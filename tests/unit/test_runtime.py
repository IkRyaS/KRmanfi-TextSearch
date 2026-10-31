import tomllib
from pathlib import Path

import krmanfi_search

ROOT = Path(__file__).resolve().parents[2]


def project():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]


def test_fallback_version_matches_pyproject():
    source = (ROOT / "src" / "krmanfi_search" / "__init__.py").read_text(encoding="utf-8")
    assert f'__version__ = "{project()["version"]}"' in source
    assert krmanfi_search.__version__ == project()["version"]


def test_default_settings_file_is_valid():
    from krmanfi_search.infrastructure.config import Settings

    loaded = Settings.load(ROOT / "settings.toml")
    assert loaded.load_error is None and loaded.ocr.languages == ["rus", "eng"]
