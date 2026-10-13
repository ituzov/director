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
    # Адрес сервера снаружи, https://... без / в конце: из него ссылки для
    # кабинета Meta и адрес возврата OAuth. Не задан: ссылок нет
    public_url: str | None = None
    # Graph API Instagram. Меняют только нагрузочный тест и e2e: там вместо Meta
    # заглушка, чтобы не слать настоящие сообщения людям
    graph_url: str = "https://graph.instagram.com"
    # Версия установки. CI вшивает её в образ, в разработке dev: тогда новых
    # версий нет, сравнивать не с чем
    app_version: str = "dev"
    # stable или rc: какие версии предлагать. rc только для тестовых серверов
    director_channel: str = "stable"
    # откуда брать список версий. Меняют только тесты
    updates_url: str = "https://opendirector.dev/versions.json"
    # Папки обмена с хостом, смонтированы в compose. В request/ api кладёт
    # просьбу обновиться (systemd на хосте её забирает), из run/ читает статус
    # и лог обновления. В разработке их нет: кнопка отвечает «только на сервере»
    updates_request_dir: Path = Path("/director/request")
    updates_run_dir: Path = Path("/director/run")
    # DEBUG, INFO, WARNING. JSON не задан: в терминале строки, иначе JSON
    log_level: str = "INFO"
    log_json: bool | None = None


settings = Settings()  # type: ignore[call-arg]  # значения приходят из окружения
