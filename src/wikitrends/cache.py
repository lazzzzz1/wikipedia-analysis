"""SQLite-backed cache for pageview series and topic-resolution lookups.

Wikimedia pageview data for a finished day/month never changes retroactively,
so once a date is cached it can be reused forever. This is what makes
follow-up questions ("now extend that to 3 years", "add Ukrainian too")
cheap: only the genuinely new date range or language is fetched over the
network; everything already seen comes back from a local, instant read.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from pathlib import Path


def default_cache_path() -> Path:
    override = os.environ.get("WIKITRENDS_CACHE_DIR")
    base = Path(override) if override else Path.home() / ".cache" / "wikitrends"
    base.mkdir(parents=True, exist_ok=True)
    return base / "wikitrends.sqlite3"


class Cache:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_cache_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pageviews (
                project TEXT NOT NULL,
                article TEXT NOT NULL,
                access TEXT NOT NULL,
                agent TEXT NOT NULL,
                granularity TEXT NOT NULL,
                date TEXT NOT NULL,
                views INTEGER NOT NULL,
                PRIMARY KEY (project, article, access, agent, granularity, date)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS resolve_cache (
                cache_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ---- pageviews ----

    def get_series(
        self, project: str, article: str, access: str, agent: str,
        granularity: str, start: str, end: str,
    ) -> dict[str, int]:
        cur = self._conn.execute(
            """
            SELECT date, views FROM pageviews
            WHERE project=? AND article=? AND access=? AND agent=? AND granularity=?
              AND date >= ? AND date <= ?
            """,
            (project, article, access, agent, granularity, start, end),
        )
        return {row[0]: row[1] for row in cur.fetchall()}

    def store_series(
        self, project: str, article: str, access: str, agent: str,
        granularity: str, rows: dict[str, int],
    ) -> None:
        if not rows:
            return
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO pageviews
                (project, article, access, agent, granularity, date, views)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (project, article, access, agent, granularity, date, views)
                for date, views in rows.items()
            ],
        )
        self._conn.commit()

    # ---- topic resolution ----

    def get_resolved(self, cache_key: str) -> dict | None:
        cur = self._conn.execute(
            "SELECT payload FROM resolve_cache WHERE cache_key=?", (cache_key,)
        )
        row = cur.fetchone()
        return json.loads(row[0]) if row else None

    def store_resolved(self, cache_key: str, payload: dict) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO resolve_cache (cache_key, payload, fetched_at) VALUES (?, ?, ?)",
            (cache_key, json.dumps(payload, ensure_ascii=False), dt.datetime.now(dt.timezone.utc).isoformat()),
        )
        self._conn.commit()
