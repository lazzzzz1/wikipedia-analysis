import datetime as dt

from wikitrends.stats import TrendResult, compare_raw_vs_share, compute_trend


def _monthly_dates(n: int, start=(2022, 1, 1)) -> list[str]:
    d0 = dt.date(*start)
    out = []
    for i in range(n):
        month_index = d0.month - 1 + i
        year = d0.year + month_index // 12
        month = month_index % 12 + 1
        out.append(dt.date(year, month, 1).isoformat())
    return out


def test_growing_series_is_detected_as_growing_with_decent_confidence():
    n = 24
    dates = _monthly_dates(n)
    views = [round(2000 * (1.03 ** i)) for i in range(n)]
    trend = compute_trend(dates, views)
    assert trend.direction == "growing"
    assert trend.pct_change_per_year > 0
    assert trend.confidence in ("medium", "high")
    assert trend.pct_change_ci[0] > 0  # CI shouldn't cross zero for a clean exponential rise


def test_declining_series_is_detected():
    n = 24
    dates = _monthly_dates(n)
    views = [round(5000 * (0.97 ** i)) for i in range(n)]
    trend = compute_trend(dates, views)
    assert trend.direction == "declining"
    assert trend.pct_change_per_year < 0


def test_perfectly_flat_series_is_flat_and_not_overconfident():
    n = 12
    dates = _monthly_dates(n)
    views = [1000] * n
    trend = compute_trend(dates, views)
    assert trend.direction == "flat"
    # A truly flat series has a degenerate (zero-width) CI around 0, which
    # trivially "includes 0" -- the confidence tier should not overclaim here.
    assert trend.confidence == "low"


def test_low_traffic_series_is_low_confidence_even_if_growing():
    n = 12
    dates = _monthly_dates(n)
    views = [round(5 * (1.05 ** i)) for i in range(n)]  # a handful of views/day
    trend = compute_trend(dates, views)
    assert trend.confidence == "low"
    assert any("low" in r.lower() for r in trend.confidence_reasons)


def test_too_few_points_is_insufficient_data():
    dates = _monthly_dates(3)
    views = [100, 110, 120]
    trend = compute_trend(dates, views)
    assert trend.direction == "insufficient_data"
    assert trend.confidence == "low"
    assert trend.pct_change_per_year is None


def test_spike_is_flagged_as_anomaly():
    n = 20
    dates = _monthly_dates(n)
    views = [500 for _ in range(n)]
    views[10] = 8000  # a single viral month
    trend = compute_trend(dates, views)
    flagged = {a.date: a for a in trend.anomalies}
    assert dates[10] in flagged
    assert flagged[dates[10]].kind == "spike"


def test_small_wobble_on_high_traffic_is_not_an_anomaly():
    # +-8% around 10k views: the MAD of 4 neighbours is tiny, but this is noise.
    n = 24
    dates = _monthly_dates(n)
    views = [10_000 + (800 if i % 3 == 0 else -300 if i % 3 == 1 else 100) for i in range(n)]
    assert compute_trend(dates, views).anomalies == []


def test_compare_raw_vs_share_flags_divergence():
    growing = TrendResult(
        n_points=24, avg_views=100, median_views=100, median_daily_views=3.3, pct_change_per_year=50.0,
        pct_change_ci=(10.0, 90.0), r_squared=0.5, direction="growing",
        confidence="high", confidence_reasons=[], anomalies=[], fit_line=None,
    )
    flat = TrendResult(
        n_points=24, avg_views=100, median_views=100, median_daily_views=3.3, pct_change_per_year=1.0,
        pct_change_ci=(-1.0, 3.0), r_squared=0.1, direction="flat",
        confidence="low", confidence_reasons=[], anomalies=[], fit_line=None,
    )
    notes = compare_raw_vs_share(growing, flat)
    assert notes  # raw growth not confirmed by share-of-edition -> should warn

    notes_same = compare_raw_vs_share(growing, growing)
    assert notes_same == []


def test_share_series_volume_is_judged_by_raw_views_not_share_scale():
    # Share-per-million values are tiny (~10) even for a well-read article;
    # confidence must come from the raw views, not from the share's scale.
    n = 24
    dates = _monthly_dates(n)
    raw = [round(3000 * (0.97 ** i)) for i in range(n)]
    share = [r / 30_000_000 * 1_000_000 for r in raw]
    trend = compute_trend(dates, share, volume_views=raw)
    assert trend.confidence != "low"
    assert trend.median_daily_views > 50
    assert not any("views/day) is low" in r for r in trend.confidence_reasons)


def test_median_daily_views_converts_monthly_totals():
    dates = _monthly_dates(12)
    trend = compute_trend(dates, [3044] * 12)
    assert round(trend.median_daily_views) == 100


def test_divergence_note_names_edition_decline_when_edition_traffic_shrinks():
    declining = TrendResult(
        n_points=24, avg_views=100, median_views=100, median_daily_views=3.3, pct_change_per_year=-8.0,
        pct_change_ci=(-10.0, -6.0), r_squared=0.5, direction="declining",
        confidence="high", confidence_reasons=[], anomalies=[], fit_line=None,
    )
    flat = TrendResult(
        n_points=24, avg_views=100, median_views=100, median_daily_views=3.3, pct_change_per_year=0.0,
        pct_change_ci=(-1.0, 1.0), r_squared=0.1, direction="flat",
        confidence="low", confidence_reasons=[], anomalies=[], fit_line=None,
    )
    (note,) = compare_raw_vs_share(declining, flat)
    assert "edition traffic decline" in note


def test_recurring_spike_months_needs_two_years():
    from wikitrends.stats import Anomaly, recurring_spike_months
    anomalies = [
        Anomaly("2024-09-01", 4000, 1000, "spike"), Anomaly("2025-09-01", 1600, 450, "spike"),
        Anomaly("2025-04-01", 900, 250, "spike"),  # one-off
        Anomaly("2024-01-01", 100, 300, "dip"), Anomaly("2025-01-01", 100, 300, "dip"),  # dips don't count
    ]
    assert recurring_spike_months(anomalies) == [{"month": 9, "years": [2024, 2025]}]
