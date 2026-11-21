#!/usr/bin/env bash
# Bring a running server up to date with main: code and schema. Safe to run
# again; deploy/autodeploy.sh runs it whenever main moves. By hand:
#
#   sudo bash /opt/india-grid/deploy/update.sh
#
# bootstrap.sh builds a server from nothing; this is for every update after.
# One-off data repairs (backfills, reparses) are not here — they're run by
# hand when a change needs them (see deploy/README.md, "After a parser fix").
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/india-grid}"
cd "$APP_DIR"
C="docker compose -f deploy/docker-compose.prod.yml --env-file .env"

echo "==> code: $(git log --oneline -1)"
git fetch -q origin main
git checkout -q main
git pull -q --ff-only origin main
echo "    now at $(git log --oneline -1)"

# The db container only runs migrations when its volume is first created, so
# later ones are applied here. 010 onwards are written to be re-runnable.
echo "==> schema"
for f in db/migrations/01[0-9]_*.sql; do
    $C exec -T db psql -v ON_ERROR_STOP=1 -q -U grid -d india_grid < "$f"
done

echo "==> rebuild api + tick image (cron runs the tick every 15 min)"
$C up -d --build --wait api
$C build -q tick

echo "==> smoke test (from inside the api container)"
$C exec -T api python - <<'PY'
import json, urllib.request as u
for path in ("/v1/zones", "/v1/stations/status", "/v1/zone/IN-GJ/live"):
    with u.urlopen("http://localhost:8000" + path) as r:
        body = json.load(r)
    note = ""
    if path.endswith("status"):
        note = f"as_of {body.get('as_of')}, {len(body.get('stations', {}))} stations"
    if path.endswith("live"):
        note = f"{sum(m['metric'] == 'carbon_intensity' for m in body['metrics'])} carbon readings"
    print(f"    {path}: {r.status} {note}")
PY
