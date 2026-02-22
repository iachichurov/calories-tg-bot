"""Проверка покрытия критического функционала без внешних зависимостей (stdlib trace)."""

from __future__ import annotations

import inspect
import os
import trace
from pathlib import Path

import pytest
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


# Гарантируем импорт модулей проекта в тестовой среде
os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("DB_USER", "test-user")
os.environ.setdefault("DB_PASS", "test-pass")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_NAME", "test-db")

import utils
from handlers import reports


CRITICAL_FUNCTIONS = [
    utils.calculate_lbm,
    utils.calculate_target_macros_and_calories,
    reports.calculate_average_for_period,
    reports.calculate_total_norm_for_period,
]


def _function_source_lines(func):
    """Возвращает реально исполняемые строки функции по таблице байткода."""
    executable = set()
    for _, _, lineno in func.__code__.co_lines():
        if lineno is None:
            continue
        if lineno == func.__code__.co_firstlineno:
            # строка с `def ...`
            continue
        executable.add(lineno)
    return sorted(executable)


def main() -> int:
    tracer = trace.Trace(count=True, trace=False)
    exit_code = tracer.runfunc(pytest.main, ["-q"])

    # pytest.main returns int exit code
    if exit_code != 0:
        print(f"pytest failed with exit code {exit_code}")
        return int(exit_code)

    results = tracer.results()
    counts = results.counts

    total_lines = 0
    covered_lines = 0

    print("Critical coverage details:")

    for func in CRITICAL_FUNCTIONS:
        lines = _function_source_lines(func)
        filename = str(Path(inspect.getsourcefile(func)).resolve())
        function_total = len(lines)
        function_covered = 0

        for lineno in lines:
            total_lines += 1
            if counts.get((filename, lineno), 0) > 0:
                covered_lines += 1
                function_covered += 1

        ratio = (function_covered / function_total * 100) if function_total else 100.0
        print(f"- {func.__module__}.{func.__name__}: {function_covered}/{function_total} ({ratio:.2f}%)")

    total_ratio = (covered_lines / total_lines * 100) if total_lines else 100.0
    print(f"TOTAL critical coverage: {covered_lines}/{total_lines} ({total_ratio:.2f}%)")

    if total_ratio < 95.0:
        print("Critical coverage below 95% threshold")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
