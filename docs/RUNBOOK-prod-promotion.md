# RUNBOOK — promoting a build to prod

Read this before "deploying", "shipping", "promoting to prod", or "tagging to prod". The #1
failure mode here is shipping code whose data isn't in the prod DB (the empty-DB trap: HTTP 200
≠ working). Don't skip step 4.

> **Current blocker, measured 2026-07-28:** prod
> `player_game_logs` lacks `game_type`, has only 5,377 2025 NFL rows, and has
> zero rows carrying the published `fg_att` field. Do not promote the current
> draft work until the migration implementation specified by
> `TASK-schema-migrations-and-drift-audit.md` lands and an authorized prod
> schema/data migration passes its acceptance. DEV and Hermes
> each carry 562 `fg_att` rows. No prod mutation was made during this audit.

## How prod actually runs
- Prod = the **docker-compose stack on THIS host** (`docker-compose.yml`), behind host nginx:
  `legendarypicks.xyz` → nginx → `127.0.0.1:3100` (frontend container) → `backend:8000` (`127.0.0.1:8100`).
- **Two DBs, deliberately separate:** dev work uses `backend/data/picks.dev.db` (`LP_DB_PATH`); the
  prod **container** bind-mounts `./backend/data` and uses `backend/data/picks.db`. They drift:
  - prod's `props` / `prop_results` / `prop_games` are **LIVE and ahead** (prod ingest crons run) —
    NEVER overwrite them from dev.
  - dev's `player_game_logs` / `player_stats` are **ahead** (that's where feature work happens) —
    prod is missing/stale until you migrate them over.
- No CI/CD. Deploy = rebuild the images on this host (`docker compose up -d --build`).

## Promotion steps
1. **Land and gate on `dev`.** Complete work in its feature worktree, run the
   feature's acceptance against that code and data, then fast-forward or merge
   it into `dev`. `dev` is the integration/release branch;
   `analytics-backbone` is not a required release waypoint.
2. **Create the release commit on `dev` when a production promotion is actually
   requested.** Update `CHANGELOG.md` + `package.json` version, commit, and push
   `dev`. (Tags `v0.MINOR.PATCH`; v0.x = pre-launch.)
3. **Tag** the release (`git tag -a vX.Y.Z`) and push the tag.
4. **Migrate data into the prod DB FIRST** (never clobber live prop tables).
   The 2026 NFL draft promotion was rehearsed from a fresh online copy of prod;
   use this exact order only in an authorized migration window:
   - Pin and verify the release artifacts before any write. The rehearsed
     hashes are:
     - `stats_player_week_2025.parquet`:
       `afc45559f6385a3f253887f37efcb1124006db799c91a58d8c7151429136f0cc`
     - `snap_counts_2025.parquet`:
       `af7b7b38c8ed0c39a46486941eb919b07adcf8ddf5568a3cb403d263bff4968c`
     - `stats_team_week_2025.parquet`:
       `3916967bb228efef7b42bab7eec7d8c956cfe5aaf886828c784cc91f061bb3a7`
     - `games.csv`:
       `de3ce5e93087fe8b312e014e48ce872a2adf0224ff4f9a207f1c33b31a16b365`
     - `ep_weekly_2025.parquet`:
       `b1d0153f01eb56fd7832f220da600150c0f4315b4cbcda38b9a020c7318fcdd4`
     - `depth_charts_2026.parquet`:
       `7af2069bf0b1937cb18fe156663b75930bbf90247797b178065a396c236e2ffa`
     - `ngs_receiving.parquet`:
       `a7e2cdaa0303d49b6faa7c35c0408cd8c24a206df0ad333399a2cea2889b4ecb`
     The immutable local bundle is
     `/root/lp-release-artifacts/nfl-draft-20260728`; verify it before the
     migration with:
     ```bash
     cd /root/lp-release-artifacts/nfl-draft-20260728
     sha256sum --check MANIFEST.sha256
     ```
   - Run the versioned schema gate first. `--check` is read-only and must
     report only `APPLIED` before the data copy. `--apply` takes and verifies
     an online backup. **One invocation targets BOTH databases by default**
     (six of the seven 2026-08-05 defects were "verified on dev, never shipped
     to prod" — the runner removes the second action rather than reminding you
     to take it):
     ```bash
     backend/venv/bin/python backend/migrate_all.py --check
     backend/venv/bin/python backend/migrate_all.py --apply
     ```
     The runner applies every numbered schema migration and records/adopts the
     20 legacy hand-run migration scripts into `app_schema_migrations` on both
     databases. Re-running is a no-op. `--only prod` / `--only dev` restrict
     to one side when a single database is the actual target.
   - Copy only missing NFL logs/players. The preflight names identity
     mismatches and stable-ID remaps; the apply path names every column,
     backs up prod online, preserves existing enrichment JSON, and compares
     count plus content hash for all three protected prop tables:
     ```bash
     backend/venv/bin/python backend/migrate_logs_to_prod.py \
       --source /root/legendarypicks/backend/data/picks.dev.db \
       --target /root/legendarypicks/backend/data/picks.db \
       --league nfl --check
     backend/venv/bin/python backend/migrate_logs_to_prod.py \
       --source /root/legendarypicks/backend/data/picks.dev.db \
       --target /root/legendarypicks/backend/data/picks.db \
       --league nfl --apply
     ```
   - Refresh the complete roster first; it applies the canonical team and
     position vocabulary (`K` becomes `PK`) only after all 32 ESPN rosters
     are present:
     ```bash
     LP_DB_PATH=/root/legendarypicks/backend/data/picks.db \
       backend/venv/bin/python backend/roster_sync.py nfl
     ```
   - Run the publisher-owned ingests against the pinned artifact directory:
     ```bash
     LP_DB_PATH=/root/legendarypicks/backend/data/picks.db \
       backend/venv/bin/python backend/ingest_nfl_weekly_stats.py \
       --year 2025 --all-positions \
       --cache-dir /root/lp-release-artifacts/nfl-draft-20260728
     LP_DB_PATH=/root/legendarypicks/backend/data/picks.db \
       backend/venv/bin/python backend/ingest_nfl_schedule.py \
       --season 2025 --schedule-only \
       --cache-dir /root/lp-release-artifacts/nfl-draft-20260728
     LP_DB_PATH=/root/legendarypicks/backend/data/picks.db \
       backend/venv/bin/python backend/ingest_nfl_dst.py \
       --year 2025 \
       --cache-dir /root/lp-release-artifacts/nfl-draft-20260728
     LP_DB_PATH=/root/legendarypicks/backend/data/picks.db \
       backend/venv/bin/python backend/ingest_nfl_snap_counts.py \
       --year 2025 \
       --artifact /root/lp-release-artifacts/nfl-draft-20260728/snap_counts_2025.parquet
     LP_DB_PATH=/root/legendarypicks/backend/data/picks.db \
       backend/venv/bin/python backend/ingest_nfl_expected_points.py \
       --year 2025 \
       --cache-dir /root/lp-release-artifacts/nfl-draft-20260728
     LP_DB_PATH=/root/legendarypicks/backend/data/picks.db \
       backend/venv/bin/python backend/ingest_nfl_depth_charts.py \
       --year 2026 \
       --cache-dir /root/lp-release-artifacts/nfl-draft-20260728
     LP_DB_PATH=/root/legendarypicks/backend/data/picks.db \
       backend/venv/bin/python backend/ingest_nfl_ngs_receiving.py \
       --year 2025 \
       --artifact /root/lp-release-artifacts/nfl-draft-20260728/ngs_receiving.parquet
     ```
   - Refresh the current ESPN ADP snapshot only after all 32 D/ST identities
     exist. The ingest materializes every page and validates all 32 D/ST rows
     before its single transaction:
     ```bash
     LP_DB_PATH=/root/legendarypicks/backend/data/picks.db \
       backend/venv/bin/python backend/ingest_nfl_adp.py
     ```
   - `python3 migrate_ufc_rankings_to_prod.py` — validates the complete dev rankings dataset, takes a
     consistent SQLite online backup of
     `picks.db`, then transactionally replaces only `ufc_rankings`. It is safe to re-run and never
     touches props or other production tables.
   - `venv/bin/python ingest_nfl_season_stats.py --year 2025 --cache-dir /absolute/artifact/dir --db /absolute/path/to/picks.db --apply`
     — atomically publish NFL `player_stats` from nflverse's checksummed
     regular-season summary. Run once without `--apply` first and record the
     source/resolved counts and checksum. Never reconstruct these totals from logs.
   - (NBA opponent splits: `backfill_nba_opponent.py` if logs lack `opponent`/`home_away`.)
   - **Verify the NFL candidate before deploying code:** `PRAGMA quick_check`
     is `ok`; 19,399 identity-bearing 2025 NFL logs; 562 rows carry
     `fg_att`; 20,642 snap rows; 544 D/ST rows; 32 active DEF with published
     ADP; zero active legacy `K`; Aubrey has 17 games and positive
     `pk_pts_per_game`; at least 80% PK coverage for kickers with eight games;
     zero pool/board availability disagreements; zero orphan/duplicate
     natural keys; pre-existing snap/NGS enrichment unchanged; and
     `props`, `prop_results`, `prop_games` unchanged by count and content hash.
     Also verify `player_stats` has the exact resolved regular-season source
     count under `source='nflverse_regular_season'`, and UFC rankings contain both P4P
     groups plus all 11 weight divisions.
5. **Deploy.** The backend container needs the DeepSeek key (it can't read the host's
   `/root/.hermes/.env`), so pass it at up-time — it's never stored in the repo:
   ```
   cd /root/legendarypicks
   export DEEPSEEK_API_KEY=$(grep -m1 '^DEEPSEEK_API_KEY=' /root/.hermes/.env | cut -d= -f2- | tr -d '"')
   docker compose up -d --build      # slow: Next.js prod build on a memory-tight box (~minutes)
   ```
6. **Verify on the LIVE domain, not just a 200.** Hit `https://legendarypicks.xyz` and confirm the
   data-backed surfaces actually render real data: Stats leaderboard, a player page, the Matchups tab,
   a PropChart, a game preview. Run `cd backend && python3 verify_ufc_rankings.py`; it fails unless the
   live API has non-empty men's and women's P4P lists and exactly 11 populated weight divisions.
   Empty UI = the migration didn't take. Roll back by restoring the
   `picks.db.bak-premigrate-*` backup + `docker compose up -d` on the prior image.

## Gotchas
- Memory-tight box (~1GB free): the frontend build can OOM. Don't run a second `next dev` during a build.
- `docker compose up --build` rebuilds from the working tree, not a git ref — make sure the tree is the
  release commit.
- Story generation in prod depends on step 5's key; without it `GameStory` silently renders nothing.
- Install/update `scripts/legendarypicks-pipeline.cron` so the validated, transactional UFC ingest
  refreshes production weekly; a failed/partial scrape leaves the prior rankings intact.
