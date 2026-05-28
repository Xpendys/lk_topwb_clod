"""
Работа с SQLite. Используем стандартный модуль sqlite3 — никаких ORM,
чтобы было прозрачно и понятно новичку.

Схема БД:

users           — зарегистрированные партнёры (они же могут быть рефералами)
referrals       — клиенты, пришедшие по реф.ссылке (1 запись на 1 контакт АМО)
commissions     — начисления партнёрам по оплаченным сделкам
payouts         — выплаты партнёрам (заполняются вручную админом)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from .config import settings


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(
        settings.DATABASE_PATH,
        detect_types=sqlite3.PARSE_DECLTYPES,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_cursor() -> Iterator[sqlite3.Cursor]:
    """Контекст-менеджер: открыл соединение, получил курсор, закоммитил, закрыл."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Создаёт таблицы, если их ещё нет. Вызывается при старте приложения."""
    with db_cursor() as cur:
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ref_code        TEXT NOT NULL UNIQUE,
                email           TEXT NOT NULL UNIQUE,
                password_hash   TEXT NOT NULL,
                first_name      TEXT NOT NULL,
                last_name       TEXT NOT NULL,
                platform        TEXT NOT NULL CHECK (platform IN ('wb','ozon','both')),
                parent_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
                email_confirmed INTEGER NOT NULL DEFAULT 1,
                email_confirmed_at TIMESTAMP,
                created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_users_ref_code ON users(ref_code);
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

            CREATE TABLE IF NOT EXISTS referrals (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                amo_contact_id      INTEGER UNIQUE,
                contact_label       TEXT,                  -- что показываем партнёру (например "Клиент #341")
                first_seen_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_referrals_user ON referrals(user_id);
            CREATE INDEX IF NOT EXISTS idx_referrals_amo ON referrals(amo_contact_id);

            CREATE TABLE IF NOT EXISTS commissions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                referral_id     INTEGER REFERENCES referrals(id) ON DELETE SET NULL,
                amo_lead_id     INTEGER NOT NULL,          -- id сделки в АМО
                deal_budget     INTEGER NOT NULL,          -- бюджет сделки, рубли
                commission_amount   INTEGER NOT NULL,      -- начислено партнёру, рубли
                commission_level INTEGER NOT NULL DEFAULT 1 CHECK (commission_level IN (1,2)),
                created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (amo_lead_id, user_id, commission_level)
            );

            CREATE INDEX IF NOT EXISTS idx_commissions_user ON commissions(user_id);
            CREATE INDEX IF NOT EXISTS idx_commissions_lead ON commissions(amo_lead_id);

            CREATE TABLE IF NOT EXISTS payouts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                amount          INTEGER NOT NULL,
                note            TEXT,
                paid_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_payouts_user ON payouts(user_id);

            CREATE TABLE IF NOT EXISTS email_confirmations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash  TEXT NOT NULL UNIQUE,
                expires_at  TIMESTAMP NOT NULL,
                used_at     TIMESTAMP,
                created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_email_confirmations_user ON email_confirmations(user_id);
            """
        )
        for _col, _def in [
            ("requisites_phone", "TEXT"),
            ("requisites_name", "TEXT"),
            ("requisites_bank", "TEXT"),
            ("email_confirmed", "INTEGER NOT NULL DEFAULT 1"),
            ("email_confirmed_at", "TIMESTAMP"),
            ("parent_user_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL"),
        ]:
            try:
                cur.execute(f"ALTER TABLE users ADD COLUMN {_col} {_def}")
            except Exception:
                pass

        _migrate_commissions_for_two_levels(cur)


def _migrate_commissions_for_two_levels(cur: sqlite3.Cursor) -> None:
    """Переводит commissions на схему, где одна сделка может дать 10% и 5%."""
    cur.execute("PRAGMA table_info(commissions)")
    columns = {row["name"] for row in cur.fetchall()}

    cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='commissions'"
    )
    row = cur.fetchone()
    table_sql = row["sql"] if row else ""

    if "commission_level" in columns and "UNIQUE (amo_lead_id, user_id, commission_level)" in table_sql:
        return

    cur.execute("ALTER TABLE commissions RENAME TO commissions_old_two_levels")
    cur.executescript(
        """
        DROP INDEX IF EXISTS idx_commissions_user;
        DROP INDEX IF EXISTS idx_commissions_lead;

        CREATE TABLE commissions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            referral_id     INTEGER REFERENCES referrals(id) ON DELETE SET NULL,
            amo_lead_id     INTEGER NOT NULL,
            deal_budget     INTEGER NOT NULL,
            commission_amount   INTEGER NOT NULL,
            commission_level INTEGER NOT NULL DEFAULT 1 CHECK (commission_level IN (1,2)),
            created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (amo_lead_id, user_id, commission_level)
        );

        CREATE INDEX IF NOT EXISTS idx_commissions_user ON commissions(user_id);
        CREATE INDEX IF NOT EXISTS idx_commissions_lead ON commissions(amo_lead_id);
        """
    )

    old_level_expr = "commission_level" if "commission_level" in columns else "1"
    cur.execute(
        f"""
        INSERT OR IGNORE INTO commissions (
            id, user_id, referral_id, amo_lead_id, deal_budget,
            commission_amount, commission_level, created_at
        )
        SELECT
            id, user_id, referral_id, amo_lead_id, deal_budget,
            commission_amount, {old_level_expr}, created_at
        FROM commissions_old_two_levels
        """
    )
    cur.execute("DROP TABLE commissions_old_two_levels")
