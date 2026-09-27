"""Date-range helpers shared by fetching and caching logic."""
from __future__ import annotations

import datetime as dt
import re

ISO_FMT = "%Y-%m-%d"
API_DAILY_FMT = "%Y%m%d"


def parse_iso(value: str) -> dt.date:
    return dt.datetime.strptime(value, ISO_FMT).date()


def to_api_date(d: dt.date, granularity: str, is_end: bool = False) -> str:
    if granularity == "monthly":
        if is_end:
            # The API treats the end as an instant: YYYYMM01 would cut the
            # final month down to its first day only.
            return d.replace(day=days_in_month(d.year, d.month)).strftime(API_DAILY_FMT)
        return d.strftime("%Y%m01")
    return d.strftime(API_DAILY_FMT)


def parse_relative_period(spec: str, end: dt.date | None = None) -> tuple[dt.date, dt.date]:
    """Parse a shorthand like '24m', '2y', '90d' into (start, end)."""
    end = end or dt.date.today()
    match = re.fullmatch(r"(\d+)([dmy])", spec.strip().lower())
    if not match:
        raise ValueError(f"Invalid period '{spec}'. Use forms like 30d, 6m, 2y.")
    n, unit = int(match.group(1)), match.group(2)
    if unit == "d":
        start = end - dt.timedelta(days=n)
    elif unit == "m":
        start = shift_months(end, -n)
    else:
        start = shift_months(end, -12 * n)
    return start, end


def period_end(d: dt.date, granularity: str) -> dt.date:
    """Last calendar day covered by a data point (a monthly point is keyed by
    the 1st but covers the whole month)."""
    if granularity == "monthly":
        return d.replace(day=days_in_month(d.year, d.month))
    return d


def data_range(dates: list[str], granularity: str) -> str | None:
    """The period a series actually covers, which can be narrower than the
    requested one (clamped to API coverage, unpublished current month)."""
    if not dates:
        return None
    last = period_end(dt.date.fromisoformat(dates[-1]), granularity)
    return f"{dates[0]} to {last.isoformat()}"


def shift_months(d: dt.date, months: int) -> dt.date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, days_in_month(year, month))
    return dt.date(year, month, day)


def days_in_month(year: int, month: int) -> int:
    if month == 12:
        nxt = dt.date(year + 1, 1, 1)
    else:
        nxt = dt.date(year, month + 1, 1)
    return (nxt - dt.date(year, month, 1)).days


def expected_dates(start: dt.date, end: dt.date, granularity: str) -> list[dt.date]:
    """All dates a fully-populated series should contain between start and end,
    inclusive. Monthly series are keyed by the first of each month."""
    dates: list[dt.date] = []
    if granularity == "monthly":
        cur = start.replace(day=1)
        end_marker = end.replace(day=1)
        while cur <= end_marker:
            dates.append(cur)
            cur = shift_months(cur, 1)
    else:
        cur = start
        while cur <= end:
            dates.append(cur)
            cur += dt.timedelta(days=1)
    return dates


def missing_ranges(
    expected: list[dt.date], cached_dates: set[str], granularity: str
) -> list[tuple[dt.date, dt.date]]:
    """Group expected dates not present in cached_dates into contiguous
    (start, end) ranges, so each gap needs exactly one API call."""
    missing = [d for d in expected if d.isoformat() not in cached_dates]
    if not missing:
        return []
    ranges: list[tuple[dt.date, dt.date]] = []
    range_start = missing[0]
    prev = missing[0]
    for d in missing[1:]:
        contiguous = (
            (granularity == "daily" and (d - prev).days == 1)
            or (granularity == "monthly" and shift_months(prev, 1) == d)
        )
        if not contiguous:
            ranges.append((range_start, prev))
            range_start = d
        prev = d
    ranges.append((range_start, prev))
    return ranges

