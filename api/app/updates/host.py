"""Обмен с хостом через файлы. Хост это install.sh от root, его запускает systemd.

request/ (наша, uid 1000): кладём просьбу `update` с версией, `director-update.path`
видит файл и запускает `install.sh request`, тот удаляет файл и обновляет.
run/ (root, у нас только чтение): `update-status` одна строка «время шаг»,
`update.log` весь вывод обновления. Сюда мы не пишем никогда: root не должен
трогать то, что мог подложить api.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.updates.exceptions import NotInstalled

REQUEST = "update"
BOARD = "update-status"
LOG = "update.log"


@dataclass(frozen=True)
class BoardLine:
    at: datetime
    # «pull 0.1.1», «done 0.1.0 -> 0.1.1», «error: …»
    text: str


def write_request(request_dir: Path, version: str) -> None:
    """Положить просьбу в лоток. Целиком или никак: systemd ждёт сам файл `update`,
    и недописанный он увидеть не должен, поэтому пишем рядом и переименовываем."""
    if not request_dir.is_dir():
        raise NotInstalled
    tmp = request_dir / f"{REQUEST}.tmp"
    tmp.write_text(f"{version}\n")
    os.replace(tmp, request_dir / REQUEST)


def request_waiting_since(request_dir: Path) -> datetime | None:
    """Когда положили просьбу, которую хост ещё не забрал. Забрал или нет: None."""
    try:
        return datetime.fromtimestamp((request_dir / REQUEST).stat().st_mtime, UTC)
    except FileNotFoundError:
        return None


def read_board(run_dir: Path) -> BoardLine | None:
    """Последний шаг обновления. Доски нет или строка кривая: None."""
    try:
        line = (run_dir / BOARD).read_text().strip()
    except FileNotFoundError:
        return None
    stamp, _, text = line.partition(" ")
    try:
        at = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return BoardLine(at=at, text=text) if text else None


def read_log_tail(run_dir: Path, lines: int) -> tuple[str, ...]:
    """Последние строки лога обновления: по ним видно, что сломалось."""
    try:
        text = (run_dir / LOG).read_text(errors="replace")
    except FileNotFoundError:
        return ()
    return tuple(text.splitlines()[-lines:])
