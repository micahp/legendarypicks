# Dallas at Philadelphia: 10,000-game statistical batch

**Run date:** October 26, 2026
**Game:** Dallas Cowboys at Philadelphia Eagles
**Game ID:** 2026_07_DAL_PHI
**Result type:** Hypothetical seeded statistical simulation

## Executive summary

The batch generated one outcome for every seed from 1 through 10,000 and retained every outcome, including ties, guarded transitions, and simulation errors.

| Measure | Result |
| --- | ---: |
| Requested seeds | 10,000 |
| Valid complete, untied games | 7,993 (79.93%) |
| Games reaching the end of regulation | 8,327 |
| Tied at regulation end | 334 |
| Blocked before regulation ended | 1,614 |
| Simulation errors | 59 |

The score and win distributions use only the 7,993 valid complete games. They are conditional on passing the validity gate. The 20.07% of runs outside that sample are material coverage loss, so treat these figures as exploratory model outputs.

## Simulation results

Home is Philadelphia; away is Dallas.

| Metric | Simulation, valid games | Frozen v1 baseline |
| --- | ---: | ---: |
| Philadelphia mean points | 20.4146 | 23.1840 |
| Dallas mean points | 20.4886 | 23.1421 |
| Philadelphia minus Dallas | -0.0739 | +0.0419 |
| Combined points | 40.9032 | 46.3261 |
| Philadelphia win probability | 49.87% | 50.13% |

In the valid-game sample, Dallas won 4,007 games and Philadelphia won 3,986. The batch distribution's 10th–90th percentile ranges were 10–32 points for each team and 27–56 combined points.

The most frequent exact score was Philadelphia 23, Dallas 13, occurring 52 times (0.65% of valid games). This is the modal score, separate from the projected mean.

Compared with the v1 fit, the event simulation's valid-game mean was 2.7694 points lower for Philadelphia and 2.6535 lower for Dallas, for a 5.4229-point lower combined total. The v1 baseline was fit from 93 prior games available by the frozen cutoff. No market spread or total was supplied, so the batch does not report cover or over/under probabilities.

## Completion coverage and failure counts

All 10,000 seeds are present in the aggregate. Status counts were 7,993 complete regulation games, 1,948 blocked outcomes, and 59 simulation errors. The blocked status includes 334 overtime cases; 1,614 were blocked before regulation ended.

| Guarded transition | Count |
| --- | ---: |
| Safety free kick not modeled | 758 |
| Unresolved blocked field goal, unclassified outcome | 393 |
| Overtime not modeled | 334 |
| Blocked field goal expired with unresolved spot | 173 |
| Timeout team unresolved | 160 |
| Blocked field goal with guarded penalty, fumble, or review | 45 |
| Thin field-goal sample at 50+ yards | 32 |
| Blocked field goal, period expired | 27 |
| Blocked punt with guarded penalty, fumble, or review | 26 |

The 59 simulation errors were retained as failed seed outcomes:

| Error | Count |
| --- | ---: |
| Receiving-team return endpoint outside the field of play | 23 |
| Kicking-team recovery outside the field of play | 12 |
| Player/team offensive touchdown totals did not reconcile, away | 11 |
| Player/team offensive touchdown totals did not reconcile, home | 9 |
| Kicking-team return endpoint outside the field of play | 3 |
| Described dead-ball spot outside the field of play | 1 |

These failures and guarded cases explain why the 10,000-run request produced only 7,993 games eligible for the score and win distributions. Resolve these paths before presenting the batch as a complete-game forecast.

## Player-stat coverage

The frozen database snapshot contained 18 Dallas depth-chart rows and 23 Philadelphia rows. It did not contain starter flags or jersey numbers for these rows. The batch produced roster-role allocations for 41 players across the 7,993 valid games. These are not player-specific performance predictions and should not be used as player-prop forecasts.

## Frozen inputs and provenance

- Pregame cutoff: 2026-10-26T17:21:52Z
- Scheduled kickoff: 2026-10-27T00:15:00Z
- Kickoff source: [NFL Week 7 schedule](https://www.nfl.com/schedules/2026/by-week/week-7)
- Historical play window: nfl_pbp, seasons 2022–2025, weeks 1–18
- Pregame snapshot SHA-256: d5c106ad5db47a01e809f7999cc4b130fcc8569ebc5395ac24ad8ef039873db1
- Observed-reference SHA-256: 5d0bf76fc882467a4f0c25e55fafe3e14450cb6c1f6f8b9ffff1786f21079951
- Minimal read-only input database SHA-256: 97b2a3477d5626b4f661613b9f7e50b29d837bb25792e4d4c55af89a0a48a6f5
- Source branch/base commit: feat/statistical-full-game-e2-2026-10-25 at 90c74641effc24986eec8dbb55170b10242ac0b5
- Producer worktree was dirty. The batch-runner file used for the run had SHA-256 6f2a9b3f3849cd5caff9c138ad4502f530a3bf5fec8cebed11df5222124b17c0. It preserves missing starter/group values as unknown and records raw player-stat sums so the six shards can be combined without rounding loss. The final aggregate removes that internal field. Reproducing from the base commit alone is not sufficient.

The six non-overlapping shards covered seeds 1–1,667; 1,668–3,334; 3,335–5,001; 5,002–6,668; 6,669–8,334; and 8,335–10,000. The run took about 63 minutes on the six-worker remote host. The merger verified matching snapshot, reference, baseline, and producer metadata, then checked the combined seeds were exactly 1–10,000 with no gaps or duplicates.

## Validation and artifacts

The remote smoke run for seed 1 was valid and matched the local snapshot and reference hashes. The focused batch test file passed all 6 tests, and the runner passed py_compile.

The merged result JSON has SHA-256:

327aff0095f46eb90c8f977411fbb7838a5a927efcf5eb9494f45b833f963538

The JSON, manifest, and minimal reference database are retained on the faster host under /root/nfl-dal-phi-10k-2026-10-26/. The manifest records per-shard checksums and counts; its SHA-256 is:

8911873d8605e25f40de05c724da2b0878589548aaefa70e8f09e746246b1f4e

## Interpretation

This batch demonstrates that the runner can execute and aggregate 10,000 consecutive seeded attempts while retaining invalid outcomes. It does not establish calibrated Cowboys–Eagles betting probabilities. Most attempts passed the current validity gate, but the remaining special-teams, overtime, clock, field-position, and player-stat reconciliation paths still affect coverage. The roster snapshot also lacks starting-player and jersey-number enrichment.
