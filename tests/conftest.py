import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("KRMANFI_SEARCH_DATA_DIR", str(Path(__file__).parent / ".data"))

from krmanfi_search.container import Container
from krmanfi_search.domain import SearchQuery, SearchStats
from krmanfi_search.infrastructure.config import Settings
from krmanfi_search.infrastructure.ocr.tesseract import find_tesseract


def pytest_configure(config: pytest.Config):
    """Временные папки внутри tests/.data: без ссылки pytest-current, которую Windows не удаляет."""
    if config.option.basetemp is None:
        base = Path(__file__).parent / ".data" / "tmp"
        base.parent.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = base


DEMO = Path(__file__).resolve().parents[1] / "demo"
PHRASE = "квартальный отчёт"


def ocr_languages_installed():
    """Есть ли Tesseract с языками rus и eng (без русского сканы читаются неверно)."""
    binary = find_tesseract()
    if binary is None:
        return False
    try:
        out = subprocess.run(
            [binary, "--list-langs"], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    langs = set(re.split(r"\s+", out.stdout + out.stderr))
    return {"rus", "eng"} <= langs


needs_tesseract = pytest.mark.skipif(
    not ocr_languages_installed(), reason="Нужен Tesseract с языками rus и eng"
)


@pytest.fixture
def demo(tmp_path: Path):
    target = tmp_path / "Тест папка" / "demo"
    shutil.copytree(DEMO, target)
    return target


@pytest.fixture
def container():
    return Container.build(Settings(workers=0))


@pytest.fixture
def run_search(container):
    def run(root: Path, text: str = PHRASE, **options: object):
        stats = SearchStats()
        query = SearchQuery(text=text, root=root, **options)
        hits = list(container.search_text(query, stats=stats))
        return hits, stats

    return run
