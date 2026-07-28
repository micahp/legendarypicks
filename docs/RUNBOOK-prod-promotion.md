# RUNBOOK — promoting a build to prod

Read this before "deploying", "shipping", "promoting to prod", or "tagging to prod". The #1
failure mode here is shipping code whose data isn't in the prod DB (the empty-DB trap: HTTP 200
≠ working). Don't skip step 4.

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
4. **Migrate data into the prod DB FIRST** (additive; never clobber live prop tables). Player IDs are
   ~fully aligned dev↔prod (resolve-by-ID still holds). The proven path:
   - `cd backend && python3 migrate_logs_to_prod.py` — backs up `picks.db`, creates `player_game_logs`,
     copies the missing player rows + all logs (excluding identity-mismatched shared IDs).
   - `python3 migrate_ufc_rankings_to_prod.py` — validates the complete dev rankings dataset, takes a
     consistent SQLite online backup of
     `picks.db`, then transactionally replaces only `ufc_rankings`. It is safe to re-run and never
     touches props or other production tables.
   - `LP_DB_PATH=data/picks.db venv/bin/python derive_player_stats.py` — re-derive `player_stats` from
     the copied logs.
   - (NBA opponent splits: `backfill_nba_opponent.py` if logs lack `opponent`/`home_away`.)
   - **Verify**: `player_game_logs` non-empty, `player_stats` current, `props`/`prop_results` UNCHANGED,
     and `ufc_rankings` contains both P4P groups plus all 11 weight divisions.
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
