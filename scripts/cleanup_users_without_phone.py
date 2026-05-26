#!/usr/bin/env python3
"""
Удаляет пользователей без привязанного телефона в реквизитах.

По умолчанию работает в режиме проверки и ничего не удаляет.
Для реального удаления нужен флаг --apply.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import db_cursor  # noqa: E402


WHERE_WITHOUT_PHONE = "COALESCE(TRIM(requisites_phone), '') = ''"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="реально удалить пользователей")
    args = parser.parse_args()

    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM users WHERE {WHERE_WITHOUT_PHONE}")
        count = int(cur.fetchone()["c"])

        cur.execute(
            f"""
            SELECT id, email, first_name, last_name, created_at
            FROM users
            WHERE {WHERE_WITHOUT_PHONE}
            ORDER BY id DESC
            LIMIT 20
            """
        )
        rows = cur.fetchall()

        print(f"Пользователей без телефона: {count}")
        if rows:
            print("Первые 20 кандидатов на удаление:")
            for row in rows:
                print(
                    f"{row['id']} | {row['email']} | "
                    f"{row['first_name']} {row['last_name']} | {row['created_at']}"
                )

        if not args.apply:
            print("Это была проверка. Для удаления запустите с --apply")
            return 0

        cur.execute(f"DELETE FROM users WHERE {WHERE_WITHOUT_PHONE}")
        print(f"Удалено пользователей: {cur.rowcount}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
