"""Trend and confidence statistics for a pageviews series.

The headline number is a Theil-Sen slope fit on log1p(views): it is much
less sensitive to a single traffic spike (a news event, a viral post) than
an ordinary least-squares fit on raw counts would be. A slope alone says
nothing about whether it is *real*, so every trend also gets a confidence
tier derived from traffic volume, the width of the slope's confidence
interval, and R^2 -- this is the mechanism that lets the skill answer
"how much should I trust this growth?" instead of just "is it growing?".
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
from scipy import stats as spstats

from . import constants as c


@dataclass
class Anomaly:
    date: str
    views: float
    expected: float
    kind: str  # "spike" | "dip"


@dataclass
class TrendResult:
    n_points: int
    avg_views: float
    median_views: float
    median_daily_views: float  # volume in views/day regardless of granularity
    pct_change_per_year: float | None
    pct_change_ci: tuple[float, float] | None
    r_squared: float | None
    direction: str  # "growing" | "declining" | "flat" | "insufficient_data"
    confidence: str  # "high" | "medium" | "low"
    confidence_reasons: list[str]
    anomalies: list[Anomaly]
    fit_line: list[float] | None  # same length as input, for charting


def compute_trend(
    dates: list[str], views: list[float], volume_views: list[float] | None = None,
) -> TrendResult:
    """volume_views: raw pageviews to judge traffic volume by, when `views`
    is a derived series (e.g. share per million) whose scale isn't views."""
    n = len(views)
    anomalies = _detect_anomalies(dates, views)
    per_day = 1.0 if _granularity_hint(dates) == "daily" else 1 / 30.4375
    volume_source = volume_views if volume_views is not None else views
    daily_median = float(np.median(volume_source)) * per_day if volume_source else 0.0

    if n < c.MIN_POINTS_FOR_TREND:
        return TrendResult(
            n_points=n,
            avg_views=float(np.mean(views)) if views else 0.0,
            median_views=float(np.median(views)) if views else 0.0,
            median_daily_views=daily_median,
            pct_change_per_year=None, pct_change_ci=None, r_squared=None,
            direction="insufficient_data", confidence="low",
            confidence_reasons=[f"Only {n} data points; need at least {c.MIN_POINTS_FOR_TREND}."],
            anomalies=anomalies, fit_line=None,
        )

    # Use real elapsed days, not point index, as x. Otherwise a monthly series
    # (index steps of "1" per month) would get annualized as if each step
    # were one day, inflating pct_change_per_year by roughly 30x.
    first_date = dt.date.fromisoformat(dates[0])
    x = np.array([(dt.date.fromisoformat(dd) - first_date).days for dd in dates], dtype=float)
    y = np.asarray(views, dtype=float)
    log_y = np.log1p(y)

    slope, intercept, low_slope, high_slope = spstats.theilslopes(log_y, x, alpha=0.95)
    fit_line = list(np.expm1(intercept + slope * x))

    pct_per_year = (np.exp(slope * 365.25) - 1) * 100
    pct_ci = (
        (np.exp(low_slope * 365.25) - 1) * 100,
        (np.exp(high_slope * 365.25) - 1) * 100,
    )

    if np.all(y == y[0]):
        r_squared = 1.0 if slope == 0 else 0.0
    else:
        ols_slope, ols_intercept = np.polyfit(x, log_y, 1)
        pred = ols_intercept + ols_slope * x
        ss_res = float(np.sum((log_y - pred) ** 2))
        ss_tot = float(np.sum((log_y - np.mean(log_y)) ** 2))
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    median_views = float(np.median(y))
    avg_views = float(np.mean(y))

    reasons: list[str] = []
    low_volume = daily_median < c.LOW_VOLUME_DAILY_VIEWS
    if low_volume:
        confidence = "low"
        reasons.append(
            f"Median traffic (~{daily_median:.0f} views/day) is low; random noise can "
            "dominate any apparent trend at this volume."
        )
    elif pct_ci[0] <= 0 <= pct_ci[1]:
        confidence = "low"
        reasons.append("The trend's 95% confidence interval includes 0% change -- not statistically distinguishable from flat.")
    elif r_squared is not None and r_squared >= 0.2 and (pct_ci[1] - pct_ci[0]) < 3 * max(abs(pct_per_year), 1e-6):
        confidence = "high"
        reasons.append(f"Consistent trend (R^2={r_squared:.2f}) with a reasonably tight confidence interval.")
    else:
        confidence = "medium"
        reasons.append("Directionally consistent but noisy; treat the exact magnitude as approximate.")

    if abs(pct_per_year) < c.FLAT_BAND_PCT_PER_YEAR:
        direction = "flat"
    elif pct_per_year > 0:
        direction = "growing"
    else:
        direction = "declining"

    if len(anomalies) > max(1, n * 0.1):
        reasons.append(
            f"{len(anomalies)} unusually spiky data point(s) detected; the trend line uses a "
            "spike-resistant estimator, but a manual look at those dates is still worthwhile."
        )

    return TrendResult(
        n_points=n, avg_views=avg_views, median_views=median_views, median_daily_views=daily_median,
        pct_change_per_year=float(pct_per_year), pct_change_ci=(float(pct_ci[0]), float(pct_ci[1])),
        r_squared=float(r_squared) if r_squared is not None else None,
        direction=direction, confidence=confidence, confidence_reasons=reasons,
        anomalies=anomalies, fit_line=fit_line,
    )


def _granularity_hint(dates: list[str]) -> str:
    if len(dates) < 2:
        return "daily"
    d0 = dt.date.fromisoformat(dates[0])
    d1 = dt.date.fromisoformat(dates[1])
    return "monthly" if (d1 - d0).days >= 28 else "daily"


def _detect_anomalies(dates: list[str], views: list[int]) -> list[Anomaly]:
    n = len(views)
    if n < 5:
        return []
    y = np.asarray(views, dtype=float)
    anomalies: list[Anomaly] = []
    half = 2
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        neighborhood = np.delete(y[lo:hi], i - lo)
        if len(neighborhood) < 3:
            continue
        med = float(np.median(neighborhood))
        mad = float(np.median(np.abs(neighborhood - med))) or 1.0
        dev = abs(y[i] - med)
        # The relative floor matters on smooth high-traffic series, where the
        # MAD of 4 neighbours is tiny and a +-8% wobble would otherwise count.
        if dev > c.ANOMALY_MAD_MULTIPLIER * mad and dev > 5 and dev > c.ANOMALY_MIN_REL_DEVIATION * med:
            value = int(y[i]) if float(y[i]).is_integer() else round(float(y[i]), 3)
            kind = "spike" if y[i] > med else "dip"
            anomalies.append(Anomaly(date=dates[i], views=value, expected=med, kind=kind))
    return anomalies


def recurring_spike_months(anomalies: list[Anomaly]) -> list[dict]:
    """Calendar months that spike in at least two different years -- the
    deterministic version of "is this seasonal", so the agent doesn't have to
    eyeball dates (small models call one-off spikes seasonal)."""
    years_by_month: dict[int, set[int]] = {}
    for a in anomalies:
        if a.kind == "spike":
            d = dt.date.fromisoformat(a.date)
            years_by_month.setdefault(d.month, set()).add(d.year)
    return [
        {"month": m, "years": sorted(ys)}
        for m, ys in sorted(years_by_month.items()) if len(ys) >= 2
    ]


def compare_raw_vs_share(raw_trend: TrendResult, share_trend: TrendResult) -> list[str]:
    """Sanity-check a topic's growth against the whole edition's growth.

    If raw views are climbing only because the whole language edition is
    getting more traffic overall (more phones, more editors, platform
    growth), the topic itself is not what's actually trending -- this is
    what catches that.
    """
    notes: list[str] = []
    if raw_trend.direction == "insufficient_data" or share_trend.direction == "insufficient_data":
        return notes
    if raw_trend.direction != share_trend.direction:
        raw_pct = raw_trend.pct_change_per_year or 0.0
        share_pct = share_trend.pct_change_per_year or 0.0
        edition_move = "growth" if raw_pct > share_pct else "decline"
        notes.append(
            f"Raw views look '{raw_trend.direction}' but the article's *share* of all traffic "
            f"on this Wikipedia edition looks '{share_trend.direction}' -- part of the raw trend "
            f"is overall edition traffic {edition_move}, not topic-specific interest."
        )
    return notes
