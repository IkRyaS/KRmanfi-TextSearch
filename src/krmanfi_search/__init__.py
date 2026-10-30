"""KRmanfi Text Search: поиск текста в документах, сканах PDF и ZIP-архивах."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("krmanfi-search")
except PackageNotFoundError:
    __version__ = "1.0.0"
