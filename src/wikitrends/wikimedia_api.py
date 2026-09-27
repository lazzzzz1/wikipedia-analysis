"""Thin client for the Wikimedia Pageviews REST API and the MediaWiki /
Wikidata action APIs."""
from __future__ import annotations

import datetime as dt
import os
import time
import urllib.parse
from dataclasses import dataclass

import requests

from . import constants as c
from . import dates as d
from .cache import Cache
from .errors import ArticleNotFoundError

_session: requests.Session | None = None


def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        contact = os.environ.get(c.USER_AGENT_ENV_VAR, c.DEFAULT_CONTACT)
        # Wikimedia's API etiquette requires a descriptive User-Agent with
        # contact info; generic/default agents get more aggressively
        # rate-limited or blocked. See references/API.md.
        _session.headers.update({"User-Agent": f"wikitrends-agent-skill/0.2 ({contact})"})
    return _session


def _get_json(url: str, params: dict | None = None) -> dict:
    session = get_session()
    last_error: Exception | None = None
    for attempt in range(c.MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=c.REQUEST_TIMEOUT_SECONDS)
            if resp.status_code == 404:
                return {"__not_found__": True}
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < c.MAX_RETRIES:
                time.sleep(_retry_delay(exc, attempt))
    hint = ""
    if isinstance(last_error, requests.HTTPError) and last_error.response is not None \
            and last_error.response.status_code == 429:
        hint = (" Wikimedia is rate-limiting this client: wait a minute and re-run the same "
                f"command (already-fetched data is cached), and set {c.USER_AGENT_ENV_VAR} "
                "to a contact email -- anonymous clients are limited more aggressively.")
    raise RuntimeError(f"Request to {url} failed after {c.MAX_RETRIES} attempts: {last_error}.{hint}")


def _retry_delay(exc: Exception, attempt: int) -> float:
    delay = c.RETRY_BACKOFF_SECONDS * (2 ** attempt)
    resp = getattr(exc, "response", None)
    if resp is not None and resp.status_code == 429:
        try:
            delay = max(delay, float(resp.headers.get("Retry-After", 0)))
        except ValueError:
            pass
    return min(delay, c.MAX_RETRY_DELAY_SECONDS)


def article_path_segment(title: str) -> str:
    return urllib.parse.quote(title.replace(" ", "_"), safe="")


def lang_to_project(lang: str) -> str:
    lang = lang.strip().lower()
    return lang if lang.endswith(".wikipedia") else f"{lang}.wikipedia"


def project_to_lang(project: str) -> str:
    return project.split(".")[0]


@dataclass
class SeriesResult:
    dates: list[str]
    views: list[int]
    warnings: list[str]


def _clamp_start(start: dt.date, warnings: list[str]) -> dt.date:
    earliest = d.parse_iso(c.EARLIEST_AVAILABLE_DATE)
    if start < earliest:
        warnings.append(
            "Requested start date is before Wikimedia Pageviews data begins "
            f"({c.EARLIEST_AVAILABLE_DATE}); clamped to that date."
        )
        return earliest
    return start


# Data lags a day or two, and a month appears only once it's over. Asking for
# an unfinished period returns 400 rather than empty data, so clamp up front.
_DATA_LAG_DAYS = 2


def _clamp_end(end: dt.date, granularity: str, warnings: list[str]) -> dt.date:
    today = dt.date.today()
    clamped = min(end, today - dt.timedelta(days=_DATA_LAG_DAYS))
    if granularity == "monthly":
        current_month_start = today.replace(day=1)
        if clamped >= current_month_start:
            clamped = current_month_start - dt.timedelta(days=1)
    if clamped != end:
        warnings.append(
            f"Requested end date adjusted to {clamped.isoformat()}: Wikimedia has not "
            "yet published pageview data for the requested end of the range "
            f"({'the current, still-in-progress month' if granularity == 'monthly' else 'the last day or two'})."
        )
    return clamped


def fetch_series(
    project: str,
    article: str | None,
    start: dt.date,
    end: dt.date,
    granularity: str = c.DEFAULT_GRANULARITY,
    access: str = c.DEFAULT_ACCESS,
    agent: str = c.DEFAULT_AGENT,
    cache: Cache | None = None,
    verify_exists: bool = True,
) -> SeriesResult:
    """Fetch a pageviews series for an article, or for the whole project if
    article is None (used to normalize an article's traffic against its
    edition's total traffic)."""
    if end < start:
        raise ValueError("end date must not be before start date")

    warnings: list[str] = []
    start = _clamp_start(start, warnings)
    end = _clamp_end(end, granularity, warnings)
    if end < start:
        # The whole requested window falls after the latest data Wikimedia has
        # published (e.g. "this month" requested on the 1st-2nd of the month).
        warnings.append(
            f"No published data available yet for {start.isoformat()} to {end.isoformat()}."
        )
        return SeriesResult(dates=[], views=[], warnings=warnings)

    cache_key_article = article or "__aggregate__"

    if article and verify_exists:
        canonical = _canonical_title(project, article, cache)
        if canonical is None:
            raise ArticleNotFoundError(
                f"'{article}' was not found on {project}.org (redirects were checked too)."
            )
        if canonical != article:
            warnings.append(f"'{article}' redirects to '{canonical}'; using the redirect target.")
        article = canonical
        cache_key_article = article

    expected = d.expected_dates(start, end, granularity)
    cached: dict[str, int] = {}
    if cache is not None:
        cached = cache.get_series(
            project, cache_key_article, access, agent, granularity,
            expected[0].isoformat(), expected[-1].isoformat(),
        )

    gaps = d.missing_ranges(expected, set(cached.keys()), granularity)
    for gap_start, gap_end in gaps:
        rows, saw_data = _fetch_range(project, article, gap_start, gap_end, granularity, access, agent)
        if not saw_data:
            # No data at all for this range: could be genuinely zero traffic,
            # or a very new article. Fill with zeros so stats don't choke on
            # missing points, but make the assumption visible to the caller.
            for day in d.expected_dates(gap_start, gap_end, granularity):
                rows.setdefault(day.isoformat(), 0)
            warnings.append(
                f"No recorded traffic for {project}"
                + (f"/{article}" if article else "")
                + f" between {gap_start} and {gap_end}; treated as zero."
            )
        if cache is not None and rows:
            cache.store_series(project, cache_key_article, access, agent, granularity, rows)
        cached.update(rows)

    ordered_dates = [dd.isoformat() for dd in expected]
    views = [cached.get(dd, 0) for dd in ordered_dates]
    return SeriesResult(dates=ordered_dates, views=views, warnings=warnings)


def _fetch_range(
    project: str, article: str | None, start: dt.date, end: dt.date,
    granularity: str, access: str, agent: str,
) -> tuple[dict[str, int], bool]:
    start_s = d.to_api_date(start, granularity)
    end_s = d.to_api_date(end, granularity, is_end=True)
    if article:
        path = (
            f"{c.PAGEVIEWS_API_BASE}/per-article/{project}/{access}/{agent}/"
            f"{article_path_segment(article)}/{granularity}/{start_s}/{end_s}"
        )
    else:
        path = (
            f"{c.PAGEVIEWS_API_BASE}/aggregate/{project}/{access}/{agent}/"
            f"{granularity}/{start_s}/{end_s}"
        )
    payload = _get_json(path)
    if payload.get("__not_found__"):
        return {}, False
    rows: dict[str, int] = {}
    for item in payload.get("items", []):
        ts = item["timestamp"]  # YYYYMMDDHH
        day = 1 if granularity == "monthly" else int(ts[6:8])
        date_obj = dt.date(int(ts[0:4]), int(ts[4:6]), day)
        rows[date_obj.isoformat()] = item["views"]
    return rows, True


def _canonical_title(project: str, title: str, cache: Cache | None) -> str | None:
    """resolve_article_title with a cache, so repeat runs don't pay one API
    round-trip per article. Only found titles are cached: a missing article
    is re-checked next time in case someone has written it since."""
    key = f"title:{project}:{title}"
    if cache is not None:
        hit = cache.get_resolved(key)
        if hit is not None:
            return hit["canonical"]
    canonical = resolve_article_title(project, title)
    if cache is not None and canonical is not None:
        cache.store_resolved(key, {"canonical": canonical})
    return canonical


def resolve_article_title(project: str, title: str) -> str | None:
    """Return the canonical (redirect-resolved) title, or None if the page
    does not exist on this edition."""
    lang = project_to_lang(project)
    url = c.WIKIPEDIA_API_TEMPLATE.format(lang=lang)
    payload = _get_json(
        url, params={"action": "query", "format": "json", "redirects": 1, "titles": title},
    )
    pages = payload.get("query", {}).get("pages", {})
    for page_id, page in pages.items():
        if page_id == "-1" or "missing" in page:
            return None
        return page["title"]
    return None


def search_titles(project: str, query: str, limit: int = 5) -> list[str]:
    """Full-text search on one edition. Used to find a nearest article when
    Wikidata has no sitelink for that edition."""
    url = c.WIKIPEDIA_API_TEMPLATE.format(lang=project_to_lang(project))
    payload = _get_json(
        url, params={"action": "query", "format": "json", "list": "search", "srsearch": query,
                     "srlimit": limit, "srnamespace": 0},
    )
    return [hit["title"] for hit in payload.get("query", {}).get("search", [])]


def search_wikidata(label: str, language: str, limit: int = 5) -> list[dict]:
    payload = _get_json(
        c.WIKIDATA_API,
        params={
            "action": "wbsearchentities", "format": "json", "language": language,
            "uselang": language, "type": "item", "search": label, "limit": limit,
        },
    )
    return payload.get("search", [])


def get_sitelinks(qid: str, site_ids: list[str], label_languages: list[str] | None = None) -> dict:
    params = {
        "action": "wbgetentities", "format": "json", "ids": qid,
        "props": "sitelinks|labels|descriptions", "sitefilter": "|".join(site_ids),
    }
    if label_languages:
        params["languages"] = "|".join(label_languages)
    payload = _get_json(c.WIKIDATA_API, params=params)
    return payload.get("entities", {}).get(qid, {})
