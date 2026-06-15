# HANDOFF → DeepSeek (2026-06-15): persist MLB + NFL like you did NBA; fix MLB landmine; NHL→ESPN

Your NBA switch is the template: `ingest_hoopR.py` → `player_stats` table → `_get_nba_stats` reads
from DB (no API on the request path). Apply that SAME pattern to the rest.

## 1. MLB — move pybaseball OFF the request path (fixes 2 bugs at once)
- **Bug A (landmine):** `_get_mlb_stats` does `from pybaseball import ...`, but pybaseball is NOT in
  requirements.txt and NOT in the image → on a clean rebuild MLB stats return "pybaseball not
  installed" and go blank. Currently only "works" off a stale in-memory cache.
- **Bug B (10s cold load):** `playerid_lookup` downloads the ~100MB Chadwick register on first call
  per process; wiped on every redeploy.
- **Fix:** create `ingest_statcast.py` (mirror `ingest_hoopR.py`) that pulls Statcast and writes MLB
  rows into `player_stats`. Switch `_get_mlb_stats` to **read from `player_stats`** (like
  `_get_nba_stats`). pybaseball moves to INGEST-time only (run offline/scheduled), never the request
  path. Add pybaseball to requirements so the ingest script runs; the request path stays DB-only so
  it serves instantly even if ingest hasn't run / pybaseball fails.

## 2. NFL — same DB-backed switch
- `_get_nfl_stats` currently pulls `nfl_data_py` on-demand. Create/extend an ingest that writes NFL
  rows into `player_stats`; switch `_get_nfl_stats` to read from the DB. nfl_data_py = ingest-time only.

## 3. NHL — switch to ESPN (you flagged this yourself)
- Name resolution is hardcoded to 6 stars (nhle.com search 404s from this server). Use ESPN NHL
  (already integrated, confirmed 200): rosters for name→id resolution, box/landing for stats. Persist
  to `player_stats`. Same as the NBA fix rationale.

## 4. Cleanup
- Retire `_stats_cache` for any league now DB-backed (DB read is already fast; in-memory cache just
  causes the cold-load + stale-after-redeploy problems).

## Discipline (unchanged)
- Isolate each league in its OWN fresh subprocess (don't poison context).
- Tests per league: name-resolution coverage (Bovada players resolve), sample stat fetch from DB,
  one end-to-end prop settlement. Must pass before "done".
- The REQUEST path must be DB-only and instant for ALL leagues when you finish.

## Deliverable
Update `docs/HANDOFF-deepseek-to-claude-other-leagues-2026-06-15.md` with per-league results + ping me.
Note: DayStrip.tsx (mobile calendar) + PlayerSearch dropdown fixes are mine/landed — don't touch.
