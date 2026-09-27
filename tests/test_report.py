import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from wikitrends.report import build_report


def _page_count(path) -> int:
    return len(re.findall(rb"/Type\s*/Page[^s]", path.read_bytes()))


def test_long_report_stays_on_one_page_and_escapes_markup(tmp_path):
    chart = tmp_path / "chart.png"
    plt.plot([1, 2, 3]); plt.savefig(chart); plt.close()
    rows = [
        {"label": f"xx{i}.wikipedia: Article {i}", "median_daily_views": 100, "pct_change_per_year": -10.0,
         "share_pct_change_per_year": 1.0, "confidence": "high", "direction": "declining"}
        for i in range(10)
    ]
    long_text = "Traffic is <10 views/day & noisy. " * 25
    out = tmp_path / "r.pdf"
    build_report(str(out), "Title <with> markup", "2024-01-01 to 2026-01-01", rows, [str(chart)],
                 findings=long_text, recommendations=long_text, extra_limitations=["a < b"] * 5)
    assert _page_count(out) == 1


def test_bold_markdown_is_rendered_not_printed():
    from wikitrends.report import _inline_markup
    out = _inline_markup("a **declining** trend & <10 views")
    assert "**" not in out
    assert ">declining</font>" in out
    assert "&amp;" in out and "&lt;10" in out


def test_ukrainian_report_translates_fixed_text(tmp_path):
    from wikitrends.report import STRINGS
    assert STRINGS["uk"]["header"] and len(STRINGS["uk"]["limitations_list"]) == len(STRINGS["en"]["limitations_list"])
    rows = [{"label": "uk.wikipedia: Астрономія", "median_daily_views": 40, "pct_change_per_year": -5.0,
             "share_pct_change_per_year": 2.0, "confidence": "medium", "direction": "declining"}]
    out = tmp_path / "uk.pdf"
    build_report(str(out), "Астрономія", "2023-09-01 to 2026-08-31", rows, [],
                 findings="Висновок.", recommendations="Порада.", lang="uk")
    assert _page_count(out) == 1


def test_display_label_falls_back_for_unrenderable_scripts():
    from wikitrends.chart import display_label

    assert display_label("uk.wikipedia: Англійська мова") == "uk.wikipedia: Англійська мова"
    assert display_label("vi.wikipedia: Tiếng Anh") == "vi.wikipedia: Tiếng Anh"
    assert display_label("ja.wikipedia: 英語") == "ja.wikipedia"
    assert display_label("English language: 英語 vs English") == "English language"
