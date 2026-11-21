#!/usr/bin/env bash
# Deploy whenever main moves. Run from root's crontab every 5 minutes:
#
#   */5 * * * * /opt/india-grid/deploy/autodeploy.sh >> /opt/india-grid/logs/deploy.log 2>&1
#
# The server pulls from GitHub rather than GitHub pushing to the server, so
# deploys need no inbound access: SSH can stay limited to one admin IP (or
# closed) and nothing holds a key to this box. The website (Vercel) already
# deploys itself on every push to main.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/india-grid}"
cd "$APP_DIR"

# one deploy at a time, and never on top of a hand-run update
exec 9>/tmp/india-grid-deploy.lock
flock -n 9 || exit 0

git fetch -q origin main
here=$(git rev-parse HEAD)
there=$(git rev-parse origin/main)
[ "$here" = "$there" ] && exit 0

echo "--- deploy $(date -u +%FT%TZ): ${here:0:7} -> ${there:0:7}"
if bash deploy/update.sh; then
    echo "--- deployed ${there:0:7}"
else
    echo "--- DEPLOY FAILED at $(git rev-parse --short HEAD); will retry when main moves again or by hand"
fi
