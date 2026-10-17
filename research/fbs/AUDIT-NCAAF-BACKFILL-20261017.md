# NCAAF backfill opportunity - 2026-10-17

Measured read-only against the dev database and the SportsDataverse
`ncaa_mfb_player_stats` release. Nothing was written.

## The problem

The stored CFBD log job stopped on **2026-10-04**. Every prop fixture after that
date has no stored log row to join to, so those props cannot be graded against
anything.

The job cannot be re-run through the CFBD API. Measured 2026-10-17:

```
GET /games?year=2026  ->  HTTP 429  {"message":"Monthly call quota exceeded."}
```

The shared key in `~/.hermes/.env` exhausted its monthly quota on 2026-10-16.

## The fix

`ncaa_mfb_player_stats` is the stats.ncaa.org player-statistics release: one row
per player per game per category, with `espn_game_id` -- the same join key our
logs use (`player_game_logs.game_no`).

Measured 2026-10-17:

| measure | value |
|---|---|
| rows, 2026 | 103,705 |
| distinct games, 2026 | 793 |
| seasons covered | 2013-2026 |
| parquet size, 2026 | 0.87 MB |
| categories | defense 42,615 / other 24,791 / receiving 13,850 / rushing 12,262 / passing 4,353 / punt_returns 2,951 / kicking 2,883 |
| join key | `espn_game_id` (matches `prop_games.espn_event_id`) |

**It joins to us.** Of our 323 linked prop fixtures, the release covers 259
(80.2%). Of our 1,263 NCAAF prop players, 1,216 appear in it (96.3% by name).

## What backfilling buys

| measure | value |
|---|---|
| props currently joined to logs | 45,888 |
| props on a fixture NOT in our logs | 30,538 |
| of those, present in the release | **16,438** |

So backfilling adds roughly **36% more joinable props**.

The coverage gap is concentrated in October:

| month | fixtures | already in logs |
|---|---:|---:|
| 2026-08 | 8 | 8 |
| 2026-09 | 202 | 201 |
| 2026-10 | 113 | **0** |

October is entirely uncovered by our logs. The release covers it.

## Why this is the right source

- **No API key.** It is a public Parquet file on a public URL.
- **It is the same shape as what we already ingest.** One row per player-game
  with a JSON-ish stat set, so the existing log loader can consume it with a
  source label rather than a new pipeline.
- **It is player-attributed and per-game**, which is what a prop model needs.
  The `cfb_*` releases are team-level or end-of-season and cannot do this job.

## Two caveats that must be handled

1. **The release is per-category, not per-player-game.** One player-game
   appears as up to ten rows. Measured: **103,705 rows over 57,931 distinct
   player-games** (median 1 row, max 10). A naive load writes 1.79x too many
   rows. A loader must aggregate by player-game before writing.
2. **Coverage is 80.2% of fixtures, not 100%.** 64 of our 323 linked fixtures
   are absent. The release's own note says ESPN game ids "reach roughly 88% of
   games", so this is expected and is a coverage floor, not a defect. Props on
   the missing fixtures stay unjoinable and must be reported as such rather
   than filled with zeroes.

## The naming trap

The release is `ncaa_mfb_player_stats`, not `cfb_*`. It was found only because
the `cfb_` prefix sweep was extended to `espn_cfb_*` and `ncaa_mfb_*` -- the
prefix filter the user asked for would not have found it. See
`AUDIT-CFB-RELEASES-20261017.md` section 6.

## Proposed next step

Backfill `player_game_logs` for NCAAF from this release for the games after
2026-10-04, on a **copy** of the dev database first, then verify the join
count against the 16,438 figure above before touching the live table.

This is a database write and is not performed by this audit.
