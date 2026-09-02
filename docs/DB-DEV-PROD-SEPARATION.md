# DB — Dev / Prod Separation

**Author:** orchestrator
**Date:** 2026-06-25
**Status:** ACTIVE. Read this before running any backend script or deploying.

## TL;DR
- **Prod DB** = `/root/legendarypicks/backend/data/picks.db`. It is **bind-mounted into the
  running prod container** (`legendarypicks-backend-1`, serves legendarypicks.xyz). Anything
  that writes here writes to **live production**.
- **Dev DB** = `/root/legendarypicks/backend/data/picks.dev.db`. Seeded from a prod backup,
  fully isolated (separate file + inode). **Use this for all development.**
- **Which one you hit is controlled by `LP_DB_PATH`.** Set it for dev; leave it unset for prod.
- **Default (unset) = prod.** This is deliberate so deploys keep working unchanged, but it
  means dev scripts run without `LP_DB_PATH` will silently write to prod. Always set the env
  var for dev (see §3).

## 1. How the DB path is resolved
Every backend script and the FastAPI service resolve the DB path the same way:

```python
DB = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
```

Files that do this: `sports_service.py` (5 sites), `settle_props.py`, `settlement.py`,
`backfill_team_stats.py`, `link_prop_games.py`, `ingest_hoopR.py`, `ingest_nhl.py`,
`ingest_nfl.py`, `ingest_statcast.py`. (12 connect sites total.)

- `LP_DB_PATH` **unset** → `backend/data/picks.db` (prod).
- `LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db` → dev.

The prod container does NOT set `LP_DB_PATH`, so it uses the default and reads the
bind-mounted prod file. Changing `LP_DB_PATH` only affects the process you set it on.

## 2. The prod DB and its bind-mount
`docker-compose.yml` bind-mounts the host data dir into the container:

```yaml
backend:
  volumes:
    - ./backend/data:/app/data   # host /root/legendarypicks/backend/data -> container /app/data
```

So the container's `/app/data/picks.db` **is the same file** as
`/root/legendarypicks/backend/data/picks.db` on the host. Writes from either side are
immediately visible to the other. The prod container runs an ingest+settle cadence, so
this file is actively written — treat it as live at all times.

**Prod is NOT gitignored-tracked:** `backend/data/picks.db` is in `.gitignore` (the repo
ships no DB). Each environment has its own local `data/picks.db`.

**Backups (the safety net):**
- `backend/data/picks.db.bak-20260615-182333` (4.2 MB) — oldest
- `backend/data/picks.db.bak-20260624` (6.8 MB) — pre-session baseline (10,393 prop_results)
- `backend/data/picks.db.bak-20260624-m6` (7.1 MB) — mid-M6

Before any prod-touching operation, take a fresh backup:
`cp backend/data/picks.db backend/data/picks.db.bak-$(date +%Y%m%d-%H%M%S)`.

## 3. How to use the dev DB
Set `LP_DB_PATH` for any dev command. Examples (from `backend/`):

```bash
# run the API against dev
LP_DB_PATH=$PWD/data/picks.dev.db venv/bin/uvicorn sports_service:app --port 8001

# run settlement against dev (idempotency testing, void persistence, etc.)
LP_DB_PATH=$PWD/data/picks.dev.db venv/bin/python settle_props.py

# backfill team stats into dev
LP_DB_PATH=$PWD/data/picks.dev.db venv/bin/python backfill_team_stats.py

# capture odds snapshots into dev
LP_DB_PATH=$PWD/data/picks.dev.db venv/bin/python -m bovada_scraper mlb --capture

# one-shot env for a subshell
export LP_DB_PATH=$PWD/data/picks.dev.db
```

Use a **different port** (e.g. 8001) for the dev API so it doesn't clash with the prod
container on 8000.

### Bootstrap a fresh dev DB
The committed dev DB (`backend/data/picks.dev.db`) is seeded and ready. To rebuild it from
the latest prod backup:

```bash
cd backend/data
cp picks.db.bak-20260624 picks.dev.db    # seed from a static backup (no torn read)
# the M5/M6 schema self-creates on first import via _init_db(); nothing to run manually.
```

`_init_db()` (in `sports_service.py`, runs on app import) self-creates `team_game_stats`,
`prop_odds_snapshots`, and adds `props.odds` / `props.odds_captured_at` idempotently — so a
freshly-seeded dev DB upgrades itself on first use. No manual DDL.

### Verify isolation (paranoia check)
```bash
stat -c 'prod inode=%i size=%s' backend/data/picks.db
stat -c 'dev  inode=%i size=%s' backend/data/picks.dev.db
# different inode = isolated. Write to dev, confirm prod size unchanged.
```

## 4. Guardrails (non-negotiable)
- **Never run a dev script against prod.** Always set `LP_DB_PATH` for dev. If unsure,
  `echo $LP_DB_PATH` before running — empty means PROD.
- **No destructive ops (DROP/DELETE/TRUNCATE/ALTER-that-loses-data) on prod** without a
  fresh `picks.db.bak-<timestamp>` in place. The prod DB is live.
- **Take a backup before any deploy** that touches schema or data.
- **Don't bind-mount dev into prod's compose** — `docker-compose.yml` mounts
  `./backend/data`. The dev file (`picks.dev.db`) sits in that same dir but the prod
  container ignores it (only opens `picks.db` via the default path). Safe, but don't point
  the prod container's `LP_DB_PATH` at the dev file.
- **Stray processes:** do not leave a bare `uvicorn sports_service:app` / `python
  sports_service.py` running on port 8000 — it shares the prod DB and collides with the
  container. Dev servers go on 8001 with `LP_DB_PATH` set.

## 5. What this session wrote to prod (and why it's safe to leave)
On 2026-06-24 this session mutated the **prod** DB directly (dev/prod separation did not
exist yet). All writes were **additive**, non-breaking, and backed up:
- **M4** (`f8e2d96`): +2,393 void rows in `prop_results` (`hit IS NULL`) — fixes cron
  re-voiding. Settlement verified idempotent.
- **M5** (`1e7fb43`): +1,152 `team_game_stats` rows. New table.
- **M6-impl** (`48c0f67`): `ALTER TABLE props ADD COLUMN odds/odds_captured_at` (now also in
  `_init_db()`), +3,135 `prop_odds_snapshots` rows, `props.odds` populated on ingested rows.

Decision (CEO, 2026-06-25): **leave in place.** Additive, backed up, and the new code uses
them via `CREATE TABLE IF NOT EXISTS` / idempotent `ALTER`. Deploying the current code will
work on both the already-mutated prod file and a fresh DB (verified — `_init_db()` self-heals
the M6 schema; this was a latent deploy-landmine now fixed).

## 6. Note on `/root/lp-yolo`
`/root/lp-yolo` is a **stale full copy of the repo** dated 2026-06-15 (an old "yolo"/
auto-approve agent checkout). Its `backend/data/picks.db` is **empty/uninitialized**
(`no such table: props`). It is **not** a dev database and never was — do not use it for dev.
The canonical dev DB is `/root/legendarypicks/backend/data/picks.dev.db` (§3). The `lp-yolo`
checkout can be deleted once confirmed unneeded.

## 7. Deploy reminder
The prod container still runs **old code** (pre-M3..M7) until rebuilt. To deploy the current
branch:
1. Backup prod DB (§2).
2. Push/merge the branch per your flow.
3. On the VPS: `git pull && docker compose up -d --build`.
4. Verify on prod: `/api/nba/team-stats` non-empty, `/api/capture-odds` 200,
   `settle_props.py` clean, site renders. **CEO sign-off required** before deploy and before
   enabling any live Bovada capture cron.