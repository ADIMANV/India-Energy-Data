# Production deploy (VPS with Indian IP)

Target: Ubuntu 24.04, root access, a DNS A record (`api.<your-domain>`)
pointing at the VPS. Everything runs in docker; cron fires the scraper tick.

## 1. Bootstrap

```sh
# on the VPS, as root
curl -fsSL https://raw.githubusercontent.com/<you>/<repo>/main/deploy/bootstrap.sh \
  | bash -s -- https://github.com/<you>/<repo>.git
# first run stops after creating .env — edit it, then re-run the same command
```

The script is idempotent: installs docker (get.docker.com), clones/updates the
repo at `/opt/india-grid`, builds the image, starts `db` + `api` + `caddy`,
restores a dump if `/tmp/india_grid.dump` exists, installs the 15-min cron
tick, runs the first tick, and smoke-tests `/v1/zones`.

Caddy answers `https://$API_DOMAIN` with automatic Let's Encrypt certs; the
API itself only listens on 127.0.0.1. The DB is only reachable from localhost
(port 5433) and the docker network.

## 2. Migrating today's local history

**Version check first** — pg_restore needs the VPS TimescaleDB at the same or
newer version than local. Both composes use `timescale/timescaledb:latest-pg16`;
verify with:

```sh
docker compose exec db psql -U grid -d india_grid \
  -c "SELECT extversion FROM pg_extension WHERE extname='timescaledb';"
```

**On the laptop** (root docker-compose running):

```sh
docker compose exec -T db pg_dump -U grid -d india_grid -Fc > india_grid.dump
scp india_grid.dump root@<vps-ip>:/tmp/india_grid.dump
```

**On the VPS** — easiest: place the dump *before* running bootstrap and it
restores automatically. Manually, after `db` is up:

```sh
cd /opt/india-grid
C="docker compose -f deploy/docker-compose.prod.yml --env-file .env"
$C exec db psql -U grid -d india_grid -c "SELECT timescaledb_pre_restore();"
$C exec -T db pg_restore -U grid -d india_grid --no-owner --clean --if-exists < /tmp/india_grid.dump
$C exec db psql -U grid -d india_grid -c "SELECT timescaledb_post_restore(); ANALYZE;"
# sanity:
$C exec db psql -U grid -d india_grid -c "SELECT source, count(*), max(ts) FROM datapoints GROUP BY source;"
```

The `timescaledb_pre_restore()` / `timescaledb_post_restore()` pair is
required — restoring hypertable catalogs without them corrupts the extension
state. `--clean --if-exists` replaces the schema the migrations created on
first boot, so the restore is safe on a fresh bootstrap.

## 3. RLDC probe (the reason this VPS exists)

WRLDC returned `{"d":"[]"}` from a non-Indian IP in Phase 0 recon. From the VPS:

```sh
cd /opt/india-grid
docker compose -f deploy/docker-compose.prod.yml --env-file .env \
  run --rm tick python scripts/probe_rldc.py
```

Raw responses land in `docs/sources/probe-vps/` with a `summary.md` table
(data / empty / error per endpoint). Commit that directory and we decide which
parsers to write based on it. No new parsers before probe results.

## 4. Frontend on Vercel

```sh
cd web
npx vercel link            # one-time: create/link project, root = web/
npx vercel env add NEXT_PUBLIC_API_URL production
#   value: https://api.<your-domain>      (must be https — Vercel pages are
#   https and browsers block mixed-content fetches to http://ip:8000)
npx vercel --prod
```

API CORS is already `*`, so no server change is needed. After deploy, the map
should show data with fresh "updated X min ago" labels; if every state is
grey/stale, the cron tick on the VPS is the first thing to check
(`tail /opt/india-grid/logs/tick-cron.log`).

## Operations

```sh
C="docker compose -f deploy/docker-compose.prod.yml --env-file .env"
$C ps                         # status
$C logs -f api                # API logs
tail -f logs/tick-cron.log    # scraper runs (cron)
$C run --rm tick              # manual tick
$C up -d --build api          # deploy code update (after git pull)
```
