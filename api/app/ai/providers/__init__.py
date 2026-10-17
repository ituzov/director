"""Реестр провайдеров: вид из ai.connection.provider → профиль. Объекты без
состояния, по одному на вид. Новый провайдер добавляется строкой в REGISTRY."""

from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.base import Provider
from app.ai.providers.timeweb import TimewebProvider

REGISTRY: dict[str, Provider] = {p.kind: p for p in (AnthropicProvider(), TimewebProvider())}


def get(kind: str) -> Provider | None:
    """None: такого провайдера нет. Например, строку записала версия новее."""
    return REGISTRY.get(kind)
