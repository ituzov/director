"""Границы модулей: правила импортов из pyproject.toml соблюдены.

Тест существует, чтобы линтер импортов запускался сам. Охранник, которого
надо звать руками, через месяц перестают звать. Так нарушение границы
ловит обычный прогон pytest, кто бы ни правил код: человек или агент.
"""

from pathlib import Path

from importlinter.cli import lint_imports

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_module_boundaries():
    """Отчёт линтера уходит в stdout, pytest покажет его при падении.
    no_cache, чтобы рядом с кодом не появлялась папка кэша."""
    assert lint_imports(config_filename=str(PYPROJECT), no_cache=True, no_logo=True) == 0
