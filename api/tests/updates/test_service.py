"""Что предложить: новые версии канала, пре-релизы только на rc, min_from и dev."""

from datetime import UTC, datetime

import httpx
import pytest

from app.config import settings
from app.updates import feed, service
from app.updates.feed import Feed, Release, Text
from app.updates.service import available

NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)


def release(version: str, min_from: str | None = None) -> Release:
    return Release(
        version=version,
        date="2026-10-13",
        notes=Text(ru=version, en=version),
        important=None,
        breaking=False,
        security=False,
        min_from=min_from,
    )


def make_feed(stable: str | None, rc: str | None, *releases: Release) -> Feed:
    return Feed(channels={"stable": stable, "rc": rc}, releases=releases, message=None)


FEED = make_feed(
    "0.1.2",
    "0.2.0-rc.1",
    release("0.1.0"),
    release("0.1.1"),
    release("0.1.2"),
    release("0.2.0-rc.1"),
    release("0.1.2-rc.1"),
)


def versions(result) -> list[str]:
    return [r.version for r in result.releases]


def test_stable_newer_versions_newest_first():
    result = available(FEED, current="0.1.0", channel="stable")
    assert result.latest == "0.1.2"
    # 0.1.2-rc.1 тоже новее 0.1.0, но на stable пре-релизы не показываем
    assert versions(result) == ["0.1.2", "0.1.1"]
    assert result.blocked is None


def test_rc_includes_prereleases():
    result = available(FEED, current="0.1.1", channel="rc")
    assert result.latest == "0.2.0-rc.1"
    assert versions(result) == ["0.2.0-rc.1", "0.1.2", "0.1.2-rc.1"]


@pytest.mark.parametrize("current", ["0.1.2", "0.1.3", "1.0.0"])
def test_up_to_date(current):
    result = available(FEED, current=current, channel="stable")
    assert (result.latest, result.releases, result.blocked) == (None, (), None)


def test_channel_without_releases():
    result = available(make_feed(None, None, release("0.1.0")), current="0.0.1", channel="stable")
    assert (result.latest, result.blocked) == (None, None)


def test_release_ahead_of_channel_is_hidden():
    # запись 0.1.3 уже на сайте, а канал ещё не переключили: раньше времени не показываем
    data = make_feed("0.1.2", None, release("0.1.2"), release("0.1.3"))
    result = available(data, current="0.1.1", channel="stable")
    assert (result.latest, versions(result)) == ("0.1.2", ["0.1.2"])


def test_dev_build_gets_nothing():
    result = available(FEED, current="dev", channel="stable")
    assert (result.latest, result.blocked) == (None, "dev")


def test_unknown_channel():
    result = available(FEED, current="0.1.0", channel="beta")
    assert (result.latest, result.blocked) == (None, "channel")


def test_min_from_blocks_long_jump():
    data = make_feed("0.3.0", None, release("0.2.0"), release("0.3.0", min_from="0.2.0"))
    result = available(data, current="0.1.0", channel="stable")
    # что впереди, видно, но прыгать нельзя: сначала 0.2.0
    assert result.latest == "0.3.0"
    assert versions(result) == ["0.3.0", "0.2.0"]
    assert (result.blocked, result.min_from) == ("min_from", "0.2.0")


@pytest.mark.parametrize("current", ["0.2.0", "0.2.1"])
def test_min_from_allows_from_that_version(current):
    data = make_feed("0.3.0", None, release("0.2.0"), release("0.3.0", min_from="0.2.0"))
    result = available(data, current=current, channel="stable")
    assert (result.latest, result.blocked) == ("0.3.0", None)


@pytest.fixture
def site(monkeypatch):
    feed.reset_cache()
    monkeypatch.setattr(settings, "app_version", "0.1.0")
    monkeypatch.setattr(settings, "director_channel", "stable")
    yield
    feed.reset_cache()


async def test_check_reports_site_error(site):
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    state = await service.check(http, NOW)
    assert (state.current, state.channel, state.error) == ("0.1.0", "stable", "unreachable")
    assert state.available is None


async def test_check_ok(site):
    body = {
        "schema": 1,
        "channels": {"stable": "0.1.1", "rc": None},
        "versions": [
            {
                "version": "0.1.1",
                "date": "2026-10-20",
                "notes": {"ru": "Исправления", "en": "Fixes"},
                "important": None,
                "breaking": False,
                "security": False,
                "min_from": None,
            }
        ],
        "message": {"ru": "Привет", "en": "Hi"},
    }
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))
    )
    state = await service.check(http, NOW)
    assert state.error is None
    assert state.available is not None and state.available.latest == "0.1.1"
    assert state.message == Text(ru="Привет", en="Hi")
