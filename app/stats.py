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
                COALESCE(c.commission_level, 1) AS commission_level,
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
                COALESCE(u.requisites_bank, '') AS requisites_bank,
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
        users = [dict(row) for row in cur.fetchall()]

        cur.execute("""
            SELECT
                parent.id AS parent_id,
                child.id AS partner_id,
                child.first_name,
                child.last_name,
                child.email,
                child.ref_code,
                child.created_at,
                COUNT(DISTINCT r.id) AS clients_count,
                COUNT(DISTINCT c.amo_lead_id) AS paid_deals_count,
                COALESCE(SUM(c.commission_amount), 0) AS earned_for_parent
            FROM users child
            JOIN users parent ON parent.id = child.parent_user_id
            LEFT JOIN referrals r ON r.user_id = child.id
            LEFT JOIN commissions c
                ON c.user_id = parent.id
                AND c.commission_level = 2
                AND c.referral_id = r.id
            GROUP BY child.id
            ORDER BY earned_for_parent DESC, child.created_at DESC
        """)
        second_level_by_parent: dict[int, list[dict]] = {}
        for row in cur.fetchall():
            item = dict(row)
            parent_id = int(item.pop("parent_id"))
            second_level_by_parent.setdefault(parent_id, []).append(item)

    for user in users:
        partners = second_level_by_parent.get(int(user["id"]), [])
        user["second_level_partners"] = partners
        user["second_level_partners_count"] = len(partners)
        user["second_level_earned"] = sum(int(p["earned_for_parent"]) for p in partners)

    return users
