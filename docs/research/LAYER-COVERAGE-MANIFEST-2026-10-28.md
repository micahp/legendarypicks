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

## Pre-play scores (joined, 2010 to 2025)

`nfl_pbp` has no score columns. The play-calling builder now joins exact pre-play scores from the nflverse raw play-by-play for
the same season, on (game_id, play_id). Each raw file is checked against a pinned SHA-256 before it is read.

Sources and pins:
- 2022 to 2025: `data/raw/pbp_{season}.csv.gz` in the research repo. Pins are in its build manifest.
- 2010 to 2021: retrieved 2026-10-28 from `https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv.gz`
  into `/root/lp-snapshots/nfl-pbp-2010-2021/`, with `MANIFEST.json` holding each file's SHA-256. All 12 files carry the full set of
  score fields.

Validation (`validate_pre_play_scores.py`, reports in the scratchpad). For each season 2010 to 2025, regular season weeks 1 to 18:

| Check | Result |
|---|---|
| Join coverage, both directions | 100% in every season: every raw play matches a DB play, and every DB play matches a raw play |
| Shared fields (team, quarter, down, distance, field, clock, play type) | no mismatches after the LA/LAR and WAS/WSH code normalisation |
| score_differential equals posteam minus defteam | 0 inconsistent rows in every season |
| Continuity: pre-play score equals the previous play's post-play score for the same team (plays ordered by quarter, clock, then play id; 567 untimed rows excluded) | 121 exceptions across 2010 to 2025, out of about 670,000 checked transitions. 43 are a scoring play with no row in the file (point after, field goal, touchdown, two-point or safety). 3 repeat the state from before the previous play. 75 are unexplained: 33 change both sides at once (mostly 2011, 2016 and 2020) and 42 change one side. |
| Final scores against nfl_schedule (clock ordering) | 4,174 of 4,175 games match. One 2010 game disagrees by 6 points on both sides and is kept as is. |
| Pre-play totals that decrease within a game | Computed in file order by the first validator; about 80% are on no-play rows. Superseded for the clock-ordered trace. |

Earlier counts in this table (0 to 91 continuity mismatches a season, 1 to 3 final-score disagreements a season) were computed
in play-id order. About 30 games per season, in 2022 to 2025 alone 37 games in 2022 and 16 in 2025, have play ids out of game order,
so that order made the checks compare states that never followed one another. The figures above replace them.
Play ids run backwards in game time in 77 games in 2010, 37 in 2022 and 16 in 2025.

Every remaining exception is listed in `docs/research/SCORE-EXCEPTIONS-REMAINING-2010-2025.csv`: 121 continuity rows (with
the expected and actual scores and the previous play), 567 untimed rows, and 1 final-score mismatch. The 121 continuity
rows are also the flags the play-call observations carry (`docs/fixtures/score-exceptions/`).

Decisions the validation supports:
- No-play rows drop their pre-play scores (`excluded_no_play_row`), since their totals are not pre-play state.
- Unknown-intent plays with no raw score stay `raw_score_missing`. In 2025 all 561 are unknown intent.
- Plays with no raw row stay `unmatched_in_raw`. None occur in the 2010 to 2025 window.
- Coverage at the join: 2012 has 41,100 scored plays, 4,194 excluded no-play rows and 535 missing scores. 2025 has 41,353,
  4,538 and 561.
- The residual continuity and final-score mismatches are small and are left in the data, not corrected. They are reported here.

## Registry (play-calling layer)

Each feature carries: feature_name, source, earliest_season, latest_season, observed_granularity, missingness,
cutoff_eligibility, rule_regime, provenance, model_layer.

| feature_name | source | earliest | latest | granularity | missingness | cutoff_eligibility | rule_regime | model_layer |
|---|---|---|---|---|---|---|---|---|
| intent (run, dropback, kneel, spike, two_point, special_teams, no_play, unknown) | nfl_pbp | 2010 | 2025 | play | null play_type becomes `unknown` | game week before target | NFL regular season | situational_play_calling |
| fourth_down_decision | nfl_pbp | 2010 | 2025 | play | only on down 4 | game week before target | NFL regular season | situational_play_calling |
| down, ydstogo, yardline_100, game_seconds_remaining, qtr | nfl_pbp | 2010 | 2025 | play | down/yardline null on non-scrimmage plays; clock null on a few rows per season | game week before target | NFL regular season | situational_play_calling |
| seconds_in_quarter, two_minute_window, overtime | derived from clock and qtr | 2010 | 2025 | play | null where clock or qtr is null | game week before target | regulation clock; overtime flagged | situational_play_calling |
| goal_to_go | nflverse raw `goal_to_go` flag, joined on (game_id, play_id) | 2010 | 2025 | play | null where the play has no raw row | game week before target | publisher flag; not inferred from distance | situational_play_calling |
| red_zone | derived from yardline_100 (at most 20) | 2010 | 2025 | play | null where yardline is null | game week before target | derived definition | situational_play_calling |
| posteam_score_pre, defteam_score_pre, score_differential | nflverse raw pre-play score fields, joined on (game_id, play_id) | 2010 | 2025 | play | `excluded_no_play_row` (penalty and timeout rows), `raw_score_missing`, `unmatched_in_raw`, and `flagged_continuity_exception` (121 plays, see the score exceptions section) | game week before target | NFL regular season; pre-play state only | situational_play_calling |

## Fallback hierarchy (design, not yet implemented)

1. Team evidence in the current season before the cutoff, for the same down, distance and score band.
2. Team evidence across the history window, with recency weights tested on chronological development data.
3. League prior for the era, from the full PBP window, shrunk toward (2).

A missing advanced feature (FTN, participation, NGS) triggers the next level for that feature only. It never removes the play.

## Readiness of the conditional play-calling model

Ready:
- Play facts and intents for 2010 to 2025 (run, dropback, sack, scramble, kneel, spike, two-point, fourth-down choices), with
  unknown intent kept as unknown.
- Exact pre-play scores, quarter, clock and field position, joined on (game_id, play_id) from pinned sources, validated as above.
- Cutoff and holdout guards on the observation builder.

Not ready (the model is not built and must not be frozen yet):
- The hierarchical probability model: team, down, distance, score, clock and field interactions are not fitted.
- Era effects, recency weighting and team-specific tendencies are not evaluated.
- Score-by-clock interactions are not built or tested. The score is in the data, but no model uses it yet.
- No evaluation against the league prior or the 24-cell decision model on chronological development data.
- Coaches and quarterbacks are not in the observation rows; coaching and QB changes are not modelled.
- QB and player decisions are not connected, so statistics are still assigned after the play.

This is research infrastructure. Nothing here is adopted, promoted or integrated.

## Decisions needed

1. Training window for the situational layer: 2010 to 2025 (this manifest) or 2022 to 2025 (the earlier instruction for the
   frozen model). The layer window can differ from the frozen training window, but this needs to be written down.
2. Resolved: pre-play scores are joined for 2010 to 2025 from pinned raw sources (see above).
3. Resolved: the 2010 to 2021 raw files were fetched and pinned.
4. Resolved in code: the kick, blocked-kick, overtime, safety, try and participant sources have cutoff paths, and the leakage tests
   and the S0 regression pass. The guard is lifted. The cutoff-safe versions are computed per call; the pinned originals are unchanged.
