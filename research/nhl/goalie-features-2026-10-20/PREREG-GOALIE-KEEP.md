# NHL goalie keep-rule pre-registration

**Date:** 2026-10-20
**Status:** Approved by Micah for research on 2026-10-20. This is a protocol, not an experiment or a result.

This document preregisters the population, feature inputs, market comparison, walk-forward evaluation, and keep/discard rule for the Phase 1 strict-lag goalie features. No model fitting, prediction scoring, ROI calculation, AUC calculation, or threshold evaluation is performed or reported here. The coverage figures below are copied from the committed Phase 1 artifact. The complete-case game-drop count is a row count of the committed `goalie_features.csv`, using the rule stated below.

## Registered population

The source population is the exact **4,872 regular-season target games** in `research/nhl/goalie-features-2026-10-20/goalie_features.csv`, joined to canonical game IDs by the Phase 1 SBR crosswalk. Playoff rows are outside the target population. Season coverage and feature-side coverage below are quoted from `COVERAGE.md`:

```text
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
```

**Null-side rule:** exclude a game if any one of the six registered feature values is null on either its home or away side. No imputation or partial-feature fallback is allowed. Counting the home- and away-side feature values in the committed CSV, **107 of the 4,872 regular-season games** meet this exclusion rule. The Phase 1 coverage block separately records **155** `first_team_game_of_season` absent team-sides across the archive; this is a side count, not the number of games excluded.

**Opening-price and final completeness:** Across the **5,132** games in the committed SBR archive, **5,131** have both sides' `ml_open` present. **One** game lacks an opening pair: `2020020316` (2021-02-25, Columbus–Chicago). **One** game lacks a final score: `2020020371` (2021-03-04, Vancouver–Toronto; the home final is absent). Both games have all six registered features non-null on both sides. The resulting evaluable regular-season denominator is **4,763 games**: complete features, an opening quote pair, and a final score. These archive-wide quote/result counts and game IDs were recomputed by joining the committed SBR archive to the goalie CSV through the Phase 1 date/team crosswalk. Any missing quote pair or result must be reported as a data exclusion before scoring, not treated as a pass or loss. Every game in the evaluable denominator remains in the selection-rate denominator whether the rule bets or passes.

## Frozen feature set

The model input set is frozen to these six Phase 1 fields, using the existing home- and away-side CSV columns. Definitions are verbatim from `COVERAGE.md`:

- A starter is the unique goalie with maximum all-situation icetime in a completed regular-season team game. A tied maximum is absent and logged.
- starter_last is the starter from the team's latest source game dated before the target. A team's first regular-season game of each season has all features null. After that opening game, trailing histories may include same-season and earlier-season regular-season games, with a strict date lag and no later season.
- starter_games_trailing10 counts that goalie among the team's up-to-ten most recent prior regular-season games. Fewer than ten available games are tagged with the actual n.
- starter_gsax_trailing10 is the unweighted mean of per-start xGoals minus goals over that goalie's up-to-ten uniquely identified prior starts.
- starter_savepct_trailing10 is the unweighted mean of per-start (ongoal minus goals) divided by ongoal over the same up-to-ten prior starts. A missing or zero ongoal makes this feature absent.
- team_goalie_gsax_trailing10 is the unweighted mean of team-game goalie GSAx over up to ten prior team games, summing all goalies' all-situation xGoals minus goals within each team game first.
- starter_changed is 1/0 according to whether starters in the latest and second-latest prior team games differ. It is absent unless both are unique.

Each feature retains its Phase 1 value and its own coverage metadata. No new derivations, re-scaling, interactions, zero imputation, shrinkage, or fitted feature weights may be introduced under this registration. Adding or substituting any feature later voids this pre-registration and requires a new signed registration before fitting. The learner, categorical handling, and fitting parameters must be frozen in a separate model specification before any fitting; they may not be selected by inspecting an outer evaluation season.

## Primary market comparison

The primary control is the **no-vig opening moneyline probability on the same games**, following the opening-price primary comparison in `research/nhl/ml-selectivity-2026-10-20`. Convert each archived American opening quote to decimal odds `d`; its implied probability is `q = 1 / d`. Normalize the two sides: `p_market,side = q_side / (q_home + q_away)`. Compare the model and this market probability on identical games using Brier score and log loss; report the paired Brier difference as model minus market.

For the betting comparison, calculate break-even from the actual selected-side decimal quote: `p_break_even = 1 / d`. A selection must have positive model expected value at that quote (`p_model,side × d − 1 > 0`) as well as clear its registered model-edge and minimum-price cutoffs. A win returns `d − 1` units on a one-unit stake; a loss returns `−1` unit. The no-vig market control follows the selectivity artifact: it selects a side only when that side's no-vig probability clears its quoted break-even probability; otherwise it passes. Any archived underround pairs remain in the primary opening-price data and are identified separately in reporting.

Opening and closing quotes are not interchangeable. This registration uses opening quotes as the primary historical-price comparison. The archive has no intraday execution timestamp, so reported prices cannot establish an executable fill.

## Walk-forward evaluation

- Use season-blocked forward evaluation. The **2018-19** data may train the **2019-20** evaluation; each later evaluation season may use only strictly earlier seasons for model fitting, calibration, preprocessing, and any selection among the registered rules. No target-season or future-season outcomes may influence that season's forecast or rule.
- The archive supports **four evaluation season blocks**: 2019-20, 2020-21, 2021-22, and the partial 2022-23 slice. **Three blocks are complete** and one is partial. A season-clustered percentile interval over three to four blocks is coarse by construction.
- The candidate cutoffs below are fixed proposals, not values to optimize continuously. For each evaluation season after the initial fold, select among candidates using only earlier-season out-of-fold results. Select the candidate with the greatest paired net units per eligible game versus the no-vig market control; ties go to the higher edge cutoff, then the higher minimum price. If no candidate has at least the registered prior-sample minimum, use the strictest registered rule. For the initial evaluation season, use that same strictest rule because there are no earlier out-of-fold evaluation results.
- Every eligible evaluation game stays in the selection denominator. A pass contributes zero units. Report bets, eligible games, and selection rate for each season and in aggregate; report all exclusions and their reasons before metrics.
- Report model and no-vig market Brier and log loss on the same games, realized one-unit ROI at actual opening decimal odds, and paired net units per eligible game against the market-control policy. Compute uncertainty with season-clustered percentile intervals, resampling whole season blocks, using the interval convention in the standalone selectivity report.
- Report the 2022-23 archive slice as partial and separate from complete seasons. Do not describe it as a full-season holdout or allow its short date span to stand in for a full season.

## Proposed candidate-rule grid

These are the exact cutoffs proposed for Micah's approval. On a game, calculate each side's model edge as `p_model,side − p_market,side`; at most one side can be selected. The candidate rule must choose a side that clears all three gates: model edge at or above the cutoff, quoted decimal odds at or above the minimum price, and positive expected value at the quoted price. The minimum prior-sample column controls whether a candidate can be selected from prior out-of-fold results. The final verdict also requires the stated minimum count of out-of-fold bets.

| Proposal | Minimum model edge | Minimum quoted decimal odds | Minimum prior out-of-fold bets to be eligible for rule selection | Minimum aggregate out-of-fold bets for a conclusive verdict |
| --- | ---: | ---: | ---: | ---: |
| A | 0.01 | 1.50 | 200 | 200 |
| B | 0.01 | 1.80 | 200 | 200 |
| C | 0.02 | 1.50 | 200 | 200 |
| D | 0.02 | 1.80 | 200 | 200 |

No other cutoff, price band, or candidate may be searched under this registration. The 200-bet floor is a preregistered decision rule, not an observed result.

## Predeclared stopping decision

Let ROI be realized net units divided by selected bets. Let the paired policy delta be the goalie rule's net units minus the no-vig market control's net units, divided by all eligible games. Let `ΔBrier` be goalie-model Brier minus no-vig market Brier on the same games.

- **Adopt the keep rule** only if the aggregate out-of-fold sample contains at least 200 bets, the season-clustered interval lower bound for ROI is above zero, the lower bound for paired policy delta is above zero, and the upper bound for `ΔBrier` is below zero.
- **Discard the keep rule** if the aggregate has at least 200 bets and any one of these outcomes is clear in the adverse direction: the ROI interval upper bound is below zero, the paired policy-delta interval upper bound is below zero, or the `ΔBrier` interval lower bound is above zero.
- **Call the result inconclusive** if there are fewer than 200 aggregate out-of-fold bets, or if neither the adoption nor discard condition is met. Do not relax a cutoff to escape an inconclusive result.

No fitting, scoring, ROI, AUC, rule selection, or frozen-artifact change may run downstream until this document is signed.

## Known limits

- The archive has **260 playoff games uncovered** because Phase 1 goalie logs cover regular-season targets only.
- The **2022-23** archive is a **339-game partial slice**, dated **2022-10-11 through 2022-11-27**.
- Only **four evaluation season blocks** are available: 2019-20, 2020-21, 2021-22, and partial 2022-23; **three are complete**. Season-clustered intervals over three to four blocks are weak and coarse evidence. If both reported intervals span zero, that is not proof of no effect; a single positive season is not evidence of an edge.
- One starter team-game is ambiguous: `2021021307`, ANA, 2022-04-29.
- The first team-game sides of each season are null by design: **155 team-sides** in the Phase 1 absence count.
- `goalies_gamelogs` identifies the last **actual** starter, not the announced starter; a late scratch is invisible.
- Phase 1's source is historical and finite. No claim is made here about current seasons or announced goalie availability.

## Sign-off

APPROVED BY MICAH: 2026-10-20
