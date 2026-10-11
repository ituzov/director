"""Совпадение коммента со словами: точное по словам, раньше стоящее побеждает."""

import uuid

import pytest

from app.autoreplies.matching import Candidate, Match, find_match, normalize, tokens

A, B = uuid.uuid7(), uuid.uuid7()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Хочу ГАЙД!!!", ["хочу", "гайд"]),
        ("Ещё", ["еще"]),
        ("гайд🔥гайд", ["гайд", "гайд"]),
        ("#гайд @shop", ["гайд", "shop"]),
        ("guide pls", ["guide", "pls"]),
        ("топ 10", ["топ", "10"]),
        ("", []),
        ("🔥🔥", []),
    ],
)
def test_tokens(text, expected):
    assert tokens(text) == expected


def test_normalize():
    assert normalize("  Хочу,  Гайд! ") == "хочу гайд"
    assert normalize("🔥") == ""


def one(*keywords: str, autoreply_id=A) -> Candidate:
    return Candidate(autoreply_id, keywords)


@pytest.mark.parametrize(
    "text",
    ["гайд", "Гайд!!!", "напиши гайд пожалуйста", "ГАЙД 🔥", "#гайд"],
)
def test_word_found(text):
    assert find_match(text, [one("гайд")]) == Match(A, "гайд")


@pytest.mark.parametrize("text", ["я не люблю гайды", "гайдик", "гай д", ""])
def test_only_whole_word(text):
    assert find_match(text, [one("гайд")]) is None


def test_phrase_in_order_only():
    assert find_match("очень хочу гайд", [one("хочу гайд")]) == Match(A, "хочу гайд")
    assert find_match("гайд хочу", [one("хочу гайд")]) is None
    assert find_match("хочу этот гайд", [one("хочу гайд")]) is None


def test_earlier_word_wins():
    candidates = [one("гайд"), one("прайс", autoreply_id=B)]
    assert find_match("прайс и гайд", candidates) == Match(B, "прайс")
    assert find_match("гайд и прайс", candidates) == Match(A, "гайд")


def test_longer_phrase_wins_at_same_place():
    candidates = [one("хочу"), one("хочу гайд", autoreply_id=B)]
    assert find_match("хочу гайд", candidates) == Match(B, "хочу гайд")
    # в обратном порядке кандидатов то же самое
    assert find_match("хочу гайд", candidates[::-1]) == Match(B, "хочу гайд")


def test_nothing_to_match():
    assert find_match("гайд", []) is None
    assert find_match("гайд", [one("")]) is None
