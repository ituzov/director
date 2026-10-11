"""Выбор варианта ответа под комментом. Чистая функция: без базы."""

import random

RANDOM = "random"
SEQUENCE = "sequence"


def pick(count: int, last: int | None, mode: str, rng: random.Random | None = None) -> int | None:
    """Номер варианта из count. Подряд один и тот же не берём, если есть из чего выбрать.
    None: вариантов нет, под комментом не отвечаем."""
    if count == 0:
        return None
    if count == 1:
        return 0
    if mode == SEQUENCE:
        return 0 if last is None else (last + 1) % count
    choices = [i for i in range(count) if i != last]
    return (rng or random).choice(choices)


def fill(text: str, username: str | None) -> str:
    """Подставить ник: «@{username}, лови» → «@vasya, лови». Ника нет: «@» тоже убираем."""
    if username:
        return text.replace("{username}", username)
    return " ".join(text.replace("@{username}", "").replace("{username}", "").split())
