from wikitrends.cli import _before_you_write, _compact


def _result(label, daily, spikes=None):
    return {"label": label, "trend": {"median_daily_views": daily, "confidence": "high"},
            "recurring_spike_months": spikes or []}


def test_notes_order_volume_and_flag_missing_editions():
    results = [_result("vi: A", 479), _result("es: B", 947, [{"month": 9, "years": [2024, 2025]}])]
    notes = _before_you_write(results, comparing=True, missing=["No pl.wikipedia article is linked to this concept yet."])
    volume = next(n for n in notes if n.startswith("Daily views"))
    assert volume.index("es: B") < volume.index("vi: A")
    assert any("not evidence of demand" in n and "pl.wikipedia" in n for n in notes)
    assert any("month 9 in 2024/2025" in n for n in notes)


def test_compact_drops_series_but_keeps_anomaly_views_and_rounds():
    full = {"dates": ["2024-01-01"], "views": [1], "trend": {"pct_change_per_year": -37.70118,
            "anomalies": [{"date": "2024-01-01", "views": 12538, "expected": 11590.0}]}}
    out = _compact(full)
    assert "dates" not in out and "views" not in out
    assert out["trend"]["pct_change_per_year"] == -37.7
    assert out["trend"]["anomalies"][0]["views"] == 12538
