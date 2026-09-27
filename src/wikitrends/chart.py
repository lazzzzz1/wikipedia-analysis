"""Matplotlib chart rendering. Uses the Agg backend so it works headlessly
in an agent sandbox with no display."""
from __future__ import annotations

import datetime as dt
import functools
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ft2font import FT2Font  # noqa: E402


@functools.cache
def _dejavu_codepoints() -> frozenset[int]:
    path = os.path.join(matplotlib.get_data_path(), "fonts", "ttf", "DejaVuSans.ttf")
    return frozenset(FT2Font(path).get_charmap())


def display_label(label: str) -> str:
    """DejaVu Sans (used for charts and the PDF) has no CJK, Devanagari, Thai,
    ... glyphs, so e.g. "ja.wikipedia: 英語" would render as boxes. Fall back to
    the "ja.wikipedia" part, or drop the unrenderable characters."""
    covered = _dejavu_codepoints()
    if all(ord(ch) in covered for ch in label):
        return label
    project, sep, _ = label.partition(": ")
    if sep and all(ord(ch) in covered for ch in project):
        return project
    return "".join(ch for ch in label if ord(ch) in covered).strip() or "?"


def plot_trend(
    dates: list[str], views: list[int], fit_line: list[float] | None,
    anomalies: list[dict], title: str, out_path: str,
) -> str:
    x = [dt.date.fromisoformat(dd) for dd in dates]
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.plot(x, views, color="#3b6ea5", linewidth=1.5, label="Views")
    if fit_line:
        ax.plot(x, fit_line, color="#c0392b", linewidth=1.5, linestyle="--", label="Robust trend")
    if anomalies:
        ax_dates = [dt.date.fromisoformat(a["date"]) for a in anomalies]
        ax_views = [a["views"] for a in anomalies]
        ax.scatter(ax_dates, ax_views, color="#e67e22", zorder=5, label="Anomaly", s=28)
    ax.set_title(display_label(title), fontsize=12)
    ax.set_ylabel("Pageviews")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper left")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def plot_comparison(series: dict[str, dict], title: str, ylabel: str, out_path: str) -> str:
    """series: {label: {"dates": [...], "values": [...]}}"""
    fig, ax = plt.subplots(figsize=(8, 4.2))
    for label, s in series.items():
        x = [dt.date.fromisoformat(dd) for dd in s["dates"]]
        ax.plot(x, s["values"], linewidth=1.6, label=display_label(label))
    ax.set_title(display_label(title), fontsize=12)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9, loc="best")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path
