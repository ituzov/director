"""Выбор ответа под комментом: подряд не повторяемся, по очереди идём по кругу."""

import random

import pytest

from app.autoreplies.replies import RANDOM, SEQUENCE, fill, pick


@pytest.mark.parametrize("mode", [RANDOM, SEQUENCE])
def test_no_variants(mode):
    assert pick(0, None, mode) is None


@pytest.mark.parametrize("mode", [RANDOM, SEQUENCE])
def test_single_variant_repeats(mode):
    assert pick(1, 0, mode) == 0


def test_sequence_goes_round():
    last, got = None, []
    for _ in range(4):
        last = pick(3, last, SEQUENCE)
        got.append(last)
    assert got == [0, 1, 2, 0]


def test_random_never_repeats_last():
    rng = random.Random(1)
    last = None
    seen = set()
    for _ in range(200):
        chosen = pick(3, last, RANDOM, rng)
        assert chosen != last
        seen.add(chosen)
        last = chosen
    # и это правда случайно: все варианты в ходу
    assert seen == {0, 1, 2}


def test_random_from_two_alternates():
    assert pick(2, 0, RANDOM) == 1
    assert pick(2, 1, RANDOM) == 0


@pytest.mark.parametrize(
    ("text", "username", "expected"),
    [
        ("@{username}, лови в директе", "vasya", "@vasya, лови в директе"),
        ("Лови, {username}!", "vasya", "Лови, vasya!"),
        ("Отправили!", "vasya", "Отправили!"),
        ("@{username}, лови в директе", None, ", лови в директе"),
        ("Лови, {username}!", None, "Лови, !"),
    ],
)
def test_fill(text, username, expected):
    assert fill(text, username) == expected
