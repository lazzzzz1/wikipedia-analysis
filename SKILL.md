---
name: wikipedia-trends
description: Analyzes Wikipedia pageview trends (via the Wikimedia Pageviews API) to help B2C product teams decide what content/topics to build next and which languages to localize into. Compares interest in a topic across language editions, fits a spike-resistant trend with an explicit confidence tier, normalizes for each edition's traffic size, generates charts, and assembles a one-page shareable PDF report. Use when the user asks things like "is interest in X growing", "compare interest in X across languages/editions", "which language should we localize into next", or wants a report on Wikipedia pageview trends for a topic.
license: MIT
compatibility: Requires Python 3.11+ and uv (https://docs.astral.sh/uv/), plus network access to wikimedia.org, wikipedia.org and wikidata.org. No GPU or system packages needed.
metadata:
  version: "0.2.0"
---

# Wikipedia pageview trends

## What this does

Given a topic (e.g. "intermittent fasting") and a set of language editions, this skill:

1. Resolves the topic to the matching article on each edition via Wikidata (handles the
   fact that titles rarely translate literally).
2. Fetches pageview history from the Wikimedia Pageviews API, with a local cache so
   follow-up questions don't re-fetch data you already have.
3. Fits a trend that is robust to single-day spikes, and assigns it a **confidence
   tier** (`high` / `medium` / `low`) based on traffic volume and statistical
   significance -- never just "up" or "down".
4. Normalizes each article's views against its edition's total traffic, so you can
   compare a small edition (e.g. cs.wikipedia) to a large one (e.g. pl.wikipedia)
   fairly, and to catch cases where a topic's apparent growth or decline is really the
   whole edition's traffic moving (currently many editions are shrinking overall).
5. Builds charts and a one-page PDF report.

All commands are run through the `wikitrends` CLI (installed into this skill's own
`.venv` via `uv`) and print **one JSON object to stdout** -- never free text, never a
raw traceback. Run every command with `uv run`, from this skill's directory:

```bash
uv run -q wikitrends <command> [options]
```

For `compare` and `trend`, always pass `--out outputs/<name>.json`: the full result
(with every data point) is saved there for `report`, and stdout gets a compact summary
with rounded numbers -- that summary is all you need to read. The `outputs/` folder is
created for you. Don't redirect with `2>&1`.

(First time only: `uv sync` installs dependencies into `.venv/`. `uv run` picks it up
automatically -- you never need to activate anything.)

If you can't `cd` into the skill directory, use the wrapper instead -- it works from
any working directory and takes exactly the same arguments:
`bash <skill-dir>/scripts/wikitrends.sh <command> [options]` (call it via `bash`:
unzip tools often drop the executable bit). Output files (`outputs/...`) are written
relative to your current directory either way.

## The three commands you'll normally use

### 1. `compare` -- the main entry point for "compare interest in X across languages"

```bash
uv run -q wikitrends compare --topic "intermittent fasting" --langs pl,cs --last 2y \
  --out outputs/compare.json
```

- `--last 2y` / `--last 24m` / `--last 90d` is a shorthand for the date range ending
  today; use it instead of computing exact dates by hand. Or pass `--start YYYY-MM-DD
  --end YYYY-MM-DD` explicitly if the user gave a specific window.
- `--access desktop|mobile-web|mobile-app` (default `all-access`) if the user asks
  about a specific platform ("mobile users only").
- `--source-lang` (default `en`) is the language you search the *topic name* in, not
  a language being compared -- it only affects how the topic is resolved to a Wikidata
  concept. Use whatever language the topic phrase you're passing is written in.
- If a language edition has no article on this topic yet, it's dropped from the
  comparison and a warning explains why. Report it as a fact about Wikipedia's
  coverage ("no Polish article is linked to this concept"), not as evidence of demand or
  of a market gap, and don't recommend writing Wikipedia content.
  If the user still needs that language, look for the nearest existing article:
  `uv run -q wikitrends search --project pl --query "głodówka"` (query in that
  edition's language), pick a title that is clearly about the topic, and re-run
  `compare --articles ...` with it. Say in the answer and via `--limitations` that
  this article is a proxy, not the same concept. If no hit is clearly on-topic,
  don't force one -- report the language as "no article".
- If you already know the exact article titles (or the topic search picks the wrong
  concept), skip resolution entirely:
  `--articles "cs.wikipedia:Přerušovaný půst,uk.wikipedia:Інтервальне голодування"`.

### 2. `trend` -- deep-dive on a single article/edition

```bash
uv run -q wikitrends trend --project uk.wikipedia --article "Астрономія" --last 3y \
  --out outputs/trend.json
```

Use this for single-topic, single-language questions ("is interest in astronomy
growing in Ukrainian Wikipedia"). Same output shape as one entry of `compare`.

### 3. `report` -- turn a `compare`/`trend` result into a one-page PDF

```bash
uv run -q wikitrends report --input outputs/compare.json \
  --title "Intermittent fasting: PL vs CS" \
  --findings "Your 2-4 sentence, data-grounded interpretation." \
  --recommendations "Your 1-3 sentence recommendation." \
  --lang uk --out outputs/report.pdf
```

`--input` is the file you passed as `--out` to `compare`/`trend` (the `saved_to` field
in their output) -- not `chart_path`, which is just one field *inside* that JSON.
`report` reads the chart out of the file itself.

`--lang uk` renders the report's fixed text (headings, table, built-in limitations) in
Ukrainian; use it when you talk to the user in Ukrainian, and write `--title`,
`--findings` and `--recommendations` in that language too. Default is `en`.

`--findings` and `--recommendations` are **not generated for you** -- writing them is
your job as the agent, because that synthesis is the actual value-add. Every
`compare`/`trend` output ends with **`before_you_write`**: the rules below that apply to
this particular result. Read it and follow each line. The full rules:

- Only state numbers that appear in the `--input` JSON. Never invent a percentage,
  view count, or date that isn't there.
- Always state the confidence tier explicitly (e.g. "with low confidence, because
  median traffic is only ~15 views/day"). Do not present a `low`-confidence trend with
  the same certainty as a `high`-confidence one.
- If `cross_check_notes` is non-empty, mention it -- it means the raw trend and the
  edition-normalized trend disagree, which is exactly the kind of thing a founder
  should not miss.
- Never state a *cause* the data doesn't contain ("users already learned English",
  "they moved to other platforms", "the market is saturated"). Pageviews show *that*
  interest moved, not *why*. If a cause seems plausible, label it as a hypothesis to
  check ("one hypothesis worth testing: ...").
- `high` confidence means the pageview trend is reliable -- not that demand or
  willingness to pay is. Don't write "can be fully trusted" or "shows the audience
  isn't ready"; say what was measured.
- `anomalies` entries have `kind: "spike"` or `"dip"`. If spikes recur in the same
  month each year (e.g. every September), say so -- a seasonal pattern (school year, holidays) is often the most actionable
  finding. Call it seasonal only if the same month spikes in at least two different
  years; a one-off spike is just a spike.
- `--recommendations` are for the user's *product* (which topic/language to
  research, test or launch next), not for Wikipedia ("create a Polish article").
  Don't generalise beyond the editions and topic actually analysed ("interest across
  Central Europe").
- If the user asked about an activity ("learning English", "studying astronomy") but
  the analysed article is the general topic ("English language"), say it's a proxy, in
  the answer and via `--limitations`.
- Pass anything topic-specific worth flagging via `--limitations "extra note;another
  note"` (semicolon-separated); it's appended to the built-in limitations that are
  always included (pageviews != purchase intent, bot traffic excluded, data from
  2015-07 on, etc.).
- `--findings`/`--recommendations` are plain text; `**bold**` is the only markup
  rendered.

A helper command, `resolve`, exists standalone too (`uv run -q wikitrends resolve --topic
"..." --langs pl,cs`) if you want to sanity-check which article/concept was matched
*before* running a full comparison -- useful when the topic name is ambiguous.

## Reading the output JSON

Every `trend` entry (standalone or inside `compare`) has this shape:

```jsonc
{
  // illustrative values, not real data
  "label": "cs.wikipedia: Přerušovaný půst",
  "trend": {
    "pct_change_per_year": 18.4,
    "pct_change_ci": [4.1, 34.2],
    "median_daily_views": 42.3,
    "confidence": "medium",
    "confidence_reasons": ["Directionally consistent but noisy; treat the exact magnitude as approximate."],
    "direction": "growing",
    "anomalies": [{"date": "2024-03-01", "views": 8000, "expected": 900.0, "kind": "spike"}]
  },
  "share_trend": { /* same shape, computed on this article's share of total edition traffic */ },
  "cross_check_notes": [],
  "recurring_spike_months": [],
  "data_range": "2024-09-01 to 2026-08-31"
}
```

- **`median_daily_views`** is the traffic volume in views *per day*. With the default
  monthly granularity, `views`, `avg_views` and `median_views` are *per month* totals --
  don't quote them as daily numbers.
- **`confidence`** is the single most important field to relay to the user. `low`
  means: small sample, or the confidence interval crosses zero, or too few data
  points -- say so plainly rather than stating the direction as fact.
- **`anomalies`** are months/days at least 25% away from their neighbours
  (`kind: "spike"` or `"dip"`) that the trend line already discounted -- mention large
  spikes, since they often correspond to a news event, not sustained interest.
- **`date_range`** is the period the data actually covers. It can be shorter than
  requested (`requested_range`): the current month isn't published until it ends.
  Quote `date_range`, not the period you asked for.
- **`warnings`** and **`cross_check_notes`** carry data-quality caveats generated by
  the tool itself (redirects followed, dates clamped to API coverage, zero-traffic
  gaps, raw-vs-share disagreement). Surface anything here that's relevant to the
  user's question -- don't silently drop it.

`warnings` are collected at the top level of the output.

- **`share_ranking`** (`compare` only): editions ordered by growth of their share of the
  edition's total traffic, each with its % per year, confidence and daily views. When
  comparing editions -- e.g. "which audience to explore next" -- **follow this order**:
  raw views move with each edition's overall traffic, which is currently falling across
  many editions at once. (`ranking_by_growth` is the raw-views order, for reference.)
- **`recurring_spike_months`**: calendar months that spiked in 2+ different years --
  a seasonal pattern. Only these count as "seasonal".

## Efficient follow-ups

Fetched pageview data is cached locally (SQLite under `~/.cache/wikitrends/`, override
with `WIKITRENDS_CACHE_DIR`) keyed by project/article/date. If the user extends a date
range, adds a language, or asks the same thing again, just re-run the command with the
new parameters -- only the genuinely new data is fetched over the network; everything
else comes back instantly from the cache. You don't need to do anything special to get
this benefit, and you don't need to avoid re-running commands to "save time" -- re-run
freely.

Topic-to-article resolution is cached too, so re-running `compare --topic "..."` with
the same topic/langs doesn't re-hit Wikidata.

## Edge cases

- **Topic not found on Wikidata**: `resolve`/`compare --topic` raise an error with a
  suggestion to rephrase or fall back to `--articles` with an explicit title.
- **Ambiguous topic** (`"ambiguous": true` in a resolve result, with multiple
  `candidates` shown): the top Wikidata match was used, but a plausible runner-up
  exists. If this matters for the user's question, show them the candidates and ask
  which one they meant, rather than silently proceeding.
- **Article doesn't exist on a requested edition**: that language is skipped in
  `compare` (see `warnings`), not treated as zero interest -- no article often just
  means no one has written one yet, which is a different fact from "no one reads
  about this".
- **Very low traffic**: `confidence` will be `low`; say so, don't round it up to a
  confident-sounding claim.

## Evolving this skill further

See `README.md` at the root of this skill directory for how this was validated on a
small model and a roadmap for scaling to category-level topics, bulk data volumes, and
richer statistical methods.
