"""versions.json: разбор, кривой файл, недоступный сайт и кэш на час."""

import copy
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.updates import feed
from app.updates.feed import FeedError, Text, get_feed, parse_feed

URL = "https://site.test/versions.json"
NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)

VALID = {
    "schema": 1,
    "channels": {"stable": "0.1.1", "rc": "0.2.0-rc.1"},
    "versions": [
        {
            "version": "0.2.0-rc.1",
            "date": "2026-11-01",
            "notes": {"ru": "Проба", "en": "Trial"},
            "important": None,
            "breaking": False,
            "security": False,
            "min_from": None,
        },
        {
            "version": "0.1.1",
            "date": "2026-10-20",
            "notes": {"ru": "Исправления", "en": "Fixes"},
            "important": {"ru": "Сделайте бэкап", "en": "Back up first"},
            "breaking": True,
            "security": True,
            "min_from": "0.1.0",
        },
    ],
    "message": None,
}


@pytest.fixture(autouse=True)
def clean_cache():
    feed.reset_cache()
    yield
    feed.reset_cache()


def broken(path: str, value: object) -> dict:
    """Копия VALID с одним испорченным полем: путь через точку, индексы числами."""
    data = copy.deepcopy(VALID)
    *parents, last = path.split(".")
    node: object = data
    for key in parents:
        node = node[int(key)] if isinstance(node, list) else node[key]  # type: ignore[index]
    if value is KeyError:
        del node[last]  # type: ignore[union-attr,arg-type]
    else:
        node[int(last) if isinstance(node, list) else last] = value  # type: ignore[index]
    return data


def test_valid():
    parsed = parse_feed(VALID)
    assert parsed.channels == {"stable": "0.1.1", "rc": "0.2.0-rc.1"}
    assert [r.version for r in parsed.releases] == ["0.2.0-rc.1", "0.1.1"]
    second = parsed.releases[1]
    assert second.important == Text(ru="Сделайте бэкап", en="Back up first")
    assert (second.breaking, second.security, second.min_from) == (True, True, "0.1.0")
    assert parsed.message is None


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("schema", 2),
        ("versions", KeyError),
        ("versions.0.version", "v0.2.0"),
        ("versions.0.notes.en", ""),
        ("versions.0.notes", "просто строка"),
        ("versions.0.important", {"ru": "только русский"}),
        ("versions.0.breaking", "no"),
        ("versions.1.security", None),
        ("versions.1.min_from", "0.1"),
        ("versions.1.date", ""),
        ("channels.stable", "9.9.9"),
        ("channels.rc", KeyError),
        ("message", {"ru": "", "en": "x"}),
    ],
)
def test_invalid(path, value):
    with pytest.raises(FeedError) as error:
        parse_feed(broken(path, value))
    assert error.value.reason == "invalid"


def test_not_an_object():
    for data in ([], "versions", None):
        with pytest.raises(FeedError):
            parse_feed(data)


def site(*responses):
    """Сайт, который отвечает по очереди; calls считает запросы."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        answer = responses[min(len(calls), len(responses)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (httpx.Response(500), "unreachable"),
        (httpx.Response(404), "unreachable"),
        (httpx.ConnectError("нет сети"), "unreachable"),
        (httpx.Response(200, text="<html>заглушка хостера</html>"), "invalid"),
        (httpx.Response(200, json={"schema": 1}), "invalid"),
    ],
)
async def test_fetch_errors(answer, reason):
    http, _ = site(answer)
    with pytest.raises(FeedError) as error:
        await get_feed(http, URL, NOW)
    assert error.value.reason == reason


async def test_cached_for_an_hour():
    http, calls = site(httpx.Response(200, json=VALID))
    await get_feed(http, URL, NOW)
    await get_feed(http, URL, NOW + timedelta(minutes=59))
    assert len(calls) == 1
    await get_feed(http, URL, NOW + timedelta(hours=1))
    assert len(calls) == 2


async def test_error_cached_for_five_minutes():
    # упавший сайт не вешает каждое открытие админки на таймаут
    http, calls = site(httpx.Response(500), httpx.Response(200, json=VALID))
    with pytest.raises(FeedError):
        await get_feed(http, URL, NOW)
    with pytest.raises(FeedError):
        await get_feed(http, URL, NOW + timedelta(minutes=4))
    assert len(calls) == 1
    parsed = await get_feed(http, URL, NOW + timedelta(minutes=5))
    assert parsed.channels["stable"] == "0.1.1"
    assert len(calls) == 2
