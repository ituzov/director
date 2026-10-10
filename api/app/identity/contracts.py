"""Контракт identity для соседей: справки, прочитать можно, записать в базу нельзя."""

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserRef:
    id: uuid.UUID
    role: str
    # участник с этим правом может подключать аккаунты Instagram
    can_connect_accounts: bool
