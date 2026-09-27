# API reference (for debugging, not required reading for normal use)

`SKILL.md` covers everything the CLI needs day to day. This file documents
the underlying APIs the code wraps, for when a result looks wrong and you
need to check what the raw API actually returned.

## Wikimedia Pageviews REST API

Base: `https://wikimedia.org/api/rest_v1/metrics/pageviews`

### Per-article

```
/per-article/{project}/{access}/{agent}/{article}/{granularity}/{start}/{end}
```

- `project`: `{lang}.wikipedia`, e.g. `pl.wikipedia`, `uk.wikipedia` (not `.org`).
- `access`: `all-access` | `desktop` | `mobile-app` | `mobile-web`. We default to `all-access`.
- `agent`: `all-agents` | `user` | `spider` | `automated`. We default to `user` so
  crawler/bot traffic doesn't get read as human interest.
- `article`: exact page title, spaces as `_`, fully percent-encoded (`wikitrends.wikimedia_api.article_path_segment`
  handles this, including titles that themselves contain `/`).
- `granularity`: `daily` | `monthly`.
- `start`/`end`: `YYYYMMDD` (daily) or `YYYYMM01` (monthly), inclusive.

Returns 404 (not an error payload) when there is no data for the range -- this can mean
the article didn't exist yet, or genuinely had zero recorded views. The client treats a
404 as "zero views for this range" and adds a warning rather than failing, since for
low-traffic language editions a real zero is common and shouldn't crash the analysis.

### Aggregate (whole-project total)

```
/aggregate/{project}/{access}/{agent}/{granularity}/{start}/{end}
```

Same parameters, no article. Used to normalize an article's views into "share of all
traffic on that edition" (`wikitrends.cli._trend_for_article`), which is what makes
cross-language comparisons fair -- pl.wikipedia and cs.wikipedia have very different
total traffic and growth, so raw view counts alone are not comparable.

### Data coverage

The Pageviews API starts **2015-07-01**. Anything requested before that is silently
clamped by `wikimedia_api._clamp_start`, with a warning added to the output.

## MediaWiki action API (per-language Wikipedia)

`https://{lang}.wikipedia.org/w/api.php`

Used only for `action=query&redirects=1&titles=...` to resolve a title to its
canonical form (following redirects) and confirm the page exists before hitting the
pageviews endpoint with it. `page["missing"]` present (or pageid `-1`) means the title
doesn't exist on that edition.

## Wikidata action API

`https://www.wikidata.org/w/api.php`

- `action=wbsearchentities`: search Wikidata items by label in a given language. Used
  as the entry point for `resolve_topic` -- searching Wikidata directly (rather than
  full-text search on one Wikipedia edition) matches on canonical labels/aliases and is
  more robust for finding "the concept", independent of how any one edition titles its
  article.
- `action=wbgetentities&props=sitelinks|labels|descriptions&sitefilter=plwiki|cswiki|...`:
  given a QID, read off each requested edition's article title directly from the item's
  sitelinks. This is the cross-language join: it avoids ever having to guess a
  translated title.

## Rate limiting / etiquette

Wikimedia asks for a descriptive `User-Agent` with contact info; a generic default gets
more aggressively throttled. Set the `WIKITRENDS_CONTACT` environment variable (email or
project URL) before running the CLI in any real deployment; see `wikimedia_api.get_session`.
