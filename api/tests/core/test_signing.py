"""Подпись: своё и свежее проходит, подделка, чужое назначение и просрочка нет."""

import time

import pytest

from app.core import signing
from app.core.signing import SignatureError

DATA = {"u": "01a12595", "n": "abc"}


def test_roundtrip():
    token = signing.sign(DATA, purpose="oauth")
    assert signing.unsign(token, purpose="oauth", max_age=600) == DATA


def test_other_purpose_rejected():
    token = signing.sign(DATA, purpose="oauth")
    with pytest.raises(SignatureError):
        signing.unsign(token, purpose="invite", max_age=600)


@pytest.mark.parametrize(
    "spoil",
    [
        # подменили данные, подпись оставили
        lambda t: (
            signing.sign({"u": "attacker"}, purpose="oauth").split(".")[0] + "." + t.split(".")[1]
        ),
        # подпись срезали или испортили
        lambda t: t.split(".")[0],
        lambda t: t[:-2] + ("AA" if not t.endswith("AA") else "BB"),
        lambda t: "",
    ],
)
def test_forgery_rejected(spoil):
    token = signing.sign(DATA, purpose="oauth")
    with pytest.raises(SignatureError):
        signing.unsign(spoil(token), purpose="oauth", max_age=600)


NOW = 1_791_700_000


def at(monkeypatch, moment: float) -> None:
    monkeypatch.setattr(time, "time", lambda: moment)


def test_fresh_within_max_age(monkeypatch):
    at(monkeypatch, NOW)
    token = signing.sign(DATA, purpose="oauth")
    at(monkeypatch, NOW + 600)
    assert signing.unsign(token, purpose="oauth", max_age=600) == DATA


def test_expired_rejected(monkeypatch):
    at(monkeypatch, NOW)
    token = signing.sign(DATA, purpose="oauth")
    at(monkeypatch, NOW + 601)
    with pytest.raises(SignatureError):
        signing.unsign(token, purpose="oauth", max_age=600)


def test_from_future_rejected(monkeypatch):
    # выдан «через час»: так не продлить срок, подправив часы
    at(monkeypatch, NOW + 3600)
    token = signing.sign(DATA, purpose="oauth")
    at(monkeypatch, NOW)
    with pytest.raises(SignatureError):
        signing.unsign(token, purpose="oauth", max_age=600)
