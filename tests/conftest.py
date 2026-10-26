import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("KRMANFI_SEARCH_DATA_DIR", str(Path(__file__).parent / ".data"))

from krmanfi_search.container import Container
from krmanfi_search.domain import SearchQuery, SearchStats
from krmanfi_search.infrastructure.config import Settings
from krmanfi_search.infrastructure.ocr.tesseract import find_tesseract

DEMO = Path(__file__).resolve().parents[1] / "demo"
PHRASE = "квартальный отчёт"
needs_tesseract = pytest.mark.skipif(find_tesseract() is None, reason="Tesseract не установлен")


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
