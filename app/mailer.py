from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from .config import settings


def smtp_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM_EMAIL)


def send_email_confirmation(to_email: str, first_name: str, confirmation_url: str) -> bool:
    if not smtp_configured():
        print(f"Email confirmation link for {to_email}: {confirmation_url}")
        return False

    message = EmailMessage()
    message["Subject"] = "Подтвердите регистрацию в реферальной программе"
    message["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM_EMAIL))
    message["To"] = to_email
    message.set_content(
        "\n".join(
            [
                f"Здравствуйте, {first_name}!",
                "",
                "Чтобы завершить регистрацию в реферальной программе Топай в ТОП, подтвердите email:",
                confirmation_url,
                "",
                "Если вы не регистрировались, просто проигнорируйте это письмо.",
            ]
        )
    )

    if settings.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            if settings.SMTP_USERNAME:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls()
            if settings.SMTP_USERNAME:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)
    return True
