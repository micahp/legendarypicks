# merge_nba_identities.py — ported from `codex/nba-v1`, tests green

Written 2026-07-29 on a branch that never merged and was 174 commits behind dev by
the time it was found. Ported 2026-08-04 **because the defect it repairs is still
live**, and because it root-caused, five days earlier, the same NBA problem this
week's audit rediscovered from the symptom end.

## What it fixes

hoopR's `athlete_id` **is** ESPN's athlete id. Legacy imports wrote that value to
`players.nba_id`; current roster and game-log jobs write it to `players.espn_id`.
When the two land on different `players.id` rows, one real player is split — his
historical stats belong to one person and his current game logs to another, and no
join will ever reunite them.

Measured on prod 2026-08-04: **269 split athletes**, and of 1,063 NBA rows,
**zero carry both ids**. The two populations are completely disjoint.

## What it does, verified against a copy of prod

```
--plan   NBA identity bridge: 269 split pairs; moved rows={'player_stats': 261}
--apply  same, after taking its own verified backup
```

Effect on `audit_league_stats.py`, measured before and after on that copy:

| check | before | after |
|---|---|---|
| `F/identity-crosswalk` | FAIL — 269 split | **PASS** |
| `D/leaders-reach-logs` | 53 of 525 (10%) | **314 of 525 (60%)** |

It keeps the ESPN row, moves only stable-ID-backed dependencies off the hoopR row,
and requires the operator to state the counts up front (`--expect-pairs 269
--expect-moved player_stats=261`) — it refuses if reality disagrees. The row count
falls 1,063 → 794 because 269 duplicate people stop existing.

## What it does NOT fix

- **NBA leaders still serve 2023.** This reunites the identities; it does not
  publish 2026 season stats. That is `publish_nba_season_identities.py` (also on
  `codex/nba-v1`, not yet ported) plus a rollup over the 23,749 NBA 2026 game-log
  rows we already hold.
- **`players.position` still holds two vocabularies** — `G/F/C` beside
  `PG/SG/SF/PF`. `C/vocabulary[position]` stays red.

## Running it

```bash
cd backend
PYTHONPATH=. venv/bin/python scripts/merge_nba_identities.py --db <copy> --plan
```

**Not yet applied to prod.** Plan against a copy first and confirm the counts match
before anyone passes `--apply`.
