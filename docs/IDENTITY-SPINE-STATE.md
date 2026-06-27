# Identity Spine — current state & rules (2026-06-26)

How player identity actually works today, and the ONE rule that prevents the coverage
gaps. Complements the design in `SPEC-player-identity-spine.md` (that's the plan; this is
the as-built + the lesson from the MLB dup bug).

## The spine
`players` is the canonical table — **one row per real human**, with every source's native ID:

| Column | Source it comes from | Used by |
|---|---|---|
| `id` (PK) | surrogate | **everything joins on this** |
| `espn_id` | ESPN (scores, rosters, NBA box scores) | roster_sync, NBA logs, props players |
| `mlbam_id` | MLB / Statcast | MLB game logs (`ingest_mlb_logs`) |
| `nfl_gsis_id` | nflverse (weekly + pbp) | NFL game logs |
| `nhl_id` | api-web.nhle.com | NHL game logs |
| `nba_id` | hoopR athlete_id | (legacy NBA) |

Downstream tables key on `players.id`: `player_game_logs.player_id`, `props.player_id`,
`player_stats.player_id`, `predictions.player_id`. The whole point: **join on the stable
integer `id`, never on `name`.**

## The id-space problem (why dups happen)
Each source speaks a DIFFERENT id language, and they don't overlap:
- A roster/props player arrives with an **espn_id**.
- A Statcast game-log arrives with an **mlbam_id**.
- These are different numbers for the same human, linked only through the `players` row
  that carries BOTH. If a row has espn_id but not mlbam_id (or vice-versa), an ingest keyed
  on the missing id won't find it.

## THE RULE (non-negotiable for any ingest)
**Resolve to an existing canonical row by source-id; NEVER create a second row for a human
who already exists under another source-id. If you can't resolve, queue it — don't dup.**

Resolution order when ingesting source X with native id `xid`:
1. `SELECT id FROM players WHERE <x_id_col> = xid` → use it.
2. Else try to **link**: find the canonical row by a *reliable* cross-ref (another shared id,
   or a verified name+team+league match) and **backfill** `<x_id_col>` onto it.
3. Else insert into `unresolved_players` (review queue) — do NOT silently create a players row.

## What went wrong (the MLB dup bug, fixed)
`ingest_mlb_logs.py`'s `_resolve_or_add(mlbam, ...)` did step 1, but on miss it **inserted a
new players row** (placeholder lowercase name, no espn_id) and wrote logs under it — instead
of linking to the existing espn_id roster row (step 2) or queueing (step 3). Result: **317
mlbam_ids split across two rows** — props on the espn row, 18k logs on the mlbam row — so
prop charts found no logs for Freeman/Betts/Kurtz/etc. Coverage *looked* 53%; real data was 90%.

**Remediation shipped:** `dedupe_mlb.py` merges by `mlbam_id` (provably same human), repoints
logs/props/stats to the canonical (espn_id) row, deletes the dup. Identity-safe — only merges
rows sharing a real source-id, never by name (per "resolve by ID, never name").

## Current dup status (verified 2026-06-26)
- NFL: 0 · NBA: 0 (espn_id UNIQUE constraint blocks it) · NHL: 3 · MLB: 5 residual
  (the NHL/MLB residual are `mlbam=NULL`/name-only cases; no prop impact — props are MLB-only
  and those players are unresolved, a separate resolution gap not a dup).

## Going forward
- New per-game-log / props ingests MUST follow THE RULE above (resolve-or-queue, never dup).
- Before any new league gets props, run an identity-safe dedup for it (generalize `dedupe_mlb.py`
  by that league's source-id).
- The real coverage fix for the residual is **mlbam resolution** for unresolved props players
  (Bovada name → mlbam crosswalk), not more dedup.
- Dedup scripts: `dedupe_nfl.py` (orphan stubs), `dedupe_mlb.py` (source-id merge + repoint).
