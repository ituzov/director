"""Шифрование секретов, которые лежат в базе: ключи Meta, токены Instagram.

Fernet (AES + HMAC): подделанный или испорченный шифротекст не
расшифруется, а не превратится в мусор. Ключ выводится из SECRET_KEY через
HKDF с меткой назначения, поэтому SECRET_KEY может быть любой строкой, а
ключи для других задач, выведенные из неё с другой меткой, с этим не совпадут.
"""

import base64
from functools import cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings

# Метку не менять: с другой меткой выйдет другой ключ, и сохранённое не расшифровать
_PURPOSE = b"director/secrets"


class DecryptError(Exception):
    """Не расшифровалось: чужой SECRET_KEY или испорченная строка."""


def _derive(secret_key: str) -> Fernet:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_PURPOSE).derive(
        secret_key.encode()
    )
    return Fernet(base64.urlsafe_b64encode(key))


@cache
def _fernet() -> Fernet:
    # HKDF считаем один раз за процесс, ключ в настройках не меняется
    return _derive(settings.secret_key)


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token).decode()
    except InvalidToken as e:
        raise DecryptError from e
