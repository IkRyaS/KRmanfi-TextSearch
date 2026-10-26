"""Запуск внешних программ: без shell, с таймаутом и без окна консоли в Windows."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping

_LIBRARY_VARIABLES = ("LD_LIBRARY_PATH", "LIBPATH", "DYLD_LIBRARY_PATH")


def child_environment(extra: Mapping[str, str] | None = None):
    """Окружение дочернего процесса; в сборке PyInstaller возвращает системные пути библиотек.

    Args:
        extra: Переменные, которые нужно добавить или заменить.
    """
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        for variable in _LIBRARY_VARIABLES:
            original = env.pop(f"{variable}_ORIG", None)
            if original is not None:
                env[variable] = original
            else:
                env.pop(variable, None)
    if extra:
        env.update(extra)
    return env


def no_window_flags():
    """``creationflags``, скрывающие окно консоли дочернего процесса в Windows."""
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
