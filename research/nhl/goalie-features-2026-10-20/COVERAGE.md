# NHL strict-lag goalie feature coverage

Phase 1 only: coverage and leakage audit. No model fitting, scoring, threshold
selection, betting simulation, or promotion-rule changes.

## Population and source

The SBR archive is joined to the official canonical game table by date and
unordered team pair, then keyed by canonical game_id. It contains 5,132
crosswalk games: 4,872 regular-season target games and 260 playoff games. The
CSV retains one row per crosswalk game_id. Playoff rows have null goalie fields
and target_coverage_status
playoff_uncovered_regular_season_goalie_logs_only. They are uncovered because
goalies_gamelogs contains regular-season game logs for these target seasons.
The 2022-23 SBR archive is a partial season slice, not full-season coverage;
the exact game count and date span are printed in the coverage block below.

The source is /root/nhl_database_2025-26-playoffs.duckdb, table goalies_gamelogs, filtered to
lower(situation)='all' and season <= 2022, read-only with one DuckDB thread and a 200 MB memory
limit. Source gameId, gameDate, season, and playerTeam are reconciled against
canonical game_id, game_date, season, home_team, and away_team. SBR crosswalk
logic is reused from the predecessor new-information audit. Historical
canonical PHX and goalie-source ARI codes are normalized to the Arizona franchise
key ARI; that alias is counted in the source reconciliation output.

## Feature definitions

- A starter is the unique goalie with maximum all-situation icetime in a
  completed regular-season team game. A tied maximum is absent and logged.
- starter_last is the starter from the team's latest source game dated before
  the target. A team's first regular-season game of each season has all features
  null. After that opening game, trailing histories may include same-season and
  earlier-season regular-season games, with a strict date lag and no later season.
- starter_games_trailing10 counts that goalie among the team's up-to-ten most
  recent prior regular-season games. Fewer than ten available games are tagged
  with the actual n.
- starter_gsax_trailing10 is the unweighted mean of per-start xGoals minus
  goals over that goalie's up-to-ten uniquely identified prior starts.
- starter_savepct_trailing10 is the unweighted mean of per-start
  (ongoal minus goals) divided by ongoal over the same up-to-ten prior starts.
  A missing or zero ongoal makes this feature absent.
- team_goalie_gsax_trailing10 is the unweighted mean of team-game goalie GSAx
  over up to ten prior team games, summing all goalies' all-situation xGoals
  minus goals within each team game first.
- starter_changed is 1/0 according to whether starters in the latest and
  second-latest prior team games differ. It is absent unless both are unique.
- Each feature has its own max_source_gameDate, n, and coverage string.
  Missing values remain null; no zero imputation, shrinkage, tuned constant,
  or fitted weight is used.

## SEASON COVERAGE and SBR crosswalk output

<pre>
SBR / CANONICAL CROSSWALK
target_rows=5132 unique_canonical_games=5132 unmatched_or_ambiguous=0 venue_order_mismatches=1
VENUE_ORDER_MISMATCH season=2019-20 date=2020-01-17 sbr_home=Pittsburgh sbr_away=Detroit canonical_home=DET canonical_away=PIT
SEASON COVERAGE
archive_rows=5132 canonical_game_ids=5132 regular_season_games=4872 playoff_games=260
season=2018-19 sbr_games=1358 canonical_matches=1358 regular_season_games=1271 playoff_games=87 date_span=2018-10-03..2019-06-12
season=2019-20 sbr_games=1082 canonical_matches=1082 regular_season_games=1082 playoff_games=0 date_span=2019-10-02..2020-03-11
season=2020-21 sbr_games=952 canonical_matches=952 regular_season_games=868 playoff_games=84 date_span=2021-01-13..2021-07-07
season=2021-22 sbr_games=1401 canonical_matches=1401 regular_season_games=1312 playoff_games=89 date_span=2021-10-12..2022-06-26
season=2022-23 sbr_games=339 canonical_matches=339 regular_season_games=339 playoff_games=0 date_span=2022-10-11..2022-11-27
</pre>

## Source reconciliation and starter coverage

<pre>
SOURCE_CANONICAL_RECONCILIATION all_situation_rows_season_le_2022=37981 unique_game_ids=17664 team_games=35327 team_alias_rows=487 canonical_team_alias=PHX->ARI canonical_id_date_season_team_mismatches=0 non_regular_season_source_games=0
SOURCE_STARTER_COVERAGE season=2018 source_team_games=2542 unique_starter_team_games=2542 ambiguous_starter_team_games=0
SOURCE_STARTER_COVERAGE season=2019 source_team_games=2163 unique_starter_team_games=2163 ambiguous_starter_team_games=0
SOURCE_STARTER_COVERAGE season=2020 source_team_games=1736 unique_starter_team_games=1736 ambiguous_starter_team_games=0
SOURCE_STARTER_COVERAGE season=2021 source_team_games=2624 unique_starter_team_games=2623 ambiguous_starter_team_games=1
SOURCE_STARTER_COVERAGE season=2022 source_team_games=2624 unique_starter_team_games=2624 ambiguous_starter_team_games=0
</pre>

## Feature coverage and absence reasons

Coverage counts by season use team-sides. Absence counts include both sides of
every archive row, including uncovered playoff rows. Reason strings are stored
per feature and side in the CSV.

<pre>
GOALIE FEATURE COVERAGE
target_rows=5132 unique_game_ids=5132 regular_season_target_games=4872 playoff_target_games_uncovered=260
coverage_unit=team_side; covered counts include partial windows tagged with actual n
season_label target_games regular_feature_games playoff_uncovered_games starter_last_covered_sides starter_games_trailing10_covered_sides starter_gsax_trailing10_covered_sides starter_savepct_trailing10_covered_sides team_goalie_gsax_trailing10_covered_sides starter_changed_covered_sides
2018-19 1358 1271 87 2511 2511 2511 2511 2511 2511
2019-20 1082 1082 0 2133 2133 2133 2133 2133 2133
2020-21 952 868 84 1705 1705 1705 1705 1705 1705
2021-22 1401 1312 89 2592 2592 2592 2592 2592 2591
2022-23 339 339 0 648 639 634 634 648 647
PARTIAL_TARGET_SEASON season=2022-23 archive_regular_games=339 date_span=2022-10-11..2022-11-27 full_regular_season=false
FIELD_ABSENCE_COUNTS (unit=team_side; denominator includes playoff sides)
field=starter_last total_sides=10264 populated=9589 absent=675 absent_reasons=first_team_game_of_season:155,playoff_target_uncovered:520
field=starter_games_trailing10 total_sides=10264 populated=9580 absent=684 absent_reasons=ambiguous_starter_in_trailing_team_games:9,first_team_game_of_season:155,playoff_target_uncovered:520
field=starter_gsax_trailing10 total_sides=10264 populated=9575 absent=689 absent_reasons=ambiguous_starter_tie_in_last10_start_window:14,first_team_game_of_season:155,playoff_target_uncovered:520
field=starter_savepct_trailing10 total_sides=10264 populated=9575 absent=689 absent_reasons=ambiguous_starter_tie_in_last10_start_window:14,first_team_game_of_season:155,playoff_target_uncovered:520
field=team_goalie_gsax_trailing10 total_sides=10264 populated=9589 absent=675 absent_reasons=first_team_game_of_season:155,playoff_target_uncovered:520
field=starter_changed total_sides=10264 populated=9587 absent=677 absent_reasons=ambiguous_starter_in_comparison_games:1,fewer_than_two_prior_team_games:1,first_team_game_of_season:155,playoff_target_uncovered:520
FIELD_PARTIAL_WINDOWS field=starter_games_trailing10 covered_partial_n=1_of_10:1,covered_partial_n=2_of_10:1,covered_partial_n=3_of_10:1,covered_partial_n=4_of_10:1,covered_partial_n=5_of_10:1,covered_partial_n=6_of_10:1,covered_partial_n=7_of_10:1,covered_partial_n=8_of_10:1,covered_partial_n=9_of_10:1
FIELD_PARTIAL_WINDOWS field=starter_gsax_trailing10 covered_partial_n=1_of_10:57,covered_partial_n=2_of_10:53,covered_partial_n=3_of_10:52,covered_partial_n=4_of_10:51,covered_partial_n=5_of_10:50,covered_partial_n=6_of_10:47,covered_partial_n=7_of_10:44,covered_partial_n=8_of_10:46,covered_partial_n=9_of_10:45
FIELD_PARTIAL_WINDOWS field=starter_savepct_trailing10 covered_partial_n=1_of_10:57,covered_partial_n=2_of_10:53,covered_partial_n=3_of_10:52,covered_partial_n=4_of_10:51,covered_partial_n=5_of_10:50,covered_partial_n=6_of_10:47,covered_partial_n=7_of_10:44,covered_partial_n=8_of_10:46,covered_partial_n=9_of_10:45
FIELD_PARTIAL_WINDOWS field=team_goalie_gsax_trailing10 covered_partial_n=1_of_10:1,covered_partial_n=2_of_10:1,covered_partial_n=3_of_10:1,covered_partial_n=4_of_10:1,covered_partial_n=5_of_10:1,covered_partial_n=6_of_10:1,covered_partial_n=7_of_10:1,covered_partial_n=8_of_10:1,covered_partial_n=9_of_10:1
</pre>

## Leak audit output (verbatim from the builder)

<pre>
LEAK AUDIT
feature_rows=5132 unique_game_ids=5132 regular_season_targets=4872 playoff_rows_null_and_flagged=260
read_only_all_situation_rows_season_le_2022=37981 source_game_ids=17664 source_team_games=35327
assertion=max_source_gameDate < target_gameDate for every non-null per-feature source date
checked_per_feature_source_dates=57534 violations=0 status=PASS
same_target_date_excluded=true future_season_source_excluded=true
</pre>

## Reproduction

<pre>
/root/lp-goalie-research/.venv/bin/python research/nhl/goalie-features-2026-10-20/build_goalie_features.py
</pre>
