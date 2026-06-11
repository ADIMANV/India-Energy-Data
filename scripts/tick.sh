#!/bin/sh
# Cron entrypoint: one scraper tick, logging to logs/tick.log.
# Installed as: */15 * * * * /bin/sh "<repo>/scripts/tick.sh"
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
.venv/bin/python -m gridscrapers.tick >> logs/tick.log 2>&1
status=$?
[ $status -ne 0 ] && echo "$(date -u +%FT%TZ) tick exited $status" >> logs/tick-failures.log
exit $status
