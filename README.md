# India Live Grid Map

Electricity-Maps-for-India: state-wise live demand, generation mix, and carbon
intensity on a map, with free history and API. See `docs/` for the build plan
and source recon.

## Layout

- `scrapers/` — Python package (`gridscrapers`): one plugin per source under
  `gridscrapers/sources/`, each exposing `fetch() -> list[RawResponse]` and
  `parse(raw) -> list[Datapoint]`
- `db/migrations/` — TimescaleDB schema (auto-applied on first container start)
- `api/` — FastAPI (Phase 1)
- `web/` — Next.js + MapLibre map (Phase 1)
- `docs/sources/` — endpoint recon notes + archived sample responses
- `docs/reference/emaps-parsers/` — electricitymaps-contrib India parsers (MIT, reference only)

## Quick start

```sh
docker compose up -d --wait          # TimescaleDB on localhost:5433
python3 -m venv .venv
.venv/bin/pip install -e ./scrapers
.venv/bin/python -m gridscrapers.run vidyut_pravah   # all-state demand/price → DB
.venv/bin/python -m gridscrapers.run merit           # live demand/own-gen/import → DB
.venv/bin/python -m gridscrapers.run merit --dry-run # print JSONL, no DB
.venv/bin/python -m pytest scrapers/tests/
```

DSN override: `GRID_DB_DSN=postgresql://grid:grid@localhost:5433/india_grid`

## Iron rules

1. Raw responses are archived to `raw_responses` **before** parsing — parsers
   will break; raw data lets us backfill.
2. One plugin per source. Parsers are pure functions of archived bytes and are
   versioned via `PARSER_VERSION`.
