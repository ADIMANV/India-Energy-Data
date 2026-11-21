#!/usr/bin/env bash
# Bring a running server up to date with main: code, schema, and the one-off
# re-runs a parser fix needs. Safe to run again. On the server:
#
#   cd /opt/india-grid && git pull --ff-only && sudo bash deploy/update.sh
#
# bootstrap.sh builds a server from nothing; this is for every update after.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/india-grid}"
cd "$APP_DIR"
C="docker compose -f deploy/docker-compose.prod.yml --env-file .env"

echo "==> 1/5 code: $(git log --oneline -1)"
git fetch -q origin main
git checkout -q main
git pull -q --ff-only origin main
echo "    now at $(git log --oneline -1)"

# The db container only runs migrations when its volume is first created, so
# later ones are applied here. 010 onwards are written to be re-runnable.
echo "==> 2/5 schema"
for f in db/migrations/01[0-9]_*.sql; do
    echo "    $f"
    $C exec -T db psql -v ON_ERROR_STOP=1 -q -U grid -d india_grid < "$f"
done

echo "==> 3/5 rebuild api + tick image"
$C up -d --build --wait api
$C build tick

# Re-run the CEA parser over every archived daily report: fixes Chhattisgarh
# (filed under Uttar Pradesh before 20 Nov 2026) and fills station_status.
echo "==> 4/5 CEA reparse"
$C run --rm tick python -m gridscrapers.cea reparse

echo "==> 5/5 one tick now (cron runs it every 15 min after this)"
$C run --rm tick || echo "WARN: the tick reported failures — see above"

echo
echo "Smoke test (from inside the api container):"
$C exec -T api python - <<'PY2'
import json, urllib.request as u
for path in ("/v1/zones", "/v1/stations/status", "/v1/zone/IN-GJ/live"):
    with u.urlopen("http://localhost:8000" + path) as r:
        body = json.load(r)
    note = ""
    if path.endswith("status"):
        note = f"as_of {body.get('as_of')}, {len(body.get('stations', {}))} stations"
    if path.endswith("live"):
        note = f"{sum(m['metric'] == 'carbon_intensity' for m in body['metrics'])} carbon readings"
    print(f"  {path}: {r.status} {note}")
PY2
