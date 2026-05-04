"""
Регистрация, логин, сессии. Без сторонних библиотек авторизации —
максимально просто и понятно.

Сессии хранятся в подписанной куке (itsdangerous). Внутри куки лежит user_id.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from typing import Optional

import bcrypt
from fastapi import Request
from itsdangerous import BadSignature, URLSafeSerializer

from .config import settings
from .db import db_cursor

SESSION_COOKIE = "session"
ADMIN_SESSION_COOKIE = "admin_session"
_serializer = URLSafeSerializer(settings.SECRET_KEY, salt="session-v1")


# ---------- Пароли ----------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# ---------- Реф.код ----------

def generate_ref_code(length: int = 6) -> str:
    """Шестизначный код вида AB12CD. Только заглавные буквы и цифры, без 0/O/1/I."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_unique_ref_code() -> str:
    """Генерит код и проверяет что такого ещё нет в БД."""
    for _ in range(20):
        code = generate_ref_code()
        with db_cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE ref_code = ?", (code,))
            if cur.fetchone() is None:
                return code
    raise RuntimeError("Не удалось сгенерировать уникальный реф-код за 20 попыток")


# ---------- Регистрация / логин ----------

class AuthError(Exception):
    pass


class EmailNotConfirmed(AuthError):
    pass


def register_user(
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    platform: str,
) -> int:
    email = email.strip().lower()
    if not email or "@" not in email:
        raise AuthError("Введите корректный email")
    if len(password) < 6:
        raise AuthError("Пароль должен быть не короче 6 символов")
    if platform not in ("wb", "ozon", "both"):
        raise AuthError("Выберите платформу")
    if not first_name.strip() or not last_name.strip():
        raise AuthError("Введите имя и фамилию")

    ref_code = generate_unique_ref_code()
    pw_hash = hash_password(password)

    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE email = ?", (email,))
        if cur.fetchone() is not None:
            raise AuthError("Пользователь с таким email уже существует")

        cur.execute(
            """
            INSERT INTO users (ref_code, email, password_hash, first_name, last_name, platform, email_confirmed)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (ref_code, email, pw_hash, first_name.strip(), last_name.strip(), platform),
        )
        return cur.lastrowid


def authenticate(email: str, password: str) -> Optional[int]:
    email = email.strip().lower()
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, password_hash, email_confirmed FROM users WHERE email = ?",
            (email,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    if not row["email_confirmed"]:
        raise EmailNotConfirmed("Подтвердите email. Мы отправили ссылку подтверждения на вашу почту.")
    return int(row["id"])


# ---------- Подтверждение email ----------

def _hash_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def create_email_confirmation_token(user_id: int, hours: int = 24) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    expires_at = datetime.utcnow() + timedelta(hours=hours)
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO email_confirmations (user_id, token_hash, expires_at)
            VALUES (?, ?, ?)
            """,
            (user_id, token_hash, expires_at),
        )
    return token


def get_user_by_email(email: str) -> Optional[dict]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, email, first_name, email_confirmed FROM users WHERE email = ?",
            (email.strip().lower(),),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[dict]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, email, first_name, email_confirmed FROM users WHERE id = ?",
            (user_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def confirm_email_token(token: str) -> bool:
    token_hash = _hash_token(token)
    now = datetime.utcnow()
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, expires_at, used_at
            FROM email_confirmations
            WHERE token_hash = ?
            """,
            (token_hash,),
        )
        row = cur.fetchone()
        if row is None or row["used_at"] is not None:
            return False
        expires_at = row["expires_at"]
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        if expires_at < now:
            return False

        cur.execute(
            "UPDATE users SET email_confirmed = 1, email_confirmed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (row["user_id"],),
        )
        cur.execute(
            "UPDATE email_confirmations SET used_at = CURRENT_TIMESTAMP WHERE id = ?",
            (row["id"],),
        )
    return True


# ---------- Сессии ----------

def make_session_cookie(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session_cookie(value: str) -> Optional[int]:
    try:
        data = _serializer.loads(value)
    except BadSignature:
        return None
    return data.get("uid")


def current_user_id(request: Request) -> Optional[int]:
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        return None
    return read_session_cookie(cookie)


def current_user(request: Request) -> Optional[dict]:
    uid = current_user_id(request)
    if uid is None:
        return None
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, ref_code, email, first_name, last_name, platform FROM users WHERE id = ?",
            (uid,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


# ---------- Админ-сессия ----------

def admin_credentials_valid(login: str, password: str) -> bool:
    return compare_digest(login, settings.ADMIN_LOGIN) and compare_digest(
        password,
        settings.ADMIN_PASSWORD,
    )


def make_admin_session_cookie() -> str:
    return _serializer.dumps({"admin": True})


def current_admin(request: Request) -> bool:
    cookie = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not cookie:
        return False
    try:
        data = _serializer.loads(cookie)
    except BadSignature:
        return False
    return bool(data.get("admin"))
