# PR #30 correctness and editorial smoke report

As of 2026-11-01. This is a research-only audit against `/root/legendarypicks/backend/data/picks.dev.db`, opened with SQLite `mode=ro` and `PRAGMA query_only=ON`. The audit made zero network requests and zero database writes. It made no production changes, deployments, or service restarts.

## Closure summary

| Gate | Result | Evidence and remaining work |
|---|---|---|
| Fourth-down semantics | Partially corrected; publication gate remains closed | Conversion no longer uses `success`/EPA. Regression cases pass. The full local population still has 139 unresolved attempts and has not passed independent reconciliation. Candidate totals remain audit-only. |
| Drive outcomes | Open | Compared with Legendary Picks' existing overtime reconstruction. 146/150 terminal labels match; four do not. Regulation drives lack independent reconciliation. No drive facts are emitted. |
| TB–CAR scoring discrepancy | Open; withheld | A play-level trace was retained, but local result and score-snapshot fields cannot establish the missing points. No correction was inferred. |
| Editorial relevance | Partial; quality gate not met | Selection suppresses weak outliers and repeated categories, but the smoke still shows adjacent facts without a clear matchup connection. |
| Blinded smoke | Completed as an agent-only screen | 10 NFL and 10 NBA pairs, claim-by-claim local evidence checks. This is not independent human grading and does not include the production DeepSeek generator. |
| Production adoption | Not approved | No adoption decision is supported by this research. |

## Fourth-down conversion semantics

The old conversion calculation treated `nfl_pbp.success == 1` as a first-down conversion. That field is an EPA success indicator, so the revised classifier does not read it. It evaluates down and distance, yards gained, series and possession transitions, touchdowns, penalties and turnovers. A defensive penalty is not counted as a conversion unless the sequence confirms the offense retained/progressed its series.

The regression cases exercise the semantic failures directly. The old EPA-based implementation would fail the first two cases; the new classifier passes them:

| Regression case | Expected result | Current result |
|---|---|---|
| Positive EPA, but the offense fails to convert | Failed | Pass |
| Conversion with non-positive EPA | Converted | Pass |
| Defensive penalty | Count only when the sequence confirms the first down | Pass |
| Goal-to-go conversion | Use the next series transition, not yardage-to-go alone | Pass |
| Touchdown on fourth down | Converted | Pass |
| No terminal or subsequent sequence evidence | Unresolved and withheld | Pass |

Across all local NFL play-by-play, the audit found **9,763** live fourth-down run/pass attempts in **3,794** games: **4,995 candidate conversions, 4,629 candidate failures, and 139 unresolved**. These are reconciliation counts only; no conversion-rate facts are published. The unresolved cases are 54 turnover/next-possession conflicts, 15 first-down/next-possession conflicts, 57 first-down/next-series conflicts, and 13 with insufficient terminal or sequence evidence. `PUBLISH_NFL_FOURTH_DOWN_FACTS` remains false.

The full-population scan has not been reconciled against an independent attempt outcome source, and the 139 unresolved attempts prevent a complete sequence reconciliation. Therefore this gate is **not closed**, despite the corrected semantics and passing regression cases.

## Drive outcomes and scoring evidence

The database contains 756,043 NFL plays across 4,283 games. `nfl_pbp` has drive and series labels, but no `fixed_drive_result`, per-play score snapshots, or separate drive-reconstruction table. The extractor now treats drive terminal labels as candidates and emits no drive or scoring summary facts pending reconciliation.

I compared local drive groupings with the existing Legendary Picks overtime reconstruction in `scripts/nfl_sequence/build_overtime_drives.py`, regenerating its 150-record fixture from local checksummed play-by-play parquet files. This is an independent implementation over the same underlying play-by-play, not an independent publisher or data source.

- 150/150 fixture drive keys and selected reconstructed fields matched the regenerated fixture.
- Local PBP offense and next-possession identities matched the fixture after shared team-code normalization: 150/150 each.
- Local last `series_result` matched the independent terminal label on 146/150 drives.
- Winner direction after observed overtime tries matched the scheduled final winner in 63/63 overtime games.
- `team_game_results` contained two-team score rows for 14/63 overtime games: all 14 matched schedule scores; 49 had no two-team rows; zero comparable games mismatched.
- This sample covers overtime only. General regulation drive outcomes remain unverified and quarantined.

The four terminal-label differences are:

| Game / drive | Local last `series_result` | Reconstructed outcome |
|---|---|---|
| `2022_01_IND_HOU`, 27 | First down | End of half |
| `2022_01_PIT_CIN`, 26 | First down | Missed field goal |
| `2022_10_DAL_GB`, 25 | QB kneel | Field goal |
| `2023_15_MIN_CIN`, 22 | QB kneel | Field goal |

For the 2026 Week 7 TB–CAR game, the audit retained all 156 local plays and inspected 20 drive groups. Candidate terminal counts were 6 offensive touchdown, 1 defensive touchdown, 2 made-field-goal, 3 punt, 2 turnover, 3 turnover-on-downs, and 3 unknown; one drive transition conflicted. These classifications are not independently reconciled, and none produced a narrative fact.

The scheduled score is Tampa Bay 43, Carolina 13. The local play trace contains 16 candidate scoring-related plays (7 touchdown plays, 2 field-goal plays, and 7 extra-point plays), but lacks `field_goal_result`, `extra_point_result`, `two_point_conv_result`, `posteam_score_post`, and `defteam_score_post`. `team_game_results` has no rows for this game. The prior reconstruction was two points short; the retained local evidence cannot identify the exact cause, so scoring claims remain withheld and no correction is hardcoded.

## Turnover reconciliation and data coverage

Turnover summaries are emitted only when PBP giveaways match both teams' captured `team_game_stats.turnovers` values. Across 4,026 games with PBP giveaways, the audit found 232 exact two-team matches, 18 mismatches, and 3,776 games without the required two-team snapshot/value pair. The 18 mismatches and 3,776 unavailable comparisons are withheld. The local team-stats snapshots cover 285 NFL games (570 rows); the values are not available for most of the PBP population.

Relevant local coverage:

- NFL: 756,043 PBP rows / 4,283 games; 294,359 player-log rows (294,264 with player IDs); 60,647 snap-count rows; 9,270 `team_game_results` rows.
- NFL PBP fields missing for verified scoring/drive outcomes: field-goal, extra-point and two-point results; per-play post-scores; and `fixed_drive_result`. PBP records have no per-play capture timestamp.
- NBA: 2,466 team-game-stat rows / 1,233 games; 34,974 player-log rows; 1,322 completed `nba_sportsdataverse_games` rows.
- No complete NBA play-by-play table was found locally. `scoring_plays` has 2,490 scoring-event rows across only 5 games, not full possession/event timelines.

The five previously excluded NBA timelines cannot be reclassified reproducibly from retained artifacts. The earlier run saved only `NarrativeDataError`, not its message or normalized timeline; local data has no full PBP or scoring-play rows for these games. Each does have two team-stat rows, which cannot distinguish missing plays, scoring corrections, overtime handling, or source ordering:

| ESPN event | SportsDataVerse game | Date | Matchup and final score |
|---|---|---|---|
| `401810016` | `0022500161` | 2025-11-03 | MEM 106, DET 114 |
| `401810188` | `0022500333` | 2025-12-04 | PHI 99, GS 98 |
| `401810257` | `0022500402` | 2025-12-22 | CLE 139, CHA 132 |
| `401809242` | `0022500013` | 2025-12-25 | DEN 142, MIN 138 |
| `401810585` | `0022500730` | 2026-02-04 | SA 116, OKC 106 |

All five retain the class `NarrativeDataError`, with a null exception message, and remain unclassified. No external timeline request was made.

## Editorial relevance and paired smoke

The candidate selector now requires recent verified facts, suppresses PPR fantasy-point anomalies and low-value player outliers, limits repeated categories, and uses full team names and stat labels. The generated preview still can place a team trend beside an unrelated player outlier without explaining why the combination matters.

Example NFL pair (same matchup, cutoff, and retrieved evidence):

> The Indianapolis Colts have lost three straight games, most recently falling to the Minnesota Vikings on Oct 25.
>
> The Indianapolis Colts have lost three straight games, most recently falling to the Minnesota Vikings on Oct 25. Javonte Williams had 25 carries for the Dallas Cowboys against the Philadelphia Eagles on Oct 26; the prior 10-game average was 13.9 carries.

Example NBA candidate:

> The Boston Celtics have won four straight games, most recently beating the Chicago Bulls on Oct 30. Franz Wagner recorded 11 assists for the Orlando Magic against the Toronto Raptors on Oct 30; the prior 10-game average was 3.6 assists.

The output is more precise and grammatical than the earlier examples, but these facts do not yet explain a tactical or causal connection to the upcoming matchup. The relevance gate therefore remains open.

The 20 anonymous pairs compare **event facts only** against **event facts plus eligible player-form facts**, using the same complete local evidence manifest and cutoff for each pair. After the final team-identity change, all 40 candidate outputs were recomputed from the saved evidence through the current renderer: 20/20 pairs matched exactly. The production DeepSeek generator was not called: external requests were prohibited, and historical cached previews were excluded because their complete evidence manifests are unavailable.

An agent-only blinded screening (not independent human grading) produced these 1–5 averages:

| League / variant | Accuracy | Relevance | Specificity | Readability |
|---|---:|---:|---:|---:|
| NFL event facts only | 5.0 | 3.0 | 3.0 | 4.0 |
| NFL plus player form | 5.0 | 3.3 | 3.9 | 4.0 |
| NBA event facts only | 5.0 | 3.0 | 3.0 | 4.0 |
| NBA plus player form | 5.0 | 4.0 | 4.0 | 3.7 |

The 59 rendered claims all matched their supporting local rows and rendered facts; all 59 were available by the shared as-of cutoff and occurred before target kickoff; the numeric screen found zero unsupported numeric tokens. This confirms local-source consistency for the sampled claims, not independent truth or writing quality. Relevance averaged 3.0 for event-only and 3.65 for combined; readability averaged 4.0 and 3.85 respectively. The smoke is purposive, not held out. Human ratings: **0**.

## Regression verification

`python -m unittest test_research_narrative_event_knowledge test_narrative_event_knowledge` — **38 tests passed**. The suite covers the fourth-down regression cases above, quarantined facts, local read-only database access with external requests patched to fail if called, as-of safety, and shared team-code aliases. `python -m py_compile narrative_event_knowledge.py research_narrative_event_knowledge.py` and `git diff --check` also passed.

The fourth-down cases now pass against the corrected classifier; the old EPA-based behavior would fail the positive-EPA/no-conversion and conversion/non-positive-EPA cases. No failing test remains in the current focused suite. Data reconciliation failures described above are intentionally unresolved states, not test failures that were waived.

## Exact remaining closure criteria

1. Reconcile all 9,763 fourth-down outcomes with zero unresolved or contradictory sequence classifications, then independently validate the population before enabling conversion facts.
2. Resolve the four overtime terminal-label mismatches and validate terminal outcomes across regulation and overtime against independent evidence before emitting any drive counts.
3. Recover sufficient local evidence to explain the TB–CAR two-point difference and classify each excluded NBA timeline from retained normalized event data and its exact validation error; otherwise those records stay excluded.
4. Improve event selection so paired facts explain a relevant matchup development, then rerun the 10+10 blind smoke. The current agent-only screen is not a human evaluation.
5. Obtain at least 30 paired NFL and 30 paired NBA blind human ratings with claim-by-claim evidence review. Compare a freshly generated existing-generator baseline only when its authorized evidence can be captured under the same cutoff; do not use the cached previews with incomplete manifests.

Until these gates close, the research branch remains isolated from Legendary Picks story generation.
