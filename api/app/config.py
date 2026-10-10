"""Настройки приложения: всё берём из переменных окружения.

В разработке они лежат в api/.env (не в git), шаблон в api/.env.example.
В docker compose приходят через environment.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # postgresql+psycopg://user:pass@host:port/dbname
    database_url: str
    # одноразовый токен регистрации владельца, кладёт установщик.
    # Не задан: setup выключен
    setup_token: str | None = None


settings = Settings()  # type: ignore[call-arg]  # значения приходят из окружения
