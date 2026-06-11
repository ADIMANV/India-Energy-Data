#!/usr/bin/env bash
# One-shot VPS bootstrap for Ubuntu 24.04. Run as root:
#   curl -fsSL <raw-url>/deploy/bootstrap.sh | bash -s -- <git-repo-url> [branch]
# or copy the repo up and run: bash deploy/bootstrap.sh <git-repo-url>
#
# Optional: put a custom-format dump at /tmp/india_grid.dump BEFORE running
# and it will be restored (see deploy/README.md for the dump command).
set -euo pipefail

REPO_URL="${1:?usage: bootstrap.sh <git-repo-url> [branch]}"
BRANCH="${2:-main}"
APP_DIR=/opt/india-grid
COMPOSE="docker compose -f deploy/docker-compose.prod.yml --env-file .env"

echo "==> 1/7 docker"
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
fi

echo "==> 2/7 clone $REPO_URL ($BRANCH) -> $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" fetch origin "$BRANCH" && git -C "$APP_DIR" checkout "$BRANCH" && git -C "$APP_DIR" pull --ff-only
else
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"
mkdir -p logs

echo "==> 3/7 .env"
if [ ! -f .env ]; then
    cp .env.example .env
    echo
    echo "!! Edit $APP_DIR/.env now (POSTGRES_PASSWORD, API_DOMAIN, HEALTHCHECK_URL),"
    echo "!! then re-run this script. Stopping."
    exit 1
fi

echo "==> 4/7 build + start db/api/caddy"
$COMPOSE up -d --build --wait db api caddy

echo "==> 5/7 restore dump if present"
if [ -f /tmp/india_grid.dump ]; then
    echo "    restoring /tmp/india_grid.dump (timescaledb pre/post restore)"
    $COMPOSE exec db psql -U grid -d india_grid -c "SELECT timescaledb_pre_restore();"
    $COMPOSE exec -T db pg_restore -U grid -d india_grid --no-owner --clean --if-exists < /tmp/india_grid.dump
    $COMPOSE exec db psql -U grid -d india_grid -c "SELECT timescaledb_post_restore(); ANALYZE;"
    echo "    restored. row counts:"
    $COMPOSE exec db psql -U grid -d india_grid -c "SELECT source, count(*) FROM datapoints GROUP BY source;"
else
    echo "    no /tmp/india_grid.dump — fresh DB from migrations"
fi

echo "==> 6/7 cron (every 15 min)"
CRON_LINE="*/15 * * * * cd $APP_DIR && $COMPOSE run --rm tick >> $APP_DIR/logs/tick-cron.log 2>&1"
( crontab -l 2>/dev/null | grep -vF "india-grid" | grep -vF "$APP_DIR" ; echo "$CRON_LINE" ) | crontab -
crontab -l | tail -1

echo "==> 7/7 first tick + smoke test"
$COMPOSE run --rm tick || echo "WARN: first tick reported issues (see output above)"
sleep 1
curl -s "http://127.0.0.1:8000/v1/zones" | head -c 200 && echo
echo
echo "Done. API: https://\$API_DOMAIN/v1/zones (once DNS + Let's Encrypt settle)."
echo "Probe RLDCs next:  cd $APP_DIR && $COMPOSE run --rm tick python scripts/probe_rldc.py"
