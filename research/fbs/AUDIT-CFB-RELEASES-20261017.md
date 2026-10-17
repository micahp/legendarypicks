# SportsDataverse `cfb_*` release inventory - 2026-10-17

Enumerated from the GitHub releases API, pages 1-4, 382 releases total.

`cfb_*` releases: **25**. The user asked for every one of them.

The distinction that matters for the FBS modeling track is **raw vs scored**. A raw release is one row per observed event and can be re-derived. A scored release has already had a model applied -- EPA, ratings, projections -- and its values are the publisher's model output, not observations. Using a scored feature as if it were an observation double-counts the publisher's model.

## 1. Inventory

| release | kind | grain | parquet files | seasons | parquet MB | published |
|---|---|---|---|---|---|---|
| `cfb_crosswalk` | reference | team | 29 | 2013-2026 | 2.0 | 2026-06-13 |
| `cfb_defense_vs_position` | scored | team | 13 | 2014-2026 | 0.6 | 2026-10-04 |
| `cfb_fpi_weekly` | scored | team | 22 | 2005-2026 | 4.0 | 2026-08-01 |
| `cfb_groups` | reference | team | 161 | 1869-2026 | 1.1 | 2026-09-27 |
| `cfb_league_averages` | scored | team | 23 | 2004-2026 | 0.6 | 2026-09-26 |
| `cfb_matchup_features` | scored | team | 13 | 2014-2026 | 4.3 | 2026-09-15 |
| `cfb_matchup_line` | scored | team | 12 | 2015-2026 | 7.8 | 2026-09-15 |
| `cfb_metric_curves` | scored | player | 23 | 2004-2026 | 1.8 | 2026-10-01 |
| `cfb_model_artifacts` | scored | team | 2 | - | 0.0 | 2026-08-27 |
| `cfb_paper_index_games` | scored | team | 23 | 2004-2026 | 1.7 | 2026-10-04 |
| `cfb_poll_analytics` | scored | team | 23 | 2004-2026 | 0.2 | 2026-10-01 |
| `cfb_poll_week_summary` | scored | team | 23 | 2004-2026 | 0.1 | 2026-10-01 |
| `cfb_ratings` | scored | team | 23 | 2004-2026 | 0.4 | 2026-07-16 |
| `cfb_ratings_weekly` | scored | team | 23 | 2004-2026 | 3.1 | 2026-08-01 |
| `cfb_recruiting_proj` | scored | team | 10 | 2016-2025 | 0.1 | 2026-07-17 |
| `cfb_recruits` | raw | player | 25 | 2002-2026 | 1.6 | 2026-08-06 |
| `cfb_returning_production` | scored | team | 23 | 2004-2026 | 0.2 | 2026-08-06 |
| `cfb_rolling_windows` | scored | player | 23 | 2004-2026 | 7.2 | 2026-09-27 |
| `cfb_schedules` | reference | team | 26 | 2001-2026 | 1.6 | 2026-08-27 |
| `cfb_team_info` | reference | team | 26 | 2001-2026 | 3.4 | 2026-08-27 |
| `cfb_team_opponent_splits` | scored | team | 23 | 2004-2026 | 0.7 | 2026-09-30 |
| `cfb_team_portal` | reference | team | 12 | 2015-2026 | 0.1 | 2026-10-02 |
| `cfb_team_summaries_weekly` | scored | team | 23 | 2004-2026 | 73.0 | 2026-08-01 |
| `cfb_team_talent` | scored | team | 22 | 2005-2026 | 0.2 | 2026-08-06 |
| `cfbfastR_cfb_pbp` | raw | player | 13 | 2014-2026 | 1091.9 | 2025-08-24 |

## 2. What each release is for

First sentence of the publisher's own description, verbatim.

- **`cfb_crosswalk`** -- College football identity crosswalks**.
- **`cfb_defense_vs_position`** -- College Football defense vs position: ONE ROW PER DEFENSE PER POSITION GROUP per season (`season`, `team_id`, `position_group` in QB / RB / WR / TE) with the EPA per play, success rate and explosive rate that defense allowed to the group, plus QB dropbacks and sack rate, RB carries and yards per carry, WR / TE targets and yards per target (`sportsdataverse.defense_vs_position`). Every dropback is the QB's; a carry goes to the rusher's roster group and a target to the receiver's, so a completion counts for QB and for its receiver's group. Regular season + postseason, every game in the pbp (FBS and FCS defenses; `division` says which). `qualified` = 3 or more games. PERCENTILES: each `<metric>_pct` is among FBS qualifiers within the season's position group, 0-100, and HIGHER IS ALWAYS THE BETTER DEFENSE -- allowing less ranks higher, except `sack_rate_allowed` (sacks per dropback the defense got), where more ranks higher. Non-qualifiers and non-FBS defenses carry null percentiles. WR / TE CAVEAT: in 2024 ESPN names a receiver on only about 69% of throws (few incompletions, no interceptions), so the WR and TE rates are on targets naming a receiver, mostly completions, and read high; `unattributed_target_share` on the WR and TE rows is the share of throws against that defense with no receiver named (FBS median 0.12 in 2014, 0.33 in 2024). Nothing is imputed. SPAN: 2014+ only -- earlier rosters carry no positions.
- **`cfb_fpi_weekly`** -- College football models and reference tables** — ESPN's Football Power Index snapshotted weekly.
- **`cfb_groups`** -- College football conference, division and subdivision reference**.
- **`cfb_league_averages`** -- College football models and reference tables** — season baselines: the mean, median, standard deviation and n of every published team and player metric, per level, over the same qualified population the ranks and percentiles use.
- **`cfb_matchup_features`** -- College football models and reference tables**.
- **`cfb_matchup_line`** -- College football models and reference tables**.
- **`cfb_metric_curves`** -- College football models and reference tables** — rate curves along a continuous axis: FG% by kick distance, completion% and EPA by air-yards bucket, 4th-down conversion by yards to go and success by down x distance, each bucket with attempts, successes, rate and EPA per attempt, for the league, every team and every credited player, one asset per season (FG curves 2004+, air-yards curves 2025+).
- **`cfb_model_artifacts`** -- College football models and reference tables** — serialized model artifacts (the fitted objects themselves, not observations).
- **`cfb_paper_index_games`** -- College Football Paper Index per game: ONE ROW PER TEAM PER SCORED GAME (`game_id`, `team_id`, both Int64) with `paper_share`, the team's deserved-win probability from eight performance margins (success rate, explosive rate, explosiveness, scoring-opportunity conversion, points per opportunity, starting field position, havoc, turnovers), `opp_share` (the two sum to 1), `won`, and the eight `<margin>_margin` columns, team minus opponent (`sportsdataverse.paper_index.paper_index_games`, Game on Paper's Paper Index). A game is scored when it is completed, has a winner and both sides ran at least 20 scrimmage snaps; regular season and postseason, FBS and FCS. Summed over a season the shares are the `deserved_wins` on espn_cfb_team_summaries / cfb_team_summaries_weekly, and wins minus that sum is `luck_wins`. `luck_z` there divides that gap by its binomial standard deviation; it reads like a z-score over a full season and is NOT on a normal scale below about 8 games (an early weekly snapshot can show +6). IN-SAMPLE LABEL: `paper_index_span` is `train` for 2016-2023 (the season's shares were part of the weight fit, so they are in-sample), `holdout` for 2024-2025 (scored out of sample at fit time, though not fully clean: the EP model behind the EPA, success and explosiveness inputs was trained on seasons that include them) and `out_of_span` for every other season (never seen by the fit, never evaluated). NOT A FEATURE: the shares are fitted on who won, so they describe results and must not enter a predictive model.
- **`cfb_poll_analytics`** -- College football models and reference tables** — weekly AP, Coaches and CFP poll history with each team's rank, previous rank, move, entry and exit flags, weeks ranked, points and first-place votes, one asset per season (2004+; every run refetches the season from ESPN).
- **`cfb_poll_week_summary`** -- College football models and reference tables** — per-poll week summaries: volatility (population sd of rank change with unranked = 26), chaos (sum of absolute rank changes), entries and exits, one asset per season (2004+).
- **`cfb_ratings`** -- College football models and reference tables** — team ratings.
- **`cfb_ratings_weekly`** -- College football models and reference tables** — team ratings snapshotted weekly.
- **`cfb_recruiting_proj`** -- College football models and reference tables** — recruiting projections.
- **`cfb_recruits`** -- College football models and reference tables** — recruiting classes, one row per recruit.
- **`cfb_returning_production`** -- College football models and reference tables** — returning production estimates.
- **`cfb_rolling_windows`** -- College football models and reference tables** — rolling event-count windows: each player's and team's form over its last N events vs the previous N, the season start and its career baseline, with delta ranks and sample sizes, one asset per season.
- **`cfb_schedules`** -- College football models and reference tables** — the game schedule, one row per game.
- **`cfb_team_info`** -- College football models and reference tables** — team reference information (conference, division, venue, colors).
- **`cfb_team_opponent_splits`** -- College football models and reference tables** — by-opponent team splits: one row per team per game with the opponent, EPA per play, success rate, points for and against and plays; college covers every game (FCS opponents and bowls included), NFL the regular season only, where game_id is empty before 2002 and nflverse_game_id identifies every game.
- **`cfb_team_portal`** -- cfb_team_portal (CFB dataset, Python-built).
- **`cfb_team_summaries_weekly`** -- College football models and reference tables** — team season summaries snapshotted weekly.
- **`cfb_team_talent`** -- College football models and reference tables** — 247Sports team talent composite.
- **`cfbfastR_cfb_pbp`** -- cfbfastR CFBD-sourced college football** — play-by-play, one row per play.

## 3. The raw observation releases

These are the ones a backtest is built on. Everything else is derived from them or from a reference table.

- **`cfb_recruits`** -- 25 parquet files, 1.6 MB. College football models and reference tables** — recruiting classes, one row per recruit.
- **`cfbfastR_cfb_pbp`** -- 13 parquet files, 1091.9 MB. cfbfastR CFBD-sourced college football** — play-by-play, one row per play.

## 4. The two player-level scored releases

Most `cfb_*` releases are team-level. These two carry a player/athlete id at row grain, and they join to our prop players on ESPN athlete id. They are the only scored releases usable directly in a player-prop model without re-deriving the underlying events.

| release | grain | seasons | parquet MB |
|---|---|---|---|
| cfb_rolling_windows | player | 2004-2026 | 7.2 |
| cfb_metric_curves | player | 2004-2026 | 1.8 |

## 5. The as-of contract

`cfb_team_summaries_weekly` and `cfb_ratings_weekly` carry a `through_week` column. The contract is inclusive:

> `through_week == W` includes games PLAYED in week W. To project week W, use the `through_week == W - 1` row.

The publisher verified this empirically (2024, delta between consecutive snapshots vs games actually played): **97.0% consistent with the inclusive reading, 58.7% with the exclusive one.** Filtering `through_week == W` and predicting week W leaks that week's results.

Also: the current season holds only the weeks played so far, and a build written early carries later weeks as **copies of the last real week**. Check for duplicated snapshots before using them.

## 6. Non-`cfb_` releases that are still college football

The prefix filter excludes a large part of the ecosystem. Measured in the same sweep: **68 more college releases** under `espn_cfb_*` and `ncaa_mfb_*`. The `cfb_` prefix is a naming convention, not a complete list of college football data, and several of the excluded releases are player-level.

Player-level among the excluded:

- `ncaa_mfb_player_stats` -- player season stats
- `espn_cfb_usage_players`, `espn_cfb_adv_player_usage` -- player usage
- `espn_cfb_play_participants` -- per-play player attribution
- `espn_cfb_adv_defensive_players` -- player-level defensive

Full list:

| release | parquet files | published |
|---|---|---|
| espn_cfb_adv_defensive | 23 | 2026-06-04 |
| espn_cfb_adv_defensive_players | 23 | 2026-06-24 |
| espn_cfb_adv_drive_scripting | 23 | 2026-09-15 |
| espn_cfb_adv_drives | 23 | 2026-06-04 |
| espn_cfb_adv_passing | 23 | 2026-06-04 |
| espn_cfb_adv_player_usage | 23 | 2026-09-15 |
| espn_cfb_adv_position_group_tackles | 13 | 2026-09-15 |
| espn_cfb_adv_position_group_usage | 13 | 2026-09-15 |
| espn_cfb_adv_receiving | 23 | 2026-06-04 |
| espn_cfb_adv_rushing | 23 | 2026-06-04 |
| espn_cfb_adv_situational | 23 | 2026-06-04 |
| espn_cfb_adv_specialists | 23 | 2026-06-24 |
| espn_cfb_adv_st_blocks | 19 | 2026-09-15 |
| espn_cfb_adv_st_kickers | 23 | 2026-09-15 |
| espn_cfb_adv_st_punters | 23 | 2026-09-15 |
| espn_cfb_adv_st_returners | 23 | 2026-09-15 |
| espn_cfb_adv_st_team | 23 | 2026-09-15 |
| espn_cfb_adv_tackles | 13 | 2026-09-15 |
| espn_cfb_adv_team | 23 | 2026-06-04 |
| espn_cfb_adv_team_gamelog | 23 | 2026-08-01 |
| espn_cfb_adv_team_usage | 23 | 2026-09-15 |
| espn_cfb_adv_turnover | 23 | 2026-06-04 |
| espn_cfb_betting | 23 | 2026-06-04 |
| espn_cfb_coach_careers | 1 | 2026-09-15 |
| espn_cfb_coach_tendencies | 23 | 2026-09-15 |
| espn_cfb_drives | 23 | 2026-06-04 |
| espn_cfb_game_rosters | 23 | 2026-06-04 |
| espn_cfb_injuries | 1 | 2026-06-04 |
| espn_cfb_linescores | 23 | 2026-06-04 |
| espn_cfb_model_artifacts | 0 | 2026-06-17 |
| espn_cfb_model_pbp | 59 | 2026-06-17 |
| espn_cfb_passing | 23 | 2026-06-13 |
| espn_cfb_pbp | 23 | 2023-05-04 |
| espn_cfb_percentiles | 23 | 2026-06-13 |
| espn_cfb_play_participants | 13 | 2026-06-04 |
| espn_cfb_player_box | 23 | 2026-06-04 |
| espn_cfb_power_index | 22 | 2026-06-04 |
| espn_cfb_qa | 23 | 2026-09-19 |
| espn_cfb_receiving | 23 | 2026-06-13 |
| espn_cfb_rosters | 24 | 2023-05-04 |
| espn_cfb_rushing | 23 | 2026-06-13 |
| espn_cfb_schedules | 23 | 2023-05-04 |
| espn_cfb_team_box | 23 | 2026-06-04 |
| espn_cfb_team_summaries | 23 | 2026-06-13 |
| espn_cfb_team_tendencies | 23 | 2026-09-15 |
| espn_cfb_teams | 26 | 2026-08-27 |
| espn_cfb_usage_drive_scripting | 23 | 2026-09-15 |
| espn_cfb_usage_players | 23 | 2026-09-15 |
| espn_cfb_usage_position_group_tackles | 13 | 2026-09-15 |
| espn_cfb_usage_position_groups | 13 | 2026-09-15 |
| espn_cfb_usage_st_blocks | 19 | 2026-09-15 |
| espn_cfb_usage_st_kickers | 23 | 2026-09-15 |
| espn_cfb_usage_st_punters | 23 | 2026-09-15 |
| espn_cfb_usage_st_returners | 23 | 2026-09-15 |
| espn_cfb_usage_st_team | 23 | 2026-09-15 |
| espn_cfb_usage_tackles | 13 | 2026-09-15 |
| espn_cfb_usage_teams | 23 | 2026-09-15 |
| ncaa_mfb_drives | 14 | 2026-08-24 |
| ncaa_mfb_linescore | 14 | 2026-08-24 |
| ncaa_mfb_officials | 14 | 2026-08-24 |
| ncaa_mfb_pbp | 14 | 2026-08-24 |
| ncaa_mfb_pbp_cfbfastr | 14 | 2026-08-24 |
| ncaa_mfb_player_stats | 14 | 2026-08-24 |
| ncaa_mfb_qa | 14 | 2026-09-19 |
| ncaa_mfb_rosters | 14 | 2026-08-24 |
| ncaa_mfb_schedule | 14 | 2026-08-24 |
| ncaa_mfb_team_stats | 14 | 2026-08-24 |
| ncaa_mfb_teams | 14 | 2026-08-24 |

## 7. Leak guards found in the release notes

Two releases carry explicit warnings that would silently inflate a backtest if ignored. Both are quoted because the wording is the guard.

### `cfb_paper_index_games` is not a feature

> `paper_index_span` is `train` for 2016-2023 (the season's shares were part of the weight fit, so they are in-sample), `holdout` for 2024-2025 ... and `out_of_span` for every other season. **NOT A FEATURE**: the shares are fitted on who won, so they describe results and must not enter a predictive model.

This is a target leaked into a feature. `paper_share` is a deserved-win probability fitted on the outcome, so any model given it as an input is being told the answer. The `paper_index_span` column exists specifically so a backtest can exclude the in-sample seasons.

### `cfb_defense_vs_position` has an unattributed-target caveat

> in 2024 ESPN names a receiver on only about 69% of throws (few incompletions, no interceptions), so the WR and TE rates are on targets naming a receiver, mostly completions, and read high; `unattributed_target_share` ... is the share of throws against that defense with no receiver named (FBS median 0.12 in 2014, 0.33 in 2024). Nothing is imputed.

The unattributed share roughly tripled between 2014 and 2024. Any receiving model that uses these WR/TE rates across seasons is comparing rates measured on different populations, and the drift is in the direction that makes later seasons look better. The column is published so the drift can be measured; it is not corrected.

The same caveat is the reason the plan excludes receiving markets until target and reception attribution quality is confirmed: this is the measurement that would justify that exclusion.
