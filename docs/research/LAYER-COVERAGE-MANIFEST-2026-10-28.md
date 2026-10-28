# Layer coverage manifest, 2026-10-28

Purpose: each model layer uses the longest reliable history its own sources support. No layer is shrunk to FTN's window.
Holdout: 2026 is sealed. Every count below was taken from seasons 2025 and earlier. No 2026 row was read to make this table.
Source: `data/picks.dev.db` (read-only) for the database tables, and `data/raw/` for the nflverse files.

## Layer-by-layer coverage

| Layer | Source | Verified window | Granularity | What is missing | Status |
|---|---|---|---|---|---|
| Situational play-calling | `nfl_pbp` | 2010 to 2025, 16 seasons, 44,991 to 47,651 plays per season | play | exact score and kick results are not in the table (see score gap) | observation builder built and tested, 2010 to 2025 |
| Play outcomes and game state | `nfl_pbp` | 2010 to 2025 | play | the same score gap affects score-dependent outcomes | not built |
| Player usage and production | `player_game_logs` (`league='nfl'`) | 2010 to 2025, 17,341 to 19,400 rows per season | player-game | identity crosswalk not audited here | not built |
| Snap counts | `nfl_hist_snap_counts` | 2013 to 2025, 324,612 rows | player-game | `nfl_snap_counts` (current feed) covers 2024 to 2025 only | not built |
| Formation and personnel | `nfl_hist_participation` | 2016 to 2025, 478,989 rows | play | pre-2016 has no participation source in the database | not built |
| FTN charting | `data/raw/ftn_charting_{2022..2025}.csv` | 2022 to 2025 | play | not in the database; no pre-2022 source | not built; loader must treat it as optional |
| NGS separation | `player_game_logs.stats` key `separation` | 2024 and 2025 only: 1,253 of 18,961 rows (2024) and 1,213 of 19,400 rows (2025) | player-game aggregate | about 6% coverage; no play-level join | audit of other NGS metrics not done |
| Depth charts (historical) | `nfl_hist_depth_charts` | regular season 2010 to 2024; no 2025 rows | player-week | publication time unverified | used by the 2024 exploratory snapshot only |
| Depth charts (current feed) | `nfl_depth_chart` | 2026 only | player | none for history | 2026 path, not used here |
| Tracking | not verified here | per the earlier inventory, selected 2022 to 2023 cohorts | play | research only | not part of the statistical engine |

Play-type counts in `nfl_pbp`, 2010 to 2025: pass 306,235; run 217,642; no_play 69,282; kickoff 42,599; punt 36,351; null 21,702;
extra_point 19,624; field_goal 16,240; qb_kneel 6,333; qb_spike 1,109.

## Play-calling observations built this turn (2010 to 2025, `playcall_observations.py`)

Per-season intent counts from the builder (dropbacks include sacks and recorded scrambles; kneels and spikes are kept
separate):

- Run and dropback intents are present in every season, about 12,000 to 13,400 runs and 18,900 to 20,800 dropbacks per season.
- Fourth-down go-for-it decisions run about 430 to 990 per season; punts and field goals on fourth down run about 1,900 to 2,500 and
  860 to 1,020 per season.
- Unknown intents (null play type) are about 1,300 to 1,400 per season, roughly 3%. They are kept as `unknown`, not guessed.
- No-play rows (mostly penalties) are about 4,000 to 4,700 per season and are kept as `no_play`.

Full per-season counts are in the scratchpad file `playcall-coverage-2010-2025.json`.

## Score gap and the path to close it

`nfl_pbp` has no score or kick-result columns. So the builder returns `score_differential = None` with
`score_status = 'unavailable_in_pbp'`. Nothing is estimated.

The raw nflverse file `data/raw/pbp_2022.csv.gz` (372 columns) has the pre-play score fields:
`posteam_score`, `defteam_score`, `score_differential`, plus `field_goal_result`, `extra_point_result`,
`two_point_conv_result`, `total_home_score`, `total_away_score`. The `_post` columns are the post-play values.

Path: join those pre-play fields to `nfl_pbp` on game and play id for 2022 to 2025 (the same files exist for 2023 to 2025 locally).
The join must be checked by row count and by the posteam/defteam match before use. 2010 to 2021 raw files are not local. Adding them
needs a source fetch, which needs a decision.

## Registry (play-calling layer)

Each feature carries: feature_name, source, earliest_season, latest_season, observed_granularity, missingness,
cutoff_eligibility, rule_regime, provenance, model_layer.

| feature_name | source | earliest | latest | granularity | missingness | cutoff_eligibility | rule_regime | model_layer |
|---|---|---|---|---|---|---|---|---|
| intent (run, dropback, kneel, spike, two_point, special_teams, no_play, unknown) | nfl_pbp | 2010 | 2025 | play | null play_type becomes `unknown` | game week before target | NFL regular season | situational_play_calling |
| fourth_down_decision | nfl_pbp | 2010 | 2025 | play | only on down 4 | game week before target | NFL regular season | situational_play_calling |
| down, ydstogo, yardline_100, game_seconds_remaining, qtr | nfl_pbp | 2010 | 2025 | play | down/yardline null on non-scrimmage plays; clock null on a few rows per season | game week before target | NFL regular season | situational_play_calling |
| seconds_in_quarter, two_minute_window, overtime | derived from clock and qtr | 2010 | 2025 | play | null where clock or qtr is null | game week before target | regulation clock; overtime flagged | situational_play_calling |
| goal_to_go_derived | derived from yardline_100 | 2010 | 2025 | play | null where yardline is null | game week before target | derived definition (distance to goal at most 10) | situational_play_calling |
| score_differential | not in nfl_pbp | none | none | none | not available | blocked until joined | n/a | situational_play_calling |

## Fallback hierarchy (design, not yet implemented)

1. Team evidence in the current season before the cutoff, for the same down, distance and score band.
2. Team evidence across the history window, with recency weights tested on chronological development data.
3. League prior for the era, from the full PBP window, shrunk toward (2).

A missing advanced feature (FTN, participation, NGS) triggers the next level for that feature only. It never removes the play.

## Decisions needed

1. Training window for the situational layer: 2010 to 2025 (this manifest) or 2022 to 2025 (the earlier instruction for the
   frozen model). The layer window can differ from the frozen training window, but this needs to be written down.
2. Whether to join the 2022 to 2025 pre-play score fields from the raw nflverse files (local, no fetch needed).
3. Whether to fetch 2010 to 2021 nflverse raw files for score fields. Needed for score-dependent filters before 2022.
4. Whether the kick, blocked-kick, overtime and safety tables (pinned 2022 to 2025, and containing 2025 outcomes) need
   cutoff-safe versions before any historical claim.
