"""Resolve a free-text topic to the matching article on each requested
Wikipedia edition.

Uses Wikidata as the cross-language join key: search for the concept once
by label, then read the title straight off the item's sitelinks for each
target edition. This is far more reliable than guessing translated titles
by hand, and it naturally handles the fact that article names rarely
translate literally between editions (e.g. "Intermittent fasting" vs
"Přerušovaný půst").
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import wikimedia_api as api
from .cache import Cache
from .errors import TopicNotFoundError


@dataclass
class ResolvedLanguage:
    lang: str
    project: str
    title: str | None
    url: str | None
    found: bool


@dataclass
class ResolveResult:
    topic: str
    source_lang: str
    qid: str | None
    label: str | None
    description: str | None
    wikidata_url: str | None
    ambiguous: bool
    candidates: list[dict]
    languages: dict[str, ResolvedLanguage]
    warnings: list[str] = field(default_factory=list)


def resolve_topic(
    topic: str,
    target_langs: list[str],
    source_lang: str = "en",
    cache: Cache | None = None,
    use_cache: bool = True,
) -> ResolveResult:
    all_langs = sorted(set(target_langs) | {source_lang})
    cache_key = f"resolve:{source_lang}:{topic.strip().lower()}:{','.join(all_langs)}"

    if cache is not None and use_cache:
        cached_payload = cache.get_resolved(cache_key)
        if cached_payload is not None:
            return _from_dict(cached_payload)

    candidates = api.search_wikidata(topic, source_lang)
    if not candidates:
        raise TopicNotFoundError(
            f"No Wikidata concept found for '{topic}' searched in language '{source_lang}'. "
            "Try a different phrasing, or call `trend`/`compare` with an explicit --article title."
        )

    top = candidates[0]
    qid = top["id"]
    ambiguous = _is_ambiguous(candidates)

    site_ids = [f"{lang}wiki" for lang in all_langs]
    entity = api.get_sitelinks(qid, site_ids, label_languages=list({source_lang, "en"}))

    sitelinks = entity.get("sitelinks", {})
    labels = entity.get("labels", {})
    descriptions = entity.get("descriptions", {})

    label = (labels.get(source_lang) or labels.get("en") or {}).get("value")
    description = (descriptions.get(source_lang) or descriptions.get("en") or {}).get("value")

    languages: dict[str, ResolvedLanguage] = {}
    warnings: list[str] = []
    for lang in target_langs:
        project = api.lang_to_project(lang)
        site_id = f"{lang}wiki"
        link = sitelinks.get(site_id)
        if link:
            title = link["title"]
            languages[lang] = ResolvedLanguage(
                lang=lang, project=project, title=title,
                url=f"https://{lang}.wikipedia.org/wiki/{api.article_path_segment(title)}",
                found=True,
            )
        else:
            languages[lang] = ResolvedLanguage(lang=lang, project=project, title=None, url=None, found=False)
            warnings.append(f"No {lang}.wikipedia article is linked to this concept yet.")

    result = ResolveResult(
        topic=topic, source_lang=source_lang, qid=qid, label=label, description=description,
        wikidata_url=f"https://www.wikidata.org/wiki/{qid}", ambiguous=ambiguous,
        candidates=[
            {"qid": cnd["id"], "label": cnd.get("label"), "description": cnd.get("description")}
            for cnd in candidates[:3]
        ],
        languages=languages, warnings=warnings,
    )
    if cache is not None:
        cache.store_resolved(cache_key, _to_dict(result))
    return result


def _is_ambiguous(candidates: list[dict]) -> bool:
    if len(candidates) < 2:
        return False
    # Only a shared label is a real collision ("Mercury" planet vs god).
    # Search also returns papers, trials etc. that merely mention the query.
    top_label = (candidates[0].get("label") or "").strip().lower()
    runner_up_label = (candidates[1].get("label") or "").strip().lower()
    return bool(top_label) and top_label == runner_up_label


def _to_dict(r: ResolveResult) -> dict:
    return {
        "topic": r.topic, "source_lang": r.source_lang, "qid": r.qid, "label": r.label,
        "description": r.description, "wikidata_url": r.wikidata_url, "ambiguous": r.ambiguous,
        "candidates": r.candidates, "warnings": r.warnings,
        "languages": {
            lang: {"lang": rl.lang, "project": rl.project, "title": rl.title, "url": rl.url, "found": rl.found}
            for lang, rl in r.languages.items()
        },
    }


def _from_dict(payload: dict) -> ResolveResult:
    return ResolveResult(
        topic=payload["topic"], source_lang=payload["source_lang"], qid=payload["qid"],
        label=payload["label"], description=payload["description"], wikidata_url=payload["wikidata_url"],
        ambiguous=payload["ambiguous"], candidates=payload["candidates"], warnings=payload.get("warnings", []),
        languages={lang: ResolvedLanguage(**rl) for lang, rl in payload["languages"].items()},
    )
