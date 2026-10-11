"""Подпись данных, которые уходят наружу и возвращаются к нам: state входа через Instagram.

Это не шифрование: содержимое видно любому, но подделать его или выдать за свежее нельзя.
Ключ у каждого назначения свой, выведен из SECRET_KEY через HKDF, как в crypto:
подпись для одного назначения не подходит другому, и ни одна не совпадает с ключом шифрования.
"""

import base64
import hashlib
import hmac
import json
import time
from functools import cache

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings


class SignatureError(Exception):
    """Подпись не наша, данные испорчены или срок вышел."""


@cache
def _key(purpose: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=f"director/sign/{purpose}".encode()
    ).derive(settings.secret_key.encode())


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(body: str, purpose: str) -> str:
    return _b64(hmac.new(_key(purpose), body.encode(), hashlib.sha256).digest())


def sign(data: dict, *, purpose: str) -> str:
    """Подписать данные с временем выдачи. Ключ t занят под время."""
    body = _b64(json.dumps({**data, "t": int(time.time())}, separators=(",", ":")).encode())
    return f"{body}.{_mac(body, purpose)}"


def unsign(token: str, *, purpose: str, max_age: int) -> dict:
    """Проверить подпись и срок, вернуть данные без времени выдачи."""
    body, _, mac = token.partition(".")
    if not mac or not hmac.compare_digest(mac.encode(), _mac(body, purpose).encode()):
        raise SignatureError
    data = json.loads(_unb64(body))
    issued = data.pop("t")
    # из будущего тоже нельзя: так не продлить срок, подправив часы
    if not 0 <= time.time() - issued <= max_age:
        raise SignatureError
    return data
