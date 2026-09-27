import datetime as dt

from wikitrends import dates as d


def test_expected_dates_daily():
    result = d.expected_dates(dt.date(2024, 1, 30), dt.date(2024, 2, 2), "daily")
    assert [x.isoformat() for x in result] == ["2024-01-30", "2024-01-31", "2024-02-01", "2024-02-02"]


def test_expected_dates_monthly_normalizes_to_first_of_month():
    result = d.expected_dates(dt.date(2024, 1, 15), dt.date(2024, 4, 3), "monthly")
    assert [x.isoformat() for x in result] == ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"]


def test_missing_ranges_groups_contiguous_gaps():
    expected = d.expected_dates(dt.date(2024, 1, 1), dt.date(2024, 1, 10), "daily")
    cached = {"2024-01-01", "2024-01-02", "2024-01-05", "2024-01-06", "2024-01-07", "2024-01-10"}
    gaps = d.missing_ranges(expected, cached, "daily")
    assert gaps == [
        (dt.date(2024, 1, 3), dt.date(2024, 1, 4)),
        (dt.date(2024, 1, 8), dt.date(2024, 1, 9)),
    ]


def test_missing_ranges_empty_when_fully_cached():
    expected = d.expected_dates(dt.date(2024, 1, 1), dt.date(2024, 1, 3), "daily")
    cached = {"2024-01-01", "2024-01-02", "2024-01-03"}
    assert d.missing_ranges(expected, cached, "daily") == []


def test_parse_relative_period_months():
    end = dt.date(2026, 9, 24)
    start, resolved_end = d.parse_relative_period("24m", end=end)
    assert resolved_end == end
    assert start == dt.date(2024, 9, 24)


def test_parse_relative_period_invalid():
    import pytest
    with pytest.raises(ValueError):
        d.parse_relative_period("two years")



def test_monthly_end_date_covers_the_whole_final_month():
    assert d.to_api_date(dt.date(2026, 8, 1), "monthly") == "20260801"
    assert d.to_api_date(dt.date(2026, 8, 1), "monthly", is_end=True) == "20260831"
    assert d.to_api_date(dt.date(2024, 2, 10), "monthly", is_end=True) == "20240229"
    assert d.to_api_date(dt.date(2026, 8, 15), "daily", is_end=True) == "20260815"
