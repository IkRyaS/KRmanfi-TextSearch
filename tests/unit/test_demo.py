import re

from tests.conftest import DEMO, needs_tesseract


def documented_summary():
    text = (DEMO / "README.md").read_text(encoding="utf-8")
    match = re.search(r"```\n(найдено[^\n]+)\n```", text)
    assert match, "в demo/README.md нет строки итога"
    return match.group(1)


@needs_tesseract
def test_demo_set_matches_the_documented_summary(run_search, demo):
    hits, stats = run_search(demo)
    assert stats.summary() == documented_summary()
    group = [h for h in hits if h.display_path.endswith("03_повторы_на_странице.pdf")]
    assert len(group) == 3 and {h.page for h in group} == {1}


def test_demo_regex(run_search, demo):
    hits, _ = run_search(demo / "документы", r"\d{4}-К", mode="regex", ocr_scanned_pdfs=False)
    assert [h.fragment for h in hits] == ["4711-К", "4712-К"]
