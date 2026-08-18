# India Electricity Data

State-wise live electricity demand, generation mix, and carbon intensity for
India — on a map, with free history and a public API. Estimates are always
labelled as estimates, never presented as measurements.

Live demand covers all 32 states/UTs. Four states publish real per-fuel
generation over SCADA and are reported as **measured** (Punjab, Delhi,
Karnataka, Chhattisgarh); the rest have their fuel mix **estimated** from a
documented freshness ladder — see
[docs/METHODOLOGY.md](docs/METHODOLOGY.md).

![India Electricity Data — live demand choropleth with per-state generation mix and carbon intensity](docs/screenshot.png)

## Layout

- `scrapers/` — Python package (`gridscrapers`): one plugin per source under
  `gridscrapers/sources/`, each exposing `fetch() -> list[RawResponse]` and
  `parse(raw) -> list[Datapoint]`
- `db/migrations/` — TimescaleDB schema (auto-applied on first container start)
- `api/` — FastAPI (Phase 1)
- `web/` — Next.js + MapLibre map (Phase 1)
- `docs/sources/` — endpoint recon notes + archived sample responses
- `deploy/` — production stack (TimescaleDB + API + Caddy TLS + cron tick)

## Quick start

```sh
docker compose up -d --wait          # TimescaleDB on localhost:5433
python3 -m venv .venv
.venv/bin/pip install -e ./scrapers -e ./api
.venv/bin/python -m gridscrapers.tick                # one full scrape of all sources → DB
.venv/bin/python -m gridscrapers.run merit --dry-run # single source, print JSONL, no DB
.venv/bin/python -m pytest scrapers/tests/

# API on :8000
.venv/bin/uvicorn gridapi.main:app --port 8000

# map on :3000 (needs the API running)
cd web && npm install && npm run dev
```

DSN override: `GRID_DB_DSN=postgresql://grid:grid@localhost:5433/india_grid`.
Scheduler: `scripts/tick.sh` runs from cron every 15 min (sources `.env`;
see `.env.example` for the healthchecks.io ping URL — pinged only on fully
successful ticks, so a missed ping is the alert).

## API

- `GET /v1/zones` — every zone: freshest demand met + carbon intensity (with `estimated` flag)
- `GET /v1/zone/{id}/live` — latest value per metric/fuel (e.g. `IN-MH`, `IN`)
- `GET /v1/zone/{id}/history?metric=demand_met&hours=24` — timeseries (≤168 h)
- `GET /v1/zone/{id}/export.csv?metric=&hours=` — CSV download (≤1 year)
- `GET /v1/status` — data quality: per-source uptime/gaps, cross-source deltas, schema drift
  (rendered at `/status` on the web app)

Estimated fuel mix & carbon intensity methodology: [docs/METHODOLOGY.md](docs/METHODOLOGY.md).
Curated plant-name fixes: [data/plant_overrides.json](data/plant_overrides.json)
(wins over fuzzy matching; review queue dump in `data/plant_review_top30.md`).

## Data sources

All upstream data is public. Full per-source latency and provenance tables are
in [docs/METHODOLOGY.md](docs/METHODOLOGY.md); source-by-source recon notes are
in [docs/sources/README.md](docs/sources/README.md).

| Source | Used for |
|---|---|
| [Vidyut Pravah](https://vidyutpravah.in) (Ministry of Power) | live state demand, exchange price |
| [MERIT](https://meritindia.in) (Ministry of Power) | own-generation vs import, plant-wise dispatch |
| RLDC PSP reports (NRLDC/SRLDC/WRLDC) | daily actual fuel shares |
| [CEA](https://cea.nic.in) daily generation + RE reports | fuel-share blend, validation |
| State SLDCs (Punjab, Delhi, Karnataka, Chhattisgarh, Maharashtra) | measured live generation by fuel |

State boundaries from [datameet/maps](https://github.com/datameet/maps)
(CC-BY 2.5 IN). Emission factors are versioned in
`scrapers/gridscrapers/emission_factors.json` (CEA CO2 Baseline Database).

This project is independent and not affiliated with or endorsed by any of the
above organisations.

## License

[MIT](LICENSE) © 2026 Aditya Sawant.

Upstream data remains subject to its publishers' own terms; the MIT license
covers this repository's code and derived outputs only.

