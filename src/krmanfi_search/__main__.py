"""Точка входа: ``python -m krmanfi_search [путь]`` или ``uv run krmanfi-search [путь]``."""

from __future__ import annotations

import argparse
import multiprocessing
import sys
from collections.abc import Sequence
from pathlib import Path


def build_parser():
    """Разбор аргументов командной строки."""
    parser = argparse.ArgumentParser(prog="krmanfi-search", description="Поиск по документам")
    parser.add_argument("path", nargs="?", type=Path, help="папка или архив для поиска")
    return parser


def main(argv: Sequence[str] | None = None):
    """Запустить окно приложения."""
    multiprocessing.freeze_support()
    multiprocessing.set_start_method("spawn", force=True)
    args = build_parser().parse_args(argv)
    from krmanfi_search.presentation.app import run

    return run(sys.argv[:1], args.path)


if __name__ == "__main__":
    sys.exit(main())
