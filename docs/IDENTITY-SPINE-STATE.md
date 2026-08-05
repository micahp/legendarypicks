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

---

## CORRECTION — 2026-08-04: "identity-safe" was an assumption, not a property

Everything above stands as written on 2026-06-26 except one sentence, and it is the load-bearing one:

> "Identity-safe — only merges rows sharing a real source-id, never by name."

That is safe **only if the source-id on the row names the person on the row.** Nothing had ever
checked that. **223 prod / 167 dev MLB rows carried another player's `mlbam_id`**, so of the 317
duplicate `mlbam_id` groups, **124 were two different people.** Running the dedupe would have
repointed 408,610 prop rows and 26,491 game logs onto the wrong players and then deleted the
originals. It was stopped by a `player_stats` UNIQUE constraint firing on 188 collisions — luck,
not the safety property this document claims.

Cause: Statcast's `player_name` is the **pitcher's** name on every pitch row, and the pre-`b03b9c9`
batter fallback took `player_name.iloc[0]` while `player_id` came correctly from `batter_id`. Right
id, stranger's name, no error. Full trace and the measured fingerprint in `docs/DATA-SPINE.md`
(2026-08-04 addendum).

**Repaired in v0.7.5** via `backend/repair_mlb_identity_names.py`, id-first — the published name for
each `mlbam_id`, nothing else written. Groups that are two different people: **124 → 0**.

### Dup status (verified 2026-08-04, supersedes the 2026-06-26 numbers above)
- **prod:** 317 duplicate `mlbam_id` groups, **0** of them split across different people.
  The dedupe is now genuinely identity-safe and has not yet been run.
- **dev:** 0 duplicate groups.

### What to carry forward
- **Before trusting any id-keyed merge, run `audit_league_stats.py` check `G/published-identity`
  for that league.** UNVERIFIED is not a pass — it means no publisher snapshot exists yet and the
  merge's safety property is unproven for that league. Today only MLB has one
  (`backend/data/published-identity-names.json`); NFL, NBA and NHL report UNVERIFIED.
- Generalising `dedupe_mlb.py` to a new league means generalising the identity snapshot **first**.
