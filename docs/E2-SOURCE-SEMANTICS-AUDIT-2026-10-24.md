# E2 source-semantics audit (2026-10-24)

Every source column the E2 engine or the rules matrix reads, what it is taken to mean, the evidence for that, and the verdict.
Verdicts: **verified** (checked against data in this audit), **measured** (counted, meaning not independently confirmed),
**assumed** (not checked here), **contradicted** (the data disagrees with the assumption; the engine handles it as stated).

Data: the dev table `nfl_pbp` (window: season 2022-2025, week <= 18), and the nflverse parquet for the same seasons
(`/root/nflverse-raw`, SHA-256 in `SHA256SUMS`). The rebuilt tables are `docs/fixtures/e2/kick_results_2022_2025.csv` and
`docs/fixtures/e2/play_extras_2022_2025.csv`, each with a manifest.

## Kick outcomes

| column | meaning taken | evidence | verdict |
| --- | --- | --- | --- |
| `extra_point_result` | `good` made, `failed` missed, `blocked` neither | 2022-2025 window: good 4643, failed 178, blocked 38, empty 11 | verified |
| `success` (extra point rows) | equal to `good` | `success` = 1 on all 4643 good rows; 0 on failed and blocked; one empty row has `success` 1 | verified for result rows; **contradicted** as a conversion flag for blocked and empty rows, so it is not used |
| `two_point_conv_result` | `success` converted, `failure` not | success 240, failure 269, empty 0 in the window | verified |
| `success` (two-point rows) | equal to the conversion field | equal on all 509 rows | verified (so the two-point rate is the same either way) |
| `field_goal_result` | `made`, `missed`, `blocked` for the kick | window: made 3664, missed 556, blocked 86 | verified |
| `series_result` (field goal rows) | a label of the series, not the kick | cross-tab: `Field goal` = made 3664; `Missed field goal` = missed 556 + blocked 78; `QB kneel` = made 18 (contradicted); `Opp touchdown` = blocked 8; `Turnover` = missed 1 | verified; contradicted for the 18 kneel rows, so the table uses `field_goal_result` with a series-label check |

Consequences in the engine: extra-point rate 96.3% (4643 / 4821), excluding 38 blocked and 11 empty; two-point rate 47.2%
(240 / 509); field-goal table from `field_goal_result` with 86 blocked and 19 non-kick rows excluded, make rate 86.8%.

## Field position and possession

| column | meaning taken | evidence | verdict |
| --- | --- | --- | --- |
| kickoff `posteam` / `defteam` | `posteam` is the receiving team, `defteam` the kicking team | measured earlier on 10,999 kickoffs; 10,037 have a clean receiving snap | measured |
| `yardline_100` at a kick | the spot the kick was taken from, offense-relative | used as the kick spot for the bucket and the missed-kick rule | assumed |
| missed field goal spot (Rule 11-4-2) | receiving team at the kick spot, or its own 20 when the spot is inside its 20 | **the rule is cited from the review; the rulebook text is not in the repository** | assumed (cited, not verified) |
| punt receiving spot | the next snap by the receiving team, `yardline_100` | kickoff-style convention, measured on the sample | measured |

## Clock, timeouts, penalties and plays

| column | meaning taken | evidence | verdict |
| --- | --- | --- | --- |
| `game_seconds_remaining` | clock runoff = difference between consecutive snaps in one quarter | used for E1 runoffs; clamped to 0 when negative (594 of 7016 plays in the E1 census) | measured |
| `timeout` and `timeout_team` | a timeout called on that play, by the team named (an abbreviation) | 2022-2025 flag count 8,355 (2109, 2040, 2111, 2095 by season); `timeout_team` is a team abbreviation | measured |
| timeouts per half | three per team per half, reset at halftime | the rule; the observed flags are charged to the side the sampled play names | assumed (the rule); measured (the flags) |
| `penalty` | a penalty on the play | E1 excludes penalty plays from its pool (2,666 excluded) | verified (excluded in code) |
| `qb_scramble` | a scramble | E1 excludes it (3,883 excluded) | verified (excluded in code) |
| two-minute warning | a stoppage | not identifiable in the table; a stoppage shows only in the runoff | assumed (guarded as unmodelled) |

## Participants and outcomes

| column | meaning taken | evidence | verdict |
| --- | --- | --- | --- |
| `passer_player_id`, `rusher_player_id`, `receiver_player_id` | the players on the observed play | used only as sampled participants, labelled `sampled_observed_play`; the null pattern was not audited in this pass | assumed (null pattern) |
| `air_yards` | yards the ball travelled in the air | null on 30,912 of the plays in 2024 (non-pass plays and some passes) | measured |
| yards after catch (derived as `receiving_yards - air_yards`) | yards after the catch | agrees with the publisher's `yards_after_catch` on 11,625 of 11,629 completions in 2024 (99.97%); 4 differ by 1-3 yards | measured; the derived value is labelled `derived` |
| `out_of_bounds` | the play ended out of bounds | flag count in the window 16,269 | measured |
| `yards_gained` | the play's gain | used as the sampled outcome | assumed |
| touchdown credit | yards capped at the goal line | the observed yards describe a different spot; capping is the engine's rule | assumed (a modelling choice) |

## Scores and identity

| column | meaning taken | evidence | verdict |
| --- | --- | --- | --- |
| `home_team`, `away_team` | the real sides | the engine uses authored labels `A` and `B`; `home` is `A` by convention | contradicted for any real-team reading: the record is an authored hypothetical, so real identities are not claimed |
| `total_home_score`, `total_away_score` | running score | in the raw parquet, not in the dev table; the engine computes its own score | measured (not used by the engine) |
| observed points per game | the sum of scoring events | 43.8 per game in the window (E3 derivation, from touchdowns, extra points, field goals) | measured (E3) |

## Drive and window

| column | meaning taken | evidence | verdict |
| --- | --- | --- | --- |
| `drive` | a possession, numbered within a game | 2163 window rows have a null drive and are excluded | measured |
| `series_result` (on the last play of a drive) | the drive's outcome | the next-play check on field goals agrees (3071 made field goals are followed by a kickoff by the other team; 464 misses by a run, pass or kneel by the other team); five rows disagree | measured |
| `season_type`, `week` | regular season, weeks 1-18 | the dev table has no `season_type` column; it holds weeks 1-18 only (no row above week 18 in 2022-2025), so `week <= 18` is the regular season. The parquet kick build filters `season_type` = `REG` | verified for the dev table (measured 2026-10-24); the `REG` filter is verified in the kick build |

## Identifiers, flags and play type (measured 2026-10-24)

Window: 2022-2025, week <= 18, the dev table read-only: 188,282 rows.

| column | meaning taken | measured | verdict |
| --- | --- | --- | --- |
| `game_id`, `play_id` | identify one play | 0 duplicate pairs; 0 nulls | verified |
| `game_date` | the game's date | 0 nulls | verified |
| `qtr` | quarter; 5 is overtime | quarters 1-4: 41,528 / 52,565 / 40,915 / 52,060; overtime (5): 1,214 | **contradicted for regulation.** The E1 pool keys on down, distance and field, not quarter, so it takes overtime rows (1,214 of them: 470 pass, 348 run, 149 no-play, 78 kickoff, and others). The engine never reaches overtime, but its pool includes these outcomes. Disclosed here, not corrected: removing them would change the frozen survey. |
| `ydstogo` | yards to go | 0 nulls | verified |
| `play_type` | the play's kind | run 57,116; pass 77,022; punt 8,442; field_goal 4,325; kickoff 10,999; extra_point 4,870; qb_kneel 1,689; qb_spike 278; no_play 18,013; null 5,528 | measured. E1 takes run, pass, punt and field_goal only; kneels, spikes, kickoffs and extra points are outside its vocabulary |
| `interception` | a pass was intercepted | 1,615, all on pass plays | verified |
| `sack` | the passer was sacked | 5,308, all on pass plays | verified |
| `complete_pass` | a pass was completed | 46,259 of 77,022 pass plays; no completion on any other play type | verified |
| `fumble_lost` | the offense lost a fumble | 1,112: pass 599, run 378, punt 93, kickoff 41, field goal 1. E1 classifies a punt before it checks fumbles, so a punt fumble is a punt | measured |
| `two_point_attempt` | a two-point try | 509: pass 360, run 142, no-play 7. E1 excludes these | verified |
| `qb_scramble` | the QB scrambled | 4,380. E1 excludes these | verified |
| `penalty` | a penalty was on the play | 13,095. E1 excludes these | verified |
| `touchdown` | the play scored | 5,399 | measured |

## Not verified

- The rulebook text for Rule 11-4-2 (missed-kick spot) and for two-minute stoppages. The spot rule is implemented as cited.
- The null pattern of the participant ids.
- Whether the observed timeout flag marks the play before or after the stoppage. The engine applies it to the sampled play it sits on.
- Any relationship between the observed `series_result` and the simulated drive terminals, beyond the next-play check.
