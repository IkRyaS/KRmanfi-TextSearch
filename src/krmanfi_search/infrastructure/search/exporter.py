"""Экспорт совпадений в CSV (UTF-8 с BOM, чтобы Excel определил кодировку)."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path

from krmanfi_search.domain import SearchHit

HEADER = ("Файл", "Страница / место", "№", "Фрагмент", "Контекст", "Совпадений на странице")
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: str):
    """Обезвредить ячейку, которую Excel мог бы выполнить как формулу."""
    return f"'{value}" if value.startswith(FORMULA_PREFIXES) else value


def export_csv(hits: Sequence[SearchHit], path: Path):
    """Записать совпадения в CSV.

    Args:
        hits: Совпадения в порядке показа.
        path: Файл назначения.

    Raises:
        OSError: Если файл нельзя записать.
    """
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        for hit in hits:
            writer.writerow(
                [
                    csv_safe(hit.display_path),
                    csv_safe(hit.location),
                    hit.occurrence,
                    csv_safe(hit.fragment),
                    csv_safe(hit.context),
                    hit.match_count,
                ]
            )
