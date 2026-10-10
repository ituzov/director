import pytest

from app.core import crypto


def test_roundtrip():
    token = crypto.encrypt("секрет")
    assert token != "секрет"
    assert crypto.decrypt(token) == "секрет"


def test_same_text_encrypts_differently():
    # случайный IV: по шифротексту не видно, что два секрета совпадают
    assert crypto.encrypt("a") != crypto.encrypt("a")


def test_other_key_fails():
    token = crypto._derive("другой ключ").encrypt(b"a").decode()
    with pytest.raises(crypto.DecryptError):
        crypto.decrypt(token)


def test_tampered_fails():
    token = crypto.encrypt("a")
    with pytest.raises(crypto.DecryptError):
        crypto.decrypt(token[:-4] + "AAAA")
