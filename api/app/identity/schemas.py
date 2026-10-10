"""Схемы HTTP: что ручки identity принимают и отдают. Модели наружу не отдаём."""

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Argon2 хеширует пароль любой длины, но мегабайтный пароль это лишняя нагрузка
MAX_PASSWORD_LENGTH = 1024


class SetupIn(BaseModel):
    token: str
    email: EmailStr
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class TokenOut(BaseModel):
    token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: str
    can_connect_accounts: bool
