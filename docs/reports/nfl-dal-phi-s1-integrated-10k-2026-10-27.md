# Dallas–Philadelphia S1 Integrated 10,000-Run Report

**Game:** Dallas Cowboys at Philadelphia Eagles (`2026_07_DAL_PHI`)  
**Scheduled kickoff:** 2026-10-27 00:15 UTC  
**Pregame information cutoff:** 2026-10-26 22:45:01.400 UTC  
**Batch output frozen:** 2026-10-27 03:04:50.891 UTC  
**Report date:** 2026-10-27

## Result

The integrated contextual simulator completed all 10,000 requested seed attempts. The run manifest verifies 10,000 unique rows covering seeds 1 through 10,000 across six shards. The archived result and shard JSONs contain aggregate summaries and replay examples, not a per-seed outcome ledger, so individual blocked and failed seed records cannot be audited from these artifacts.

| Measure | Result |
| --- | ---: |
| Requested runs | 10,000 |
| Valid complete, untied games | 9,820 (98.20%) |
| Complete regulation games | 9,449 |
| Complete overtime games | 377 |
| Blocked outcomes | 173 |
| Simulation or validation errors | 1 |
| Regulation ties | 6 |

The score and win summaries below use only the 9,820 games that passed the validity gate. The 173 blocked outcomes and one error remain in the run denominator and are not included in those projections.

## Conditional score distribution

Philadelphia is the home team; Dallas is the away team.

| Measure | PHI | DAL | Combined / margin |
| --- | ---: | ---: | ---: |
| Mean points | 19.9695 | 20.8081 | 40.7776 total |
| Median points | 20 | 20 | 40 total |
| 10th–90th percentile | 9–31 | 10–33 | 26–56 total |

Dallas won 5,152 of 9,820 valid games (52.46%); Philadelphia won 4,668 (47.54%). The mean PHI-minus-DAL margin was −0.8387 points, or DAL by 0.8387. The most frequent exact score was PHI 20, DAL 17, occurring 66 times (0.67% of valid games). The percentile ranges describe simulated outcomes; they are not confidence intervals.

## Model and inputs

This was S1 with contextual sampling enabled for both teams. A Gaussian kernel conditioned the historical play pool on opponent-adjusted offensive and defensive points ratings, with a bandwidth of 1.0 source-rating standard deviations and a minimum effective source-game count of 10. Same-week games were excluded. The eligible play-by-play pool extended through the week before 2026 Week 7. The simulator also used pinned 2022–2025 special-teams reference inputs, including observed safety free kicks, and the integrated blocked-kick and overtime rules.

The frozen team context included season-to-date performance through Week 6 and recent-form summaries. The roster snapshot contained 18 Dallas and 23 Philadelphia skill-position depth-chart rows, but no row had a jersey number or starter flag. Player totals are simulator allocations from that snapshot, not player-specific forecasts.

## v1 reference and fairness limits

The recorded v1 lock was at the same timestamp as the context cutoff. It projected PHI 23.1840, DAL 23.1421, and 46.3261 combined points. The simulator's valid-game means were lower by 3.2145 PHI points and 2.3340 DAL points, with a 5.5485-point lower mean total.

This is **not a fair predictive-accuracy comparison**. The v1 reference is marked `exploratory_schedule_unverified`, with `comparable_at_snapshot_cutoff=false`: schedule availability at the lock could not be verified from historical versions. The input availability manifest also notes that play-by-play rows lack row-level publication timestamps and historical schedule revisions are unavailable. Do not score these results as an equal-information v1-versus-S1 evaluation.

The simulation input cutoff preceded kickoff, but the merged batch output was frozen at 03:04:50 UTC, after the scheduled 00:15 UTC kickoff. This batch was not available as a pre-kickoff forecast. No actual game result is included in this report.

## Blocked and failed outcomes

All 173 blocked outcomes are accounted for by these guarded transitions:

| Guarded transition | Count |
| --- | ---: |
| Blocked field goal: guarded penalty, fumble, or review | 56 |
| Thin field-goal sample at 50+ yards | 45 |
| Blocked-kick receiving return endpoint outside field | 24 |
| Safety free kick not modeled | 23 |
| Blocked-kick kicking recovery outside field | 14 |
| Blocked punt: guarded penalty, fumble, or review | 10 |
| Blocked-kick kicking return endpoint outside field | 1 |
| **Total blocked** | **173** |

One additional seed ended in a simulation or validation error. It is included in the aggregate error count, but the archived summary does not identify its seed or specific error. Safety free kicks and thin long-distance field-goal cells remain explicit coverage gaps.

## Comparison with earlier batches

The earlier S1 batch had 8,825 valid games (88.25%); this integrated run had 9,820 (98.20%). That 9.95 percentage-point coverage difference is descriptive, not a measured treatment effect. The integrated run changed the rules implementation and reference inputs, and the added inputs changed the snapshot and seed-derived draws. The runs are not paired common-random-number experiments.

Likewise, the increase over the 7,993 valid S0 games cannot be attributed to contextual conditioning. S0, earlier S1, and this integrated S1 differ in producer revisions, special-teams references, and rules coverage. These batches establish execution and coverage progress; they do not establish that S1 predicts real games better than v1.

## Reproduction and artifact provenance

- Producer repository: `micahp/legendarypicks`
- Producer branch: `research/nfl-contextual-batch-run-2026-10-26`
- Producer commit: `709fb75959c16adc74baf42e986d4fb85974e0cc`
- Producer worktree: clean
- Seeds: 1–10,000, split into six contiguous non-overlapping ranges; ranges and shard checksums are in the run manifest
- Context SHA-256: `59b1d6364c54d315ef409c9ab569e0fb6351c25acfbe2302d12810933a5b542d`
- Contextual-pool SHA-256: `300aba808186e6208784c71802b61123579073ef4e10074a13da3f47215591d2`
- Pregame snapshot SHA-256: `dcc8bb5cacda1a34e634a6ca7056af37bf2cd56da917f58aa35cc74dff57ab70`
- Observed-reference SHA-256: `25d092a117c98ea327e80f70d7d03897d46a1fa55f4e9e354497fad425b7836d`
- Source snapshot SHA-256: `edd2cc2e48353d8b33a6db0a6153bd10a374778a477b671a1943c53ef1ef0e1e`
- Batch runner SHA-256: `a57838abb7220e1892f949d0f32b79487f6edbd3f9bc423c32f0cebae0b0b841`
- Merged result SHA-256: `a8772289b9d1378ae5ca7fde79decdc6e8ca9bff561db691fd9a42f07fea8efa`
- Run-manifest SHA-256: `20963de4e8be84e4adc95e985f2fe6a3f0d39b4bd9d0a9a6d5e96e82e8248e4d`
- Remote artifact directory: `/root/nfl-dal-phi-s1-integrated-2026-10-26/`

The run manifest verifies all 10,000 rows and unique seed coverage. It records the six shard checksums and merge invariants, including game identity, snapshot, reference, v1 baseline, context, contextual pool, producer hashes, and policy settings. The reported runtime counters are 33,549.0769 seconds for game generation and 33,872.6137 seconds total before report writing; they are not asserted here to be wall-clock elapsed time.

## Conclusion

This is the first completed 10,000-seed Dallas–Philadelphia S1 batch on the integrated safety-kick, blocked-kick, and overtime path. It demonstrates 98.2% valid full-game coverage and counts the remaining 180 blocked or failed attempts in its aggregate coverage report. The per-seed records are not present in the archived artifacts. Because schedule provenance is unverified and the merged output was frozen after kickoff, this remains an engineering and exploratory simulation result, not a pregame forecast evaluation. The next accuracy comparison needs verified as-of schedule inputs and a batch that completes before the event cutoff.
