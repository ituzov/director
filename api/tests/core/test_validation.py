"""Ответ 422 на форму не повторяет присланное: в формах секреты."""

import pytest

KEY = "sk-ant-api03-0123456789abcdefWXYZ"
SECRET = "0123456789abcdef0123456789abcdeZ"


@pytest.fixture
async def owner(login_as):
    return await login_as("owner")


@pytest.mark.parametrize(
    ("method", "url", "body", "secret"),
    [
        # нет обязательного поля: input это всё тело
        ("POST", "/ai/connections", {"key": KEY}, KEY),
        # длиннее предела: input это сам ключ
        ("POST", "/ai/connections", {"provider": "anthropic", "key": KEY * 20}, KEY),
        # не тот формат секрета Meta
        ("PUT", "/instagram/app", {"app_id": "123", "app_secret": SECRET}, SECRET),
    ],
)
async def test_secret_not_echoed(client, owner, method, url, body, secret):
    r = await client.request(method, url, headers=owner, json=body)
    assert r.status_code == 422
    assert secret not in r.text
    # где ошибка, по-прежнему видно
    assert all("loc" in e and "type" in e for e in r.json()["detail"])
