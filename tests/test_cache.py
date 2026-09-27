from wikitrends.cache import Cache


def test_store_and_get_series_roundtrip(tmp_path):
    cache = Cache(tmp_path / "test.sqlite3")
    rows = {"2024-01-01": 10, "2024-01-02": 20, "2024-01-03": 30}
    cache.store_series("pl.wikipedia", "Foo", "all-access", "user", "daily", rows)

    got = cache.get_series("pl.wikipedia", "Foo", "all-access", "user", "daily", "2024-01-01", "2024-01-03")
    assert got == rows


def test_get_series_respects_date_bounds(tmp_path):
    cache = Cache(tmp_path / "test.sqlite3")
    rows = {"2024-01-01": 10, "2024-01-02": 20, "2024-01-03": 30}
    cache.store_series("pl.wikipedia", "Foo", "all-access", "user", "daily", rows)

    got = cache.get_series("pl.wikipedia", "Foo", "all-access", "user", "daily", "2024-01-02", "2024-01-02")
    assert got == {"2024-01-02": 20}


def test_series_isolated_by_key(tmp_path):
    cache = Cache(tmp_path / "test.sqlite3")
    cache.store_series("pl.wikipedia", "Foo", "all-access", "user", "daily", {"2024-01-01": 10})
    cache.store_series("cs.wikipedia", "Foo", "all-access", "user", "daily", {"2024-01-01": 999})

    got = cache.get_series("pl.wikipedia", "Foo", "all-access", "user", "daily", "2024-01-01", "2024-01-01")
    assert got == {"2024-01-01": 10}


def test_resolve_cache_roundtrip(tmp_path):
    cache = Cache(tmp_path / "test.sqlite3")
    assert cache.get_resolved("missing-key") is None

    payload = {"topic": "intermittent fasting", "qid": "Q1361058"}
    cache.store_resolved("key-1", payload)
    assert cache.get_resolved("key-1") == payload


def test_canonical_title_is_cached(tmp_path, monkeypatch):
    from wikitrends import wikimedia_api as api

    calls = []

    def fake_resolve(project, title):
        calls.append(title)
        return {"Foo": "Foo (canonical)"}.get(title)

    monkeypatch.setattr(api, "resolve_article_title", fake_resolve)
    cache = Cache(tmp_path / "test.sqlite3")

    assert api._canonical_title("pl.wikipedia", "Foo", cache) == "Foo (canonical)"
    assert api._canonical_title("pl.wikipedia", "Foo", cache) == "Foo (canonical)"
    assert calls == ["Foo"]

    # Missing articles are not cached, so a newly written article is picked up.
    assert api._canonical_title("pl.wikipedia", "Missing", cache) is None
    assert api._canonical_title("pl.wikipedia", "Missing", cache) is None
    assert calls == ["Foo", "Missing", "Missing"]
