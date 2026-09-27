# wikipedia-analysis

An Agent Skill and CLI tool for analyzing Wikipedia article pageviews via the
[Wikimedia Pageviews API](https://wikimedia.org/api/rest_v1/). It shows whether
interest in a topic is growing and compares it across language editions — for
example, to decide what content to build next or which language to localize into.

## Features

- Finds the matching article for a topic across several language editions (via Wikidata)
- Spike-resistant trend fitting with an explicit confidence tier
- Normalization by each edition's total traffic, for fair comparison of large and small languages
- Charts and a one-page PDF report (English or Ukrainian)
- Request caching and retries on API errors

## Requirements

- [uv](https://docs.astral.sh/uv/) (installs Python 3.11+ itself if needed)
- Network access to wikimedia.org, wikipedia.org and wikidata.org

## Quickstart

```bash
uv sync
uv run -q wikitrends compare --topic "intermittent fasting" --langs pl,cs --last 2y \
  --out outputs/compare.json
uv run -q wikitrends report --input outputs/compare.json --lang en --out outputs/report.pdf
```

Commands: `resolve`, `search`, `fetch`, `trend`, `compare`, `report`.
Details: `uv run wikitrends <command> --help`.

Wikimedia asks API clients for contact info (anonymous requests are rate-limited harder):

```bash
export WIKITRENDS_CONTACT=you@example.com
```

## Using it as an Agent Skill

Copy this directory to `~/.claude/skills/wikipedia-trends/` (or
`<project>/.claude/skills/wikipedia-trends/`) and restart Claude Code.
The agent picks the skill up from its description in [`SKILL.md`](SKILL.md).

## Layout

| Path | Contents |
|---|---|
| `src/wikitrends/` | Code: API client, statistics, charts, PDF report, CLI |
| `tests/` | Unit tests (no network needed): `uv run pytest` |
| `examples/` | Three pre-generated runs: JSON, chart and PDF |
| `references/API.md` | Notes on the Wikimedia API |
| `SKILL.md` | Instructions for the agent |

## Validation

- 37 unit tests on synthetic data with known answers (no network needed)
- Runs against the live Wikimedia API, with JSON values and PDFs checked by hand
- Full end-to-end runs on Claude Haiku 4.5 using only the skill and the user's request,
  with every number in the answer checked against the JSON (four rounds of fixes)

## Roadmap

1. Backtest the signal on 20–50 past cases with known outcomes
2. Automated evals of the example requests and hard cases on several models
3. Topics as sets of articles (Wikidata SPARQL or categories), not a single article
4. Bulk pageview dumps instead of rate-limited REST calls
5. Seasonal decomposition (STL), change-point detection, year-over-year comparisons
6. A second independent signal (Google Trends, app store categories)
7. Shared storage (DuckDB/Postgres) for monitoring and multiple users
8. Multi-page or interactive reports

## License

[MIT](LICENSE)
