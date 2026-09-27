"""Command-line entry point for the wikitrends skill.

Every subcommand prints exactly one JSON object to stdout (success or
error), so an agent never has to parse free-text output or scrape a
traceback. Redirect a `trend`/`compare` result to a file when you want to
feed it into `report` afterwards.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

from . import constants as c
from . import dates as d
from . import wikimedia_api as api
from .cache import Cache
from .chart import plot_comparison, plot_trend
from .errors import WikitrendsError
from .report import STRINGS, build_report
from .resolve import resolve_topic
from .stats import compare_raw_vs_share, compute_trend, recurring_spike_months


def _emit(payload: dict, error: bool = False) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    if error:
        sys.exit(1)


# Per-point arrays the agent never needs to read: they're for charts and
# `report`, and make up most of the payload (a 7-edition compare is ~45k chars).
_BULKY_KEYS = {"dates", "views", "share_per_million", "fit_line"}


def _compact(o):
    """Drop per-point arrays and round floats: a small model reads this, and
    shouldn't be quoting "-37.70118065948939"."""
    if isinstance(o, dict):
        return {k: _compact(v) for k, v in o.items() if not (k in _BULKY_KEYS and isinstance(v, list))}
    if isinstance(o, list):
        return [_compact(v) for v in o]
    if isinstance(o, float):
        return round(o, 2)
    return o


def _emit_result(result: dict, out: str | None) -> None:
    """With --out: full JSON to that file, a compact summary to stdout.
    Without: full JSON to stdout (backward compatible)."""
    if not out:
        _emit(result)
        return
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    full = json.loads(json.dumps(result, default=_json_default))
    Path(out).write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = _compact(full)
    for r in summary.get("results", []):
        r.pop("warnings", None)  # already merged into the top-level "warnings"
    _emit({"saved_to": str(Path(out).resolve()), **summary})


def _json_default(o):
    if dataclasses.is_dataclass(o):
        return dataclasses.asdict(o)
    if isinstance(o, dt.date):
        return o.isoformat()
    raise TypeError(f"Not serializable: {o!r}")


def _safe_filename(s: str) -> str:
    # Non-Latin titles strip to nothing under the ASCII filter, so add a short
    # hash to keep e.g. two Cyrillic titles from sharing one chart file.
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_")[:80]
    digest = hashlib.md5(s.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned}_{digest}" if cleaned else digest


def _parse_period(args) -> tuple[dt.date, dt.date]:
    if args.start and args.end:
        return d.parse_iso(args.start), d.parse_iso(args.end)
    if args.start or args.end:
        raise ValueError("Provide both --start and --end, or neither (with --last).")
    return d.parse_relative_period(args.last)


def _trend_for_article(project, title, start, end, granularity, cache, out_chart, normalize, label=None,
                       access=c.DEFAULT_ACCESS):
    warnings: list[str] = []
    article_series = api.fetch_series(project, title, start, end, granularity, access=access, cache=cache)
    warnings += article_series.warnings
    trend = compute_trend(article_series.dates, article_series.views)

    result = {
        "label": label or f"{project}: {title}",
        "project": project, "article": title, "granularity": granularity, "access": access,
        "data_range": d.data_range(article_series.dates, granularity),
        "dates": article_series.dates, "views": article_series.views,
        "trend": dataclasses.asdict(trend),
        "recurring_spike_months": recurring_spike_months(trend.anomalies),
    }

    if normalize:
        agg_series = api.fetch_series(project, None, start, end, granularity, access=access, cache=cache)
        warnings += agg_series.warnings
        share = [
            (v / t * 1_000_000) if t else 0.0
            for v, t in zip(article_series.views, agg_series.views)
        ]
        share_trend = compute_trend(article_series.dates, share, volume_views=article_series.views)
        result["share_per_million"] = share
        result["share_trend"] = dataclasses.asdict(share_trend)
        result["cross_check_notes"] = compare_raw_vs_share(trend, share_trend)

    if out_chart:
        Path(out_chart).parent.mkdir(parents=True, exist_ok=True)
        plot_trend(
            article_series.dates, article_series.views, trend.fit_line,
            [dataclasses.asdict(a) for a in trend.anomalies], result["label"], out_chart,
        )
        # Absolute, so `report` finds the chart from any working directory.
        result["chart_path"] = str(Path(out_chart).resolve())

    result["warnings"] = list(dict.fromkeys(warnings))
    return result


def _before_you_write(results: list[dict], comparing: bool, missing: list[str] | None = None) -> list[str]:
    """The interpretation rules small models skipped most in evals, put where
    the agent reads them: next to the numbers, tailored to this result."""
    notes = [
        "Quote only numbers from this output, and name the confidence tier of every trend you mention.",
        "Don't state causes (users moved to other platforms, market saturated, ...): the data "
        "shows that interest changed, not why. Label any cause as a hypothesis to test.",
    ]
    if comparing:
        notes.append(
            "To rank editions ('which audience next'), follow share_ranking (share of edition "
            "traffic), not raw views or your own judgement; say which ranks have low confidence."
        )
        by_volume = sorted(results, key=lambda r: r["trend"]["median_daily_views"], reverse=True)
        notes.append(
            "Daily views, largest first: "
            + ", ".join(f"{r['label']} ~{r['trend']['median_daily_views']:,.0f}" for r in by_volume)
            + ". Use this order when you compare audience size."
        )
    for m in missing or []:
        notes.append(
            f"{m} That's a fact about Wikipedia's coverage, not evidence of demand or a market gap; "
            "don't recommend writing Wikipedia content."
        )
    for r in results:
        if r.get("recurring_spike_months"):
            months = ", ".join(
                f"month {m['month']} in {'/'.join(map(str, m['years']))}" for m in r["recurring_spike_months"]
            )
            notes.append(f"{r['label']}: spikes recur ({months}) -- a seasonal pattern worth reporting.")
    if any(r.get("recurring_spike_months") is not None for r in results):
        notes.append("Call a spike seasonal only if it's listed in recurring_spike_months.")
    if any(r["trend"]["confidence"] == "high" for r in results):
        notes.append(
            "'high' confidence means the pageview trend is reliable, not that demand or "
            "willingness to pay is -- don't turn it into a go/no-go verdict on the product."
        )
    notes.append(
        "If the user asked about an activity (learning X) and the article is the general "
        "topic (X), say it's a proxy. Recommendations are about the user's product, not "
        "Wikipedia, and stay within the articles and editions analysed here."
    )
    return notes


def cmd_resolve(args):
    cache = Cache()
    langs = [x.strip() for x in args.langs.split(",") if x.strip()]
    res = resolve_topic(args.topic, langs, source_lang=args.source_lang, cache=cache)
    _emit(dataclasses.asdict(res))


def cmd_search(args):
    project = api.lang_to_project(args.project)
    _emit({"project": project, "query": args.query, "titles": api.search_titles(project, args.query, args.limit)})


def cmd_fetch(args):
    cache = Cache()
    start, end = _parse_period(args)
    series = api.fetch_series(
        args.project, args.article, start, end, args.granularity, access=args.access, cache=cache,
    )
    _emit({
        "project": args.project, "article": args.article, "granularity": args.granularity,
        "dates": series.dates, "views": series.views, "warnings": series.warnings,
    })


def cmd_trend(args):
    cache = Cache()
    start, end = _parse_period(args)
    out_chart = args.out_chart or f"outputs/{_safe_filename(args.project)}_{_safe_filename(args.article)}_{args.granularity}.png"
    result = _trend_for_article(
        args.project, args.article, start, end, args.granularity, cache,
        out_chart, normalize=not args.no_normalize, access=args.access,
    )
    result["requested_range"] = f"{start.isoformat()} to {end.isoformat()}"
    result["date_range"] = result["data_range"] or result["requested_range"]
    result["before_you_write"] = _before_you_write([result], comparing=False)
    _emit_result(result, args.out)


def cmd_compare(args):
    if args.topic and not args.langs:
        raise WikitrendsError("--topic requires --langs (comma-separated language codes).")
    if not args.topic and not args.articles:
        raise WikitrendsError("Provide either --topic (+ --langs) or --articles.")

    cache = Cache()
    start, end = _parse_period(args)
    entries: list[tuple[str, str, str]] = []  # (label, project, title)
    warnings: list[str] = []

    if args.topic:
        langs = [x.strip() for x in args.langs.split(",") if x.strip()]
        resolved = resolve_topic(args.topic, langs, source_lang=args.source_lang, cache=cache)
        resolve_payload = dataclasses.asdict(resolved)
        warnings += resolved.warnings
        for lang, rl in resolved.languages.items():
            if rl.found:
                entries.append((f"{lang}.wikipedia: {rl.title}", rl.project, rl.title))
    else:
        resolve_payload = None
        for chunk in args.articles.split(","):
            project, _, title = chunk.partition(":")
            if not title:
                raise WikitrendsError(f"Malformed --articles entry '{chunk}', expected project:Title.")
            entries.append((f"{project.strip()}: {title.strip()}", project.strip(), title.strip()))

    if not entries:
        raise WikitrendsError("Nothing to compare: none of the requested language editions have a matching article.")

    results = []
    series_for_chart = {}
    for label, project, title in entries:
        r = _trend_for_article(project, title, start, end, args.granularity, cache, None, normalize=True,
                               label=label, access=args.access)
        results.append(r)
        warnings += r["warnings"]
        series_for_chart[label] = {"dates": r["dates"], "values": r.get("share_per_million", r["views"])}

    out_chart = args.out_chart or f"outputs/compare_{_safe_filename(args.topic or 'articles')}_{args.granularity}.png"
    Path(out_chart).parent.mkdir(parents=True, exist_ok=True)
    plot_comparison(
        series_for_chart,
        title=f"{args.topic or 'Comparison'}: pageview share per 1M edition views",
        ylabel="Views per 1M edition pageviews", out_path=out_chart,
    )

    def _growth(r, key):
        pct = r.get(key, {}).get("pct_change_per_year")
        return pct if pct is not None else -999

    ranking_growth = sorted(results, key=lambda r: _growth(r, "trend"), reverse=True)
    ranking_share = sorted(results, key=lambda r: _growth(r, "share_trend"), reverse=True)

    share_ranking = [
        {
            "rank": i + 1, "label": r["label"],
            "share_pct_change_per_year": r.get("share_trend", {}).get("pct_change_per_year"),
            "share_confidence": r.get("share_trend", {}).get("confidence"),
            "median_daily_views": r["trend"]["median_daily_views"],
        }
        for i, r in enumerate(ranking_share)
    ]
    ranges = [r["data_range"] for r in results if r["data_range"]]
    requested = f"{start.isoformat()} to {end.isoformat()}"
    _emit_result({
        "topic": args.topic, "date_range": ranges[0] if len(set(ranges)) == 1 else requested,
        "requested_range": requested, "access": args.access,
        "resolve": resolve_payload, "results": results,
        "ranking_by_growth": [r["label"] for r in ranking_growth],
        "ranking_by_share_growth": [r["label"] for r in ranking_share],
        "share_ranking": share_ranking,
        "before_you_write": _before_you_write(
            results, comparing=len(results) > 1, missing=[w for w in warnings if w.startswith("No ")],
        ),
        "chart_path": str(Path(out_chart).resolve()), "warnings": list(dict.fromkeys(warnings)),
    }, args.out)


def cmd_report(args):
    raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
    payload = json.loads(raw)

    if "results" in payload:  # `compare` output
        rows = [
            {
                "label": r["label"], "median_daily_views": r["trend"]["median_daily_views"],
                "pct_change_per_year": r["trend"]["pct_change_per_year"],
                "share_pct_change_per_year": r.get("share_trend", {}).get("pct_change_per_year"),
                "share_confidence": r.get("share_trend", {}).get("confidence"),
                "confidence": r["trend"]["confidence"], "direction": r["trend"]["direction"],
            }
            for r in payload["results"]
        ]
        chart_paths = [payload["chart_path"]] if payload.get("chart_path") else []
        title = args.title or f"{STRINGS[args.lang]['title']}: {payload.get('topic') or 'comparison'}"
        date_range = payload.get("date_range", "")
    else:  # single `trend` output
        rows = [{
            "label": payload["label"], "median_daily_views": payload["trend"]["median_daily_views"],
            "pct_change_per_year": payload["trend"]["pct_change_per_year"],
            "share_pct_change_per_year": payload.get("share_trend", {}).get("pct_change_per_year"),
            "share_confidence": payload.get("share_trend", {}).get("confidence"),
            "confidence": payload["trend"]["confidence"], "direction": payload["trend"]["direction"],
        }]
        chart_paths = [payload["chart_path"]] if payload.get("chart_path") else []
        title = args.title or f"{STRINGS[args.lang]['title']}: {payload['label']}"
        date_range = payload.get("date_range", "")

    # A moved/copied result (e.g. examples/) may carry a chart path from another
    # machine; fall back to a chart of the same name next to the JSON file.
    if args.input != "-":
        chart_paths = [
            cp if Path(cp).exists() else str(Path(args.input).parent / Path(cp).name)
            for cp in chart_paths
        ]

    out_path = args.out or "outputs/report.pdf"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    extra_limitations = [x.strip() for x in args.limitations.split(";") if x.strip()] if args.limitations else []
    build_report(
        out_path, title, date_range, rows, chart_paths,
        findings=args.findings or "", recommendations=args.recommendations or "",
        extra_limitations=extra_limitations, lang=args.lang,
    )
    _emit({"report_path": out_path})


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wikitrends", description="Analyze Wikipedia pageview trends across languages.")
    sub = p.add_subparsers(dest="command", required=True)

    def period_args(sp):
        sp.add_argument("--start", help="YYYY-MM-DD")
        sp.add_argument("--end", help="YYYY-MM-DD")
        sp.add_argument("--last", default=c.DEFAULT_LAST, help="Shorthand like 24m, 2y, 90d, used only if --start/--end are omitted. Default: %(default)s")
        sp.add_argument("--granularity", default=c.DEFAULT_GRANULARITY, choices=["daily", "monthly"])

    def out_args(sp):
        sp.add_argument("--out", default=None, help="Save the full JSON here (input for `report`) and print only a compact summary.")
        sp.add_argument("--access", default=c.DEFAULT_ACCESS, choices=c.ACCESS_CHOICES,
                        help="Traffic type. Default: %(default)s")

    sp = sub.add_parser("resolve", help="Find the matching article for a topic across language editions.")
    sp.add_argument("--topic", required=True)
    sp.add_argument("--langs", required=True, help="Comma-separated language codes, e.g. pl,cs,uk")
    sp.add_argument("--source-lang", default="en")
    sp.set_defaults(func=cmd_resolve)

    sp = sub.add_parser("search", help="Full-text search for article titles on one edition (when resolve finds none).")
    sp.add_argument("--project", required=True, help="e.g. pl or pl.wikipedia")
    sp.add_argument("--query", required=True, help="Search words in that edition's language.")
    sp.add_argument("--limit", type=int, default=5)
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("fetch", help="Raw pageviews for one project/article, or a whole project (debug tool).")
    sp.add_argument("--project", required=True, help="e.g. pl.wikipedia")
    sp.add_argument("--article", default=None, help="Omit for whole-project totals.")
    sp.add_argument("--access", default=c.DEFAULT_ACCESS)
    period_args(sp)
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("trend", help="Fetch and analyze one article's trend.")
    sp.add_argument("--project", required=True)
    sp.add_argument("--article", required=True)
    sp.add_argument("--out-chart", default=None)
    sp.add_argument("--no-normalize", action="store_true", help="Skip the share-of-edition cross-check.")
    out_args(sp)
    period_args(sp)
    sp.set_defaults(func=cmd_trend)

    sp = sub.add_parser("compare", help="Compare a topic across languages, or explicit project:article pairs.")
    sp.add_argument("--topic", default=None)
    sp.add_argument("--langs", default=None, help="Required with --topic. Comma-separated, e.g. pl,cs")
    sp.add_argument("--source-lang", default="en")
    sp.add_argument("--articles", default=None, help='Alternative to --topic/--langs: "pl.wikipedia:Title,cs.wikipedia:Title2"')
    sp.add_argument("--out-chart", default=None)
    out_args(sp)
    period_args(sp)
    sp.set_defaults(func=cmd_compare)

    sp = sub.add_parser("report", help="Build a one-page PDF from a trend/compare JSON result.")
    sp.add_argument("--input", required=True, help="Path to saved JSON from trend/compare, or '-' for stdin.")
    sp.add_argument("--title", default=None)
    sp.add_argument("--findings", default=None, help="Your data-grounded interpretation -- write this yourself, citing only numbers present in --input.")
    sp.add_argument("--recommendations", default=None)
    sp.add_argument("--limitations", default=None, help="Extra limitations, ';'-separated, appended to the built-in defaults.")
    sp.add_argument("--out", default=None)
    sp.add_argument("--lang", default="en", choices=["en", "uk"],
                    help="Language of the report's fixed text (headings, table, limitations). Default: %(default)s")
    sp.set_defaults(func=cmd_report)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except WikitrendsError as exc:
        _emit({"error": str(exc), "type": type(exc).__name__}, error=True)
    except Exception as exc:  # noqa: BLE001 -- always surface as JSON, never a raw traceback
        _emit({"error": str(exc), "type": type(exc).__name__}, error=True)


if __name__ == "__main__":
    main()
