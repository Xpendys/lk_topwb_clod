"""
Запросы для личного кабинета: статистика партнёра, список рефералов, начисления.
"""
from __future__ import annotations

from typing import TypedDict

from .db import db_cursor


class UserStats(TypedDict):
    referrals_count: int
    paid_deals_count: int
    total_earned: int     # всего начислено за всё время
    total_paid_out: int   # всего выплачено
    balance: int          # к выплате (earned - paid_out)


def get_user_stats(user_id: int) -> UserStats:
    with db_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM referrals WHERE user_id = ?",
            (user_id,),
        )
        referrals_count = int(cur.fetchone()["c"])

        cur.execute(
            """
            SELECT
                COUNT(*) AS deals,
                COALESCE(SUM(commission_amount), 0) AS earned
            FROM commissions WHERE user_id = ?
            """,
            (user_id,),
        )
        row = cur.fetchone()
        paid_deals_count = int(row["deals"])
        total_earned = int(row["earned"])

        cur.execute(
            "SELECT COALESCE(SUM(amount), 0) AS p FROM payouts WHERE user_id = ?",
            (user_id,),
        )
        total_paid_out = int(cur.fetchone()["p"])

    return UserStats(
        referrals_count=referrals_count,
        paid_deals_count=paid_deals_count,
        total_earned=total_earned,
        total_paid_out=total_paid_out,
        balance=total_earned - total_paid_out,
    )


def get_user_commissions(user_id: int) -> list[dict]:
    """Список начислений с информацией о реферале."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
                c.id,
                c.amo_lead_id,
                c.deal_budget,
                c.commission_amount,
                c.created_at,
                COALESCE(r.contact_label, '—') AS contact_label
            FROM commissions c
            LEFT JOIN referrals r ON r.id = c.referral_id
            WHERE c.user_id = ?
            ORDER BY c.created_at DESC
            """,
            (user_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_all_users_admin() -> list[dict]:
    """Все партнёры с балансом и реквизитами (для админ-панели)."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT
                u.id,
                u.first_name,
                u.last_name,
                u.email,
                u.ref_code,
                COALESCE(u.requisites_phone, '') AS requisites_phone,
                COALESCE(u.requisites_name, '') AS requisites_name,
                COALESCE(SUM(c.commission_amount), 0) AS total_earned,
                COALESCE(pp.total_paid, 0) AS total_paid_out,
                COALESCE(SUM(c.commission_amount), 0) - COALESCE(pp.total_paid, 0) AS balance,
                (SELECT COUNT(*) FROM referrals r WHERE r.user_id = u.id) AS referrals_count
            FROM users u
            LEFT JOIN commissions c ON c.user_id = u.id
            LEFT JOIN (
                SELECT user_id, SUM(amount) AS total_paid FROM payouts GROUP BY user_id
            ) pp ON pp.user_id = u.id
            GROUP BY u.id
            ORDER BY balance DESC
        """)
        return [dict(row) for row in cur.fetchall()]


def get_user_referrals(user_id: int) -> list[dict]:
    """Список приглашённых клиентов."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
                r.id,
                r.amo_contact_id,
                r.contact_label,
                r.first_seen_at,
                (SELECT COUNT(*) FROM commissions WHERE referral_id = r.id) AS deals_count,
                (SELECT COALESCE(SUM(commission_amount), 0) FROM commissions WHERE referral_id = r.id) AS earned
            FROM referrals r
            WHERE r.user_id = ?
            ORDER BY r.first_seen_at DESC
            """,
            (user_id,),
        )
        return [dict(row) for row in cur.fetchall()]
