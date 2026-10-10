"""Настройки приложения: всё берём из переменных окружения.

В разработке они лежат в api/.env (не в git), шаблон в api/.env.example.
В docker compose приходят через environment.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # api/.env рядом с проектом, а не в текущей папке: тесты и IDE запускают откуда угодно.
    # В Docker файла нет, это не ошибка: значения приходят из окружения
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / ".env", extra="ignore"
    )

    # postgresql+psycopg://user:pass@host:port/dbname
    database_url: str
    # Из него выводятся ключи шифрования секретов в базе. Потерян или
    # заменён: зашифрованное раньше не расшифровать
    secret_key: str
    # одноразовый токен регистрации владельца, кладёт установщик.
    # Не задан: setup выключен
    setup_token: str | None = None


settings = Settings()  # type: ignore[call-arg]  # значения приходят из окружения
