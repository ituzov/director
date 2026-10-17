"""Сборник всех ORM-моделей для Alembic.

Импорт регистрирует таблицы в Base.metadata, иначе autogenerate их не увидит.
Единственное место снаружи модулей, которому можно в их models.
"""

from app.activity.models import Event  # noqa: F401
from app.ai.models import Binding, Call, Connection  # noqa: F401
from app.assistant.models import Assistant, AssistantMedia, Reply  # noqa: F401
from app.autoreplies.models import Autoreply, AutoreplyMedia, Delivery, Keyword  # noqa: F401
from app.identity.models import LoginSession, User  # noqa: F401
from app.instagram.models import Account, InboxEvent, MetaApp, OutboxTask  # noqa: F401
