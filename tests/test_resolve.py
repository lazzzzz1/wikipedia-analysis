from unittest.mock import patch

import pytest

from wikitrends.errors import TopicNotFoundError
from wikitrends.resolve import resolve_topic

FAKE_CANDIDATES = [
    {"id": "Q1361058", "label": "intermittent fasting", "description": "eating pattern"},
]

FAKE_ENTITY = {
    "sitelinks": {
        "plwiki": {"title": "Głodówka przerywana"},
        "enwiki": {"title": "Intermittent fasting"},
        # deliberately no cswiki sitelink -> should come back found=False
    },
    "labels": {"en": {"value": "intermittent fasting"}},
    "descriptions": {"en": {"value": "pattern of eating that cycles between periods of fasting and eating"}},
}


def test_resolve_topic_maps_languages_via_wikidata():
    with patch("wikitrends.resolve.api.search_wikidata", return_value=FAKE_CANDIDATES), \
         patch("wikitrends.resolve.api.get_sitelinks", return_value=FAKE_ENTITY):
        result = resolve_topic("intermittent fasting", target_langs=["pl", "cs"], source_lang="en")

    assert result.qid == "Q1361058"
    assert result.languages["pl"].found is True
    assert result.languages["pl"].title == "Głodówka przerywana"
    assert result.languages["cs"].found is False
    assert any("cs.wikipedia" in w for w in result.warnings)


def test_resolve_topic_raises_when_no_wikidata_match():
    with patch("wikitrends.resolve.api.search_wikidata", return_value=[]):
        with pytest.raises(TopicNotFoundError):
            resolve_topic("asdkjhqwlekjhasd", target_langs=["pl"], source_lang="en")


def test_resolve_topic_flags_ambiguous_when_runner_up_has_description():
    candidates = [
        {"id": "Q1", "label": "Mercury", "description": "planet"},
        {"id": "Q2", "label": "Mercury", "description": "Roman god"},
    ]
    with patch("wikitrends.resolve.api.search_wikidata", return_value=candidates), \
         patch("wikitrends.resolve.api.get_sitelinks", return_value=FAKE_ENTITY):
        result = resolve_topic("Mercury", target_langs=["pl"], source_lang="en")

    assert result.ambiguous is True
    assert len(result.candidates) == 2


def test_resolve_topic_uses_cache_on_second_call():
    calls = {"n": 0}

    def fake_search(*args, **kwargs):
        calls["n"] += 1
        return FAKE_CANDIDATES

    class FakeCache:
        def __init__(self):
            self.store = {}

        def get_resolved(self, key):
            return self.store.get(key)

        def store_resolved(self, key, payload):
            self.store[key] = payload

    cache = FakeCache()
    with patch("wikitrends.resolve.api.search_wikidata", side_effect=fake_search), \
         patch("wikitrends.resolve.api.get_sitelinks", return_value=FAKE_ENTITY):
        resolve_topic("intermittent fasting", target_langs=["pl"], source_lang="en", cache=cache)
        resolve_topic("intermittent fasting", target_langs=["pl"], source_lang="en", cache=cache)

    assert calls["n"] == 1  # second call served from cache, no network hit


def test_search_titles_reads_mediawiki_search_hits():
    from wikitrends import wikimedia_api as api

    payload = {"query": {"search": [{"title": "Głodówka lecznicza"}, {"title": "Post"}]}}
    with patch("wikitrends.wikimedia_api._get_json", return_value=payload) as get:
        assert api.search_titles("pl.wikipedia", "głodówka") == ["Głodówka lecznicza", "Post"]
    assert get.call_args.args[0].startswith("https://pl.wikipedia.org/")
