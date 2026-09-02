# Backend Folder Audit — 2026-08-18

## What `backend/data/` currently holds

| Path | Type | Size | Tracking | Writer |
|---|---|---|---|---|
| `picks.db` | App data (prod DB) | 409MB | Ignored | Backend runtime |
| `picks.dev.db` | App data (dev DB) | 380MB | Ignored | Backend runtime |
| `espn-cache/` | HTTP response cache | 134MB | Ignored | `espn_client.py` |
| `.espn-cache/` | HTTP response cache (old location) | 96MB | Ignored | `espn_client.py` |
| `bovada-league-backoff.json` | Operational state | 565B | Ignored | `bovada_scraper.py` |
| `esports_results.json` | Runtime output | 469KB | Ignored | `routers/esports/results_store.py` |
| `esports_state_snapshot.json` | Runtime output | 124KB | Ignored | `monitor_esports_state.py` |
| `plays_board.json` | Runtime output | 6KB | Ignored | `routers/plays.py` |
| `reconcile.log` | Run log | 67KB | Ignored | `reconcile_core.py` |
| `reconcile-event-cache.json` | Cache | 572KB | Ignored | `reconcile_core.py` |
| `news-deletions.log` | Run log | 13KB | Ignored | `ingest_league_narratives.py` |
| `esports_ewc_schedules/` | Seeded content | ~200KB | Tracked | `fetch_ewc_*` |
| `esports_team_logos.json` | Seeded content | 13KB | Tracked | `routers/esports/` |
| `esports_ewc_standings.json` | Seeded content | 27KB | Tracked | `fetch_ewc_standings.py` |
| `esports_yt_liveness.json` | Seeded content | 166B | Tracked | esports monitor |
| `identity-consolidations.jsonl` | Operational log | 12KB | Tracked | identity merge |
| `name-aliases.json` | Seeded content | 2KB | Tracked | `name_aliases.py` |
| `position-vocabulary.json` | Seeded content | 33KB | Tracked | `fetch_position_vocabulary.py` |
| `published-identity-names.json` | Seeded content | 1MB | Tracked | `fetch_identity_names.py` |
| `ufc_rankings_seed.json` | Seeded content | 15KB | Tracked | `ingest_ufc_rankings.py` |
| `nflverse_games_2026.csv` | Seeded content | 2.2MB | Tracked | `ingest_nfl_schedule.py` |
| `sample_data.json` | Test fixture | 2KB | Tracked | tests |
| `sample_props.json` | Test fixture | 643B | Tracked | tests |
| `PHASE*-FINDINGS-v0.6.13.md` | Docs | 7KB | Tracked | v0.6.13 re-cut |
| `PINNED-ARTIFACTS-v0.6.13.md` | Docs | 3KB | Tracked | v0.6.13 re-cut |
| `picks.db.bak-*` | Backups | 40-400MB each | Ignored | `migrate_*` scripts |
| `picks.dev.db.bak-*` | Backups | 40-380MB each | Ignored | `migrate_*` scripts |
| `picks.db.pre-*-*.bak` | Backups | 230-380MB each | Ignored | `migrate_*` scripts |

## The three misses (2026-08-17)

All three share the same root cause: **an ignore rule protects the path it names and nothing near it.**

| What was written | Where | What should have caught it | Why it didn't |
|---|---|---|---|
| 236MB DB backup | `backend/backups/` | `.gitignore` + `backend/.dockerignore` `data/picks.db*` | patterns anchored to `backend/data/` |
| 96MB ESPN response cache | `backend/.espn-cache/` | `.gitignore:88` `backend/data/espn-cache/` | the rule names a path that does not exist |
| Bovada backoff state | `backend/data/…json` | nothing | tracked on purpose, then rewritten every run |

The cache one is the tell: somebody already wrote the ignore rule for it and pointed it at the wrong directory. The intent has been in the tree unfulfilled for months.

## The directory contract

`backend/data/` currently has no stated purpose. It holds at least five different kinds of data with different tracking policies:

1. **App data** — `picks.db`, `picks.dev.db`. Bind-mounted in prod. Never tracked. Ignored by both `.gitignore` and `.dockerignore`.
2. **Seeded content** — `esports_ewc_schedules/`, `esports_team_logos.json`, `position-vocabulary.json`, `ufc_rankings_seed.json`, `nflverse_games_2026.csv`, etc. Tracked. Published data that the app reads but does not write.
3. **Runtime caches** — `espn-cache/`, `.espn-cache/`, `reconcile-event-cache.json`. Never tracked. Rebuilt on demand.
4. **Operational state** — `bovada-league-backoff.json`, `esports_state_snapshot.json`, `plays_board.json`. Never tracked. Rewritten by runtime processes.
5. **Run logs** — `reconcile.log`, `news-deletions.log`. Never tracked. Append-only.

## The fix

The question is not "add more patterns." It is: **what is `backend/data/` for?**

Proposed contract:

- `backend/data/` = app data only (`picks.db`, `picks.dev.db`, their backups and WAL/SHM files). Ignored by both `.gitignore` and `.dockerignore`. Bind-mounted in prod.
- `backend/data/seeds/` = seeded content that the app reads but does not write. Tracked. Currently scattered files like `esports_team_logos.json`, `position-vocabulary.json`, etc. would move here.
- `backend/data/cache/` = runtime caches. Ignored. Currently `espn-cache/` and `reconcile-event-cache.json` would move here.
- `backend/data/state/` = operational state. Ignored. Currently `bovada-league-backoff.json`, `esports_state_snapshot.json`, `plays_board.json` would move here.
- `backend/data/logs/` = run logs. Ignored. Currently `reconcile.log`, `news-deletions.log` would move here.

This is a large move. The immediate fix is to update the ignore rules to cover the paths that actually exist, and to stop the three current writers from dirtying the tree.

## Immediate actions (no moves, just rule fixes)

1. `.gitignore` already ignores `backend/.espn-cache/` (line 88) and `backend/data/bovada-league-backoff.json` (line 103). Both are correct for the paths that exist.
2. `.dockerignore` already ignores `data/espn-cache` and `.espn-cache` (lines 7-8). Both are correct.
3. The remaining gap: `backend/data/esports_results.json`, `backend/data/esports_state_snapshot.json`, `backend/data/plays_board.json`, `backend/data/reconcile.log`, `backend/data/reconcile-event-cache.json`, `backend/data/news-deletions.log` are all correctly ignored by existing rules (`esports_results.json`, `esports_state_snapshot.json`, `plays_board.json`, `*.log`, `backend/data/reconcile-event-cache.json`).
4. The real risk is not the current state — it is the next writer. A check that fails when a writer writes somewhere no rule covers would catch the next miss before it costs another release.

## Recommendation

Do the full directory restructure (seeds/cache/state/logs subdirectories) as a separate commit. It is a pure move with no behavior change, but it touches many import paths. The immediate rule fixes are already in place.
