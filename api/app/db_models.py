"""Сборник всех ORM-моделей для Alembic.

Импорт регистрирует таблицы в Base.metadata, иначе autogenerate их не увидит.
Единственное место снаружи модулей, которому можно в их models.
"""

from app.identity.models import User  # noqa: F401
