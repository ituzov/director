"""Сравнение версий по SemVer: пре-релиз младше релиза, номера частей как числа."""

import pytest

from app.updates.versions import is_newer, parse

# порядок из semver.org, раздел 11, плюс наши теги
ORDERED = [
    "0.0.1-rc.9",
    "0.0.1-rc.10",
    "0.0.1",
    "0.1.0-alpha",
    "0.1.0-alpha.1",
    "0.1.0-alpha.beta",
    "0.1.0-beta",
    "0.1.0-beta.2",
    "0.1.0-beta.11",
    "0.1.0-rc.1",
    "0.1.0",
    "0.1.1",
    "0.2.0",
    "0.10.0",
    "1.0.0",
]


@pytest.mark.parametrize(("older", "newer"), list(zip(ORDERED, ORDERED[1:], strict=False)))
def test_order(older, newer):
    assert is_newer(newer, older)
    assert not is_newer(older, newer)


def test_same_version_is_not_newer():
    assert not is_newer("0.1.0", "0.1.0")
    assert not is_newer("0.1.0-rc.2", "0.1.0-rc.2")


@pytest.mark.parametrize("bad", ["dev", "v0.1.0", "0.1", "0.1.0-", "0.1.0+build", "", "1.2.3.4"])
def test_not_a_version(bad):
    assert parse(bad) is None
    # dev-сборка и кривая запись в versions.json не дают «новой версии»
    assert not is_newer(bad, "0.1.0")
    assert not is_newer("0.1.0", bad)
