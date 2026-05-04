"""
Конфиг приложения. Все настройки берутся из переменных окружения (.env файл).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Cекреты
    SECRET_KEY: str = "dev-secret-change-me"
    ALBATO_WEBHOOK_SECRET: str = "dev-webhook-secret-change-me"
    ADMIN_LOGIN: str = "admin_topwb"
    ADMIN_PASSWORD: str = "admin_topwb"

    # Почта для подтверждения регистрации
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "Топай в ТОП"
    SMTP_USE_TLS: bool = True

    # URL'ы
    PUBLIC_SITE_URL: str = "https://www.toptopwb.ru"
    LK_BASE_URL: str = "https://referal.toptopwb.ru"

    # Бизнес-логика
    COMMISSION_PERCENT: int = 10

    # БД
    DATABASE_PATH: str = "./referal.db"


settings = Settings()
