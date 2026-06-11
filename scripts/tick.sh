#!/bin/sh
# Cron entrypoint: one scraper tick, logging to logs/tick.log.
# Installed as: */15 * * * * /bin/sh "<repo>/scripts/tick.sh"
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs

# cron runs with a bare environment; load HEALTHCHECK_URL / GRID_DB_DSN from .env
if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

.venv/bin/python -m gridscrapers.tick >> logs/tick.log 2>&1
status=$?
[ $status -ne 0 ] && echo "$(date -u +%FT%TZ) tick exited $status" >> logs/tick-failures.log
exit $status
