# NHL Goalie Data Audit — 2026-10-18

Research branch `research/nhl-goalie-adjustment-2026-10-18` (fresh worktree off `dev` @ `f6ccd943`).
Audited before any model code, per build-order step 2 requirements.

## Headline finding

**Located, shot-level data exists on this host.** The local MoneyPuck-derived `shots` table
(2,079,359 rows, seasons 2007–08 through 2025–26) carries per-shot coordinates
(`xCord`/`yCord` plus arena-adjusted variants), `shotDistance`, `shotAngle` (+adjusted
variants), shot type, rebound/rush flags, `shotOnEmptyNet`, and — critically —
`goalieIdForShot`/`goalieNameForShot`, which identifies the netminder who faced each shot.
This means "shot difficulty" can retain its full meaning (a per-shot xG-style difficulty
estimate conditioned on location/angle/context), not a degraded aggregate proxy.

A **pre-puck-drop confirmed-starter signal does not exist in any local table.** The only
starter flag found is `goalies_playoff_boxscores.starter`, which is only populated for 2025
postseason box scores (164 True / 164 False) and is by construction a post-hoc result — it is
useless for forecasting and is labelled as such. Unless a live pre-game lineup feed is wired
in, the expected-starter adjustment can only use a probabilistic/predicted starter, which is
what this research will build and timestamp.

## Goalie-season and goalie-game sources on this host

All in `/root/nhl_database_2025-26-playoffs.duckdb` (~1.2 GB, last modified 2026-10-13):

| Table | Rows | Seasons | Granularity |
|---|---:|---|---|
| `goalies_seasons` | 8,510 | 2008–2025 | Aggregate per-season per-situation |
| `goalies_gamelogs` | 231,540 | 2008–2025 | Per-game per-situation aggregate |
| `goalies_playoff_seasons` | 125 | 2025 | Aggregate per-season (playoffs) |
| `goalies_playoff_boxscores` | 328 | 2025 | Per-game, includes `starter` flag |
| `goalies_playoff_shot_metrics` | 174 | 2025 | Per-game GSAx summary (playoffs) |
| `shots` | 2,079,359 | 2007–2025 | **Shot-level**, located, goalie-attributed |
| `skaters_gamelogs` | — | 2008–2025 | Per-game skater aggregates (not goalie) |

`goalies_gamelogs` and `goalies_seasons` are MoneyPuck-style situation aggregates: they carry
`xGoals`, `goals`, danger-zone splits (`lowDangerShots` etc.), icetime, and rebound/freeze
metrics, but no per-shot breakdown and no coordinate fields. They are aggregate, not shot-level.
Shot-level work must go through `shots`, which joins to goalies via `goalieIdForShot` and to
games via `game_id`.

Coverage check: `goalies_gamelogs` spans seasons 2008–2025 (18 seasons), matching
`goalies_seasons`. `shots` covers one extra earlier season (2007) plus all of 2008–2025.

## What the current model uses as its goalie assumption

The prospective 2026–27 pipeline (`research/nhl/prospective-2026-27/`) freezes three
candidates — `B3_elo`, `B5_xg_poisson`, `B7_elo_xg_poisson`. None references a goalie: there
is no `goalie` or `starter` string anywhere in `run_pipeline.py`, and the frozen feature hash
(`pregame_features_sha256`) is built from schedule, Elo, and rolling xG only. So the de-facto
assumption is a **league-average goalie with no adjustment** — which is precisely G1 in the
build-order step 2 spec.

## Gaps that shape the G2 candidate

1. **No pre-game starter feed.** The brief names Daily Faceoff as the source, but nothing on
   this host fetches or stores lineup projections. G2 must therefore estimate the expected
   starter statistically (e.g., from last-game-start pattern and rest) and treat confirmation
   as a separate, timestamped forecast update — matching the brief's requirement to record
   both pre- and post-confirmation forecasts.
2. **GSAx itself is not precomputed.** `goalies_playoff_shot_metrics.GSAx` covers only the
   2025 playoffs (174 rows). For regular-season work, GSAx must be derived from
   `shots.xGoal` summed per goalie/game minus actual `goals` — feasible since both live in
   `shots`.
3. **The main app backend** (`/root/legendarypicks/backend/`) has no goalie ingestion beyond a
   static `goalie/summary` season-stats route (per `audit_field_utilization.py`: "NHL no goalie
   source at all"). That source is season-aggregate only and contributes nothing shot-level.

## Verdict

Shot-level located data is sufficient to build shot difficulty and chronological regressed
GSAx. The missing piece is a real pre-game starter signal, which caps G2's incremental value
and must be recorded as a limitation. Proceeding to pre-registration under that stated limit.
