# Audit: cut corners / suboptimal solutions (2026-06-15)

Read-only audit of the prop product. Confirmed by reading code unless marked [verify].

## A. Frontend UI bugs (pages/props.tsx, components/Scores/DayStrip.tsx)
1. **[REPORTED] Search results don't dismiss after selecting a player (Performance tab).**
   `onSelect={p => { setSelectedPlayer(p); setQuery(p.name); setPlayers([]) }}` clears results, but
   `setQuery(p.name)` re-fires the 250ms search effect (`[query]` dep) → it refetches and repopulates
   the dropdown. Fix: add an `open`/`focused` state or a `justSelected` guard so a selection doesn't
   re-trigger the search (close on select; only open on user typing/focus).
2. **[REPORTED] Calendar squashed on mobile (DayStrip).** Fixed `grid grid-cols-7 gap-2` with no
   responsive handling — 7 day-cells crammed into ~360px. Fix: `overflow-x-auto` with `min-w` cells
   (horizontal scroll) on small screens, or render fewer days on mobile.
3. **Search dropdown never closes on click-outside / blur.** Only condition is `players.length > 0`.
   Click elsewhere and it stays open. Fix: click-outside handler / onBlur (with small delay so the
   option click still registers).
4. **Silent search failures.** `catch {}` (empty) on the search fetches; an `error` state exists but
   isn't set. Failures show nothing. Fix: set + surface the error.
5. **Missing empty-state on selected player.** When a player is selected but `performance: []` (no
   settled props yet), the hit-rate section renders blank with no "no graded props yet" message.
6. **NFL/NBA/NHL advanced stats are placeholder stubs** ("pulling from nflfastR/hoopR soon", lines
   ~401–410). [verify] confirm whether the backend `_get_nfl_stats`/`_get_nba_stats` actually return
   real data or the league buildout is UI-stubbed only.

## B. Backend cut corners (backend/sports_service.py)
7. **Stats are NOT persisted.** `_stats_cache` is an in-memory dict (1h TTL) — wiped on every
   redeploy/restart. For a data product, player stats should be **ingested into a `player_stats`
   table** and served from disk. Live-compute + in-memory cache is the corner cut.
8. **pybaseball code/requirements MISMATCH (landmine).** `sports_service.py` does
   `from pybaseball import ...`, but pybaseball was removed from `requirements.txt` and is NOT in the
   running image (`pip show` → not found). MLB Statcast stats currently work only off a stale cache;
   the next clean rebuild returns `"pybaseball not installed"` and Performance stats go blank. Either
   re-add pybaseball to requirements OR move MLB stats to a persisted ingest.
9. **10s cold load = Chadwick register download.** `playerid_lookup` pulls a ~100MB player register
   on the first call per process (then in-memory). No `statcast_id` stored on players (schema is just
   id/name/team/league/espn_id, espn_id 0/122 populated). Fixes: store `statcast_id`/`key_mlbam` at
   ingest so lookup is never needed; pre-warm at startup; persist stats so pybaseball isn't on the
   request path at all.

## C. Process / coordination risk
10. **Concurrent uncommitted edits.** `sports_service.py` AND `pages/props.tsx` have DeepSeek's
    uncommitted changes; deploy edits (docker-compose, next.config, .dockerignore) are also
    uncommitted in the same tree. Fixing now risks clobbering. **Checkpoint (commit) before dividing
    work**, then: one owner on frontend (props.tsx, DayStrip), one on backend (stats persistence,
    pybaseball, leagues).

## Suggested priority
P0 (UX dealbreakers, user-reported): #1 search-dismiss, #2 mobile calendar.
P0 (data integrity): #8 pybaseball mismatch (silent break waiting to happen).
P1: #3 click-outside, #4 errors, #5 empty-state, #7 persist stats, #9 cold-load.
P2: #6 verify league stats are real, code-split props.tsx (538 lines, all 5 tabs in one file).
