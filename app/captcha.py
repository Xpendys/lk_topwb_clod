"""
Проверка Yandex SmartCaptcha на сервере.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib import error, parse, request

from .config import settings

logger = logging.getLogger(__name__)

VALIDATE_URL = "https://smartcaptcha.cloud.yandex.ru/validate"


@dataclass
class CaptchaResult:
    ok: bool
    message: str = ""


def smartcaptcha_configured() -> bool:
    return bool(settings.SMARTCAPTCHA_SITE_KEY and settings.SMARTCAPTCHA_SERVER_KEY)


def smartcaptcha_partly_configured() -> bool:
    return bool(settings.SMARTCAPTCHA_SITE_KEY or settings.SMARTCAPTCHA_SERVER_KEY)


def validate_smartcaptcha(token: str, user_ip: str | None) -> CaptchaResult:
    if not token.strip():
        return CaptchaResult(False, "Подтвердите, что вы не робот")
    if not settings.SMARTCAPTCHA_SERVER_KEY:
        return CaptchaResult(False, "Проверка от ботов не настроена")

    payload = {
        "secret": settings.SMARTCAPTCHA_SERVER_KEY,
        "token": token.strip(),
    }
    if user_ip:
        payload["ip"] = user_ip

    data = parse.urlencode(payload).encode("utf-8")
    req = request.Request(
        VALIDATE_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=2) as resp:
            body = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger.warning("SmartCaptcha HTTP error: status=%s body=%s", exc.code, body)
        return CaptchaResult(False, "Не удалось проверить капчу, попробуйте ещё раз")
    except error.URLError as exc:
        logger.warning("SmartCaptcha network error: %s", exc)
        return CaptchaResult(False, "Не удалось проверить капчу, попробуйте ещё раз")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("SmartCaptcha bad JSON response: %s", body)
        return CaptchaResult(False, "Не удалось проверить капчу, попробуйте ещё раз")

    if parsed.get("status") == "ok":
        return CaptchaResult(True)
    return CaptchaResult(False, parsed.get("message") or "Капча не пройдена")
