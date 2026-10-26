"""Проверки конфигурации выдачи: версии, настройки, состав архивов."""

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


def test_requirements_txt_matches_pyproject_pins():
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").split()
    assert lines == project()["dependencies"]
    assert all("==" in line for line in lines)


def test_default_settings_file_is_valid():
    from krmanfi_search.infrastructure.config import Settings

    loaded = Settings.load(ROOT / "settings.toml")
    assert loaded.load_error is None and loaded.ocr.languages == ["rus", "eng"]


def test_release_check_flags_forbidden_content(tmp_path):
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import check_release

    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "a.pyc").write_bytes(b"x")
    (tmp_path / "run.log").write_text("x", encoding="utf-8")
    (tmp_path / "a.py").write_text('pass' + 'word = "' + 'x' * 12 + '"\n', encoding="utf-8")
    (tmp_path / "ok.txt").write_text("обычный текст", encoding="utf-8")
    problems = " ".join(check_release.check(tmp_path))
    assert "__pycache__" in problems and "run.log" in problems and "password" in problems
    assert "ok.txt" not in problems


def test_vendor_tesseract_is_preferred(tmp_path, monkeypatch):
    from krmanfi_search.infrastructure.ocr.tesseract import find_tesseract
    from krmanfi_search.shared import runtime

    name = "tesseract.exe" if __import__("sys").platform == "win32" else "tesseract"
    folder = tmp_path / "vendor" / "tesseract"
    folder.mkdir(parents=True)
    (folder / name).write_text("", encoding="utf-8")
    monkeypatch.setenv("KRMANFI_VENDOR_DIR", str(tmp_path / "vendor"))
    runtime.vendor_tesseract.cache_clear()
    try:
        assert find_tesseract() == str(folder / name)
    finally:
        runtime.vendor_tesseract.cache_clear()
