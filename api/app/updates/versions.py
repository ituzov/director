"""Номера версий по SemVer: разбор и сравнение. Чистые функции, без сети.

Свои, а не `packaging`: та сравнивает по правилам Python (PEP 440), а наши
теги SemVer, `0.1.0-rc.2`. Формат тот же, что проверяют install.sh и
check-versions.mjs на сайте.
"""

import re

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.]+))?$")

# Ключ сортировки: сравниваются как обычные кортежи.
# Последний элемент: (1,) у релиза, (0, части...) у пре-релиза, поэтому
# 0.1.0-rc.2 младше 0.1.0. Части пре-релиза: числа (0, n) младше слов (1, s)
# и сравниваются как числа, поэтому rc.10 старше rc.9
type VersionKey = tuple[int, int, int, tuple[int | tuple[int, int] | tuple[int, str], ...]]


def parse(version: str) -> VersionKey | None:
    """Ключ для сравнения или None, если строка не версия (`dev`, `v0.1.0`)."""
    match = _SEMVER.match(version)
    if match is None:
        return None
    major, minor, patch, pre = match.groups()
    if pre is None:
        return int(major), int(minor), int(patch), (1,)
    parts = tuple((0, int(p)) if p.isdigit() else (1, p) for p in pre.split("."))
    return int(major), int(minor), int(patch), (0, *parts)


def is_newer(candidate: str, current: str) -> bool:
    """candidate новее current. Кривая строка с любой стороны: не новее."""
    a, b = parse(candidate), parse(current)
    return a is not None and b is not None and a > b
