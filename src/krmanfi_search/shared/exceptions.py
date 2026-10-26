"""Иерархия ошибок приложения."""

from __future__ import annotations


class SearchError(Exception):
    """Базовая ошибка приложения; её текст показывается пользователю."""


class DependencyMissingError(SearchError):
    """Не найден необязательный модуль или внешняя программа."""

    def __init__(self, package: str):
        """Создать ошибку.

        Args:
            package: Имя модуля или программы.
        """
        self.package = package
        super().__init__(f"Недоступна зависимость «{package}»")


class SecurityLimitError(SearchError):
    """Сработало ограничение безопасности (zip-бомба, выход за папку, лимит размера)."""


class OperationCancelledError(SearchError):
    """Операция отменена пользователем."""
