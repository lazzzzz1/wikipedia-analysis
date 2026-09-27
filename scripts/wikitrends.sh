#!/usr/bin/env bash
# Runs the wikitrends CLI from any working directory; uv creates/syncs .venv on first use.
exec uv run -q --project "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" wikitrends "$@"
