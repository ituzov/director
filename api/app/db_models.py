"""Сборник всех ORM-моделей для Alembic.

Импорт регистрирует таблицы в Base.metadata, иначе autogenerate их не увидит.
Единственное место снаружи модулей, которому можно в их models.
"""

from app.identity.models import LoginSession, User  # noqa: F401
from app.instagram.models import MetaApp  # noqa: F401
