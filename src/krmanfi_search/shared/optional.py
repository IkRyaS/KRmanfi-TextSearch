from __future__ import annotations

import importlib
import os
import shutil
from functools import cache

from krmanfi_search.shared.exceptions import DependencyMissingError


@cache
def optional_import(module: str):
    """Импортировать ``module`` или вернуть ``None``, если его нет.

    Args:
        module: Имя модуля с точками.
    """
    try:
        return importlib.import_module(module)
    except Exception:
        return None


def require(module: str):
    """Импортировать ``module`` или поднять ошибку.

    Args:
        module: Имя модуля с точками.

    Raises:
        DependencyMissingError: Если импорт не удался.
    """
    imported = optional_import(module)
    if imported is None:
        raise DependencyMissingError(module)
    return imported


@cache
def which(binary: str):
    """Найти программу: ``vendor``, затем ``PATH``, затем стандартные папки Windows.

    Args:
        binary: Имя программы без расширения.
    """
    from krmanfi_search.shared.runtime import vendor_roots

    paths = [str(root / binary) for root in vendor_roots()]
    paths += [str(root) for root in vendor_roots()]
    found = shutil.which(binary, path=os.pathsep.join(paths))
    return found or shutil.which(binary)
