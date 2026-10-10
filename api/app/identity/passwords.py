"""Пароли: Argon2id. Хеш хранит соль и параметры в себе, отдельно их не храним."""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Параметры по умолчанию из RFC 9106 (вариант для ограниченной памяти):
# 64 МБ и 3 прохода на хеш, маленькому VPS это по силам
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Неверный пароль это False. Битый хеш в базе это баг, а не неверный
    пароль, поэтому InvalidHashError не глотаем: пусть будет видно."""
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def needs_rehash(password_hash: str) -> bool:
    """Хеш сделан со старыми параметрами: при входе перехешируем."""
    return _hasher.check_needs_rehash(password_hash)
