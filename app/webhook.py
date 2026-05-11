"""
Обработчик входящего webhook'а от Albato.

Логика:
  1. Albato триггерится по событию "сделка перешла на этап Оплачено" в АМО.
  2. Albato читает бюджет оплаченной сделки и связанный контакт (включая поле REFERER контакта).
  3. Albato шлёт нам POST с JSON примерно такого вида:
     {
       "amo_lead_id": 41046651,
       "deal_budget": 40136,
       "amo_contact_id": 12345678,
       "referer_code": "AB12CD",
       "stage_name": "Оплачено"
     }
     (точные имена полей мы зададим в самом сценарии Albato — см. README.md)
  4. Запрос подписан секретным ключом в query-параметре ?secret=...
  5. Мы:
     - проверяем секрет
     - находим партнёра по referer_code
     - находим/создаём referral по amo_contact_id
     - проверяем что для этой сделки ещё не было начисления (UNIQUE на amo_lead_id)
     - считаем 10% от бюджета сделки и записываем в commissions
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from .config import settings
from .db import db_cursor

router = APIRouter()


def _ensure_referral(cur, user_id: int, amo_contact_id: Optional[int]) -> Optional[int]:
    """Находит referral по amo_contact_id или создаёт новый. Возвращает referral.id."""
    if amo_contact_id is None:
        return None

    cur.execute(
        "SELECT id FROM referrals WHERE amo_contact_id = ?",
        (amo_contact_id,),
    )
    row = cur.fetchone()
    if row is not None:
        return int(row["id"])

    # Считаем порядковый номер реферала у этого партнёра — он станет видимым "лейблом"
    cur.execute(
        "SELECT COUNT(*) + 1 AS n FROM referrals WHERE user_id = ?",
        (user_id,),
    )
    n = int(cur.fetchone()["n"])
    label = f"Клиент #{n}"

    cur.execute(
        """
        INSERT INTO referrals (user_id, amo_contact_id, contact_label)
        VALUES (?, ?, ?)
        """,
        (user_id, amo_contact_id, label),
    )
    return int(cur.lastrowid)


@router.post("/api/amo-webhook")
async def amo_webhook(
    request: Request,
    secret: str = Query(default=""),
):
    # 1) Проверка секрета
    if secret != settings.ALBATO_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Bad secret")

    # 2) Парсим JSON. Albato может слать как application/json, так и form-data —
    #    обработаем оба.
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
    else:
        form = await request.form()
        payload = dict(form)

    # 3) Достаём данные. Имена ключей должны совпадать с тем что укажешь в Albato.
    try:
        amo_lead_id = int(payload.get("amo_lead_id") or payload.get("lead_id") or 0)
        deal_budget_raw = (
            payload.get("deal_budget")
            or payload.get("budget")
            or payload.get("amount")
            or payload.get("buyout_budget")
            or payload.get("buyouts_budget")
            or payload.get("purchase_budget")
            or 0
        )
        deal_budget = int(float(deal_budget_raw))
        amo_contact_id_raw = payload.get("amo_contact_id") or payload.get("contact_id")
        amo_contact_id = int(amo_contact_id_raw) if amo_contact_id_raw else None
        referer_code = (payload.get("referer_code") or payload.get("referer") or "").strip().upper()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Bad payload format")

    if amo_lead_id <= 0:
        raise HTTPException(status_code=400, detail="amo_lead_id is required")
    if not referer_code:
        # Это нормальная ситуация — сделка пришла НЕ от реферала. Просто игнорируем.
        return {"status": "ignored", "reason": "no referer"}
    if deal_budget <= 0:
        return {"status": "ignored", "reason": "zero deal budget"}

    # 4) Идём в БД
    with db_cursor() as cur:
        # Защита от повторного начисления (Albato может ретраить запрос)
        cur.execute("SELECT 1 FROM commissions WHERE amo_lead_id = ?", (amo_lead_id,))
        if cur.fetchone() is not None:
            return {"status": "ignored", "reason": "already processed"}

        # Ищем партнёра по реф-коду
        cur.execute("SELECT id FROM users WHERE ref_code = ?", (referer_code,))
        user_row = cur.fetchone()
        if user_row is None:
            return {"status": "ignored", "reason": f"unknown referer {referer_code}"}
        user_id = int(user_row["id"])

        # Привязываем/создаём реферала
        referral_id = _ensure_referral(cur, user_id, amo_contact_id)

        # Считаем комиссию от бюджета сделки (целые рубли, отбрасываем копейки).
        commission = deal_budget * settings.COMMISSION_PERCENT // 100

        cur.execute(
            """
            INSERT INTO commissions (user_id, referral_id, amo_lead_id, deal_budget, commission_amount)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, referral_id, amo_lead_id, deal_budget, commission),
        )

    return {
        "status": "ok",
        "user_id": user_id,
        "deal_budget": deal_budget,
        "commission": commission,
    }
