"""Совпадение коммента со словами автоответов. Чистые функции: без базы и сети.

Совпадение точное по словам: «гайды» не «гайд». Какие автоответы участвуют
(частный поста или общие), решает сервис, сюда приходят готовые кандидаты.
"""

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

_WORD = re.compile(r"\w+")


def tokens(text: str) -> list[str]:
    """Слова текста: нижний регистр, ё как е, всё не буква и не цифра разделяет."""
    return _WORD.findall(text.lower().replace("ё", "е"))


def normalize(word: str) -> str:
    """Слово или фраза автоответа в виде для сравнения: «Хочу  Гайд!» → «хочу гайд»."""
    return " ".join(tokens(word))


@dataclass(frozen=True, slots=True)
class Candidate:
    autoreply_id: uuid.UUID
    # нормализованные слова и фразы
    keywords: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Match:
    autoreply_id: uuid.UUID
    keyword: str


def find_match(text: str, candidates: Iterable[Candidate]) -> Match | None:
    """Чьё слово стоит в комменте раньше всех; в одном месте выигрывает длинная фраза."""
    words = tokens(text)
    # (позиция, -длина фразы): меньше значит лучше
    best: tuple[tuple[int, int], Match] | None = None
    for candidate in candidates:
        for keyword in candidate.keywords:
            phrase = keyword.split()
            position = _find(words, phrase)
            if position is None:
                continue
            rank = (position, -len(phrase))
            if best is None or rank < best[0]:
                best = (rank, Match(candidate.autoreply_id, keyword))
    return best[1] if best else None


def _find(words: list[str], phrase: list[str]) -> int | None:
    """Где фраза впервые стоит подряд среди слов; None, если нигде."""
    if not phrase:
        return None
    for i in range(len(words) - len(phrase) + 1):
        if words[i : i + len(phrase)] == phrase:
            return i
    return None
