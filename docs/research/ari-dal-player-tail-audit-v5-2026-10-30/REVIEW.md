# ARI–DAL 10K player workload audit

**Run:** `2026_08_ARI_DAL`, 10,000 frozen seed outcomes.

**Forecast cutoff:** 2026 Week 8; historical benchmark windows stop at 2026 Week 7.

**Disposition:** Keep the original run immutable. The 11 completed overtime ties remain in outcome denominators; the six blocked games remain excluded from completed-game distributions.

## Outcome accounting

The archived run has 10,000 seed ledgers and box scores: 9,994 completed games (9,479 regulation, 515 overtime) and six blocked games. Eleven completed games ended tied after overtime. Therefore, use **9,994** for outcome rates and **9,983** for decisive-game winner rates. No regulation tie was marked complete. Reclassification did not alter seed or box-score totals.

The audit reads the published `boxscore-summary.json`, archived seed ledgers, and player box scores. `summary.json` and `manifest.json` preserve source hashes and these counts. The source run is unchanged.

## Record-boundary findings

These are statistical `RECORD_EXCEEDANCE` alerts, not claims of an illegal play. Historical reference boundaries are 45 carries, 28 targets, 21 receptions, and 296 rushing yards.

| Player and metric | Exceedance | Rate of completed games | Maximum | Seeds |
|---|---:|---:|---:|---|
| Javonte Williams, carries ≥46 | 11 | 0.110% | 54 | 127, 248, 920, 2033, 3978, 5532, 6339, 7090, 8404, 8502, 9988 |
| Javonte Williams, rushing yards ≥297 | 1 | 0.010% | 300 | 8404 |
| Michael Wilson, targets ≥29 | 15 | 0.150% | 36 | 1300, 1995, 2126, 3206, 4160, 4786, 5428, 6181, 6208, 6779, 8211, 8630, 8706, 9116, 9190 |
| Michael Wilson, receptions ≥22 | 7 | 0.070% | 23 | 3206, 4123, 4494, 5428, 5536, 5600, 7559 |
| George Pickens, targets ≥29 | 2 | 0.020% | 32 | 5283, 8629 |

Jacoby Brissett exceeded 50 rushing yards in **1,387/9,994 games (13.878%)**, with a maximum of 147 yards in seed 3741. This is a workload/tendency calibration failure, not a league-record exceedance. Bam Knight had 30+ carries in **207/9,994 (2.071%)**, maximum 42 in seed 7893.

## Seed-level reconstruction

The findings CSV contains the exact game state, score, player stat line, team opportunities, reconstructed game share, and archived fallback counters for every listed seed. Selected high outcomes:

| Seed | Player line and context | Mechanism evidence |
|---:|---|---|
| 8502 | Williams: 54 carries, 295 yards, 5 TD; 88 Dallas plays, 62 run decisions, 26 dropbacks; home–away score 52–17 | 87.1% of team run decisions credited to Williams; reconstructed game share 70.0%, reconstructed within-RB share 95.3% |
| 8404 | Williams: 46 carries, 300 yards, 2 TD; 86 plays, 54 run decisions, 32 dropbacks; 44–24 | 85.2% of run decisions; reconstructed game share 32.4%, within-RB share 97.9% |
| 5428 | Wilson: 36 targets, 23 catches, 234 yards, 2 TD; 88 plays, 58 dropbacks/attempts, 30 run decisions; 30–26 | 62.1% of team targets; reconstructed game share 28.3%, within-WR share 96.5% |
| 3206 | Wilson: 29 targets, 23 catches, 218 yards; 92 plays, 50 dropbacks, 48 attempts, 42 run decisions; 16–31 | 60.4% of targets; reconstructed game share 11.2%, within-WR share 97.8% |
| 8629 | Pickens: 32 targets, 21 catches, 223 yards, 1 TD; 80 plays, 55 dropbacks/attempts, 24 run decisions; 37–35 | 58.2% of targets; reconstructed game share 42.4%, within-WR share 75.8% |
| 3741 | Brissett: 10 carries, 147 yards, 2 rush TD; 20/14 passing, 134 yards, 3 pass TD, 1 lost fumble; 60 plays, 38 run decisions, 21 dropbacks; 23–41 | Six QB-scramble playcall counts; reconstructed QB game share 33.5%, within-QB share 96.9% |
| 7893 | Knight: 42 carries, 188 yards, 1 TD; 89 plays, 56 run decisions, 33 dropbacks; 7–24 | 75.0% of team run decisions; reconstructed game share 66.6%, within-RB share 83.6% |

The archived run does **not** contain per-play participant-selection traces or sampled share vectors. The audit reconstructs the deterministic game-level share vector from the frozen seed, snapshot hash, 2025 role shares, and fitted concentrations. This supports attribution to an extreme game-level share draw, but it cannot identify the exact historical play on which each participant was selected. Do not describe these reconstructions as a replay of the original play-level choices.

## Root-cause evidence and reference comparisons

The opportunity model allowed every injury-eligible QB into the ordinary carry share pool without an in-game QB substitution. Across the frozen run, backup QBs received 10,440 carries and 35,170 rushing yards in 4,108 unique games, plus 351 targets in 342 games. The frozen snapshot identifies Dak Prescott and Jacoby Brissett as QB1; Gardner Minshew and Sam Howell as QB2; and Carson Beck as Arizona QB3. No corresponding QB substitution event was recorded. This is an eligibility mechanism defect, not a workload tail to calibrate away.

All 360,000 exported player rows had `starter=false`. The old exporter defaulted missing starter metadata to false. The research-branch serializer now derives QB1 from frozen depth rank and availability and emits `null` for other roles when starter status is unknown. The frozen output remains unchanged.

Cutoff-safe reference values in `player-workload-reference-2026-10-30-v2/` show:

| Player/metric | 2025 holdout | 2026 Weeks 1–7 | SLC pre-Week-8 reference supplied with the audit |
|---|---:|---:|---:|
| Javonte Williams carries/game | 15.75 (16 games) | 15.71 (7) | 20.51; +31% vs 2026 observed |
| Michael Wilson targets/game | 7.41 (17) | 9.43 (7) | 13.57; +44% vs 2026 observed |
| Jacoby Brissett carries/game | 2.71 (14) | 3.71 (7) | 5.14; +38% vs 2026 observed |
| Jacoby Brissett rushing yards/game | 12.00 (14) | 11.43 (7) | 27.51; +141% vs 2026 observed |
| Bam Knight carries/game | 8.20 (10) | 6.25 (4) | 30+ carries in 2.071% of completed simulations |

Team opportunity rates (simulation versus 2026 Weeks 1–7) were: Arizona, 64.03 versus 68.43 plays, 33.94 versus 40.43 pass attempts, and 29.09 versus 25.86 rushes per game; Dallas, 67.72 versus 62.86 plays, 35.85 versus 39.00 pass attempts, and 31.34 versus 22.86 rushes. These are first-order opportunity counterfactuals that replace one aggregate factor while holding the simulated player share fixed; they are not paired-seed reruns.

* **Williams:** 20.51 simulated carries/game versus 15.71 observed. His simulated share is about 65.4% of Dallas carries. Replacing only simulated team carries (31.34) with observed carries (22.86) yields **14.95** carries for Williams. Thus the team’s excess rushing volume explains almost all of his mean carry gap; the observed player share is slightly higher than his simulated share.
* **Wilson:** 13.57 simulated targets/game versus 9.43 observed. The implied simulated target share is about 40.0%, versus 23.3% observed. Replacing only Wilson’s share with the observed share while retaining simulated Arizona pass volume gives **7.92** targets. Replacing only team pass attempts (33.94) with the observed 40.43 while retaining the simulated share gives **16.16**. This isolates target allocation as the excess driver, partly masked by lower simulated team pass volume.
* **Brissett:** 5.14 simulated carries/game and 27.51 rushing yards versus 3.71/11.43 observed in Weeks 1–7; his 2025 holdout is 2.71/12.00. Scaling only aggregate Arizona rush volume from 29.09 to 25.86 at his simulated share reduces his carries to about **4.57**, leaving a player/QB-action allocation gap. The 1,387 games above 50 yards and seed 3741’s 10 carries/147 yards show that player-conditioned yardage and QB action need separate evaluation.
* **Knight:** 12.11 simulated carries/game versus 8.20 in the 2025 holdout (and 6.25 in the four observed 2026 games). The 30+ carry tail cannot be explained by team volume alone; role allocation and game-level opportunity concentration also need calibration.

The player-history samples for 2026 are small and event-derived participation denominators are lower bounds. Use the published 2025 holdout and multi-season references with the manifest’s coverage notes; do not treat a seven-game mean as a stable player limit.

The largest supported mechanisms are: (1) unrestricted backup-QB eligibility, (2) high simulated team run volume and game-state run decisions for carry tails, and (3) game-level share draws that sometimes concentrate nearly all position opportunities on one player. Wilson’s target tail is principally a share-concentration problem: the observed 2026 target mean is below 10, while the pre-Week-8 simulated mean is 13.57 despite lower team pass volume than observed. Brissett’s extreme yardage combines excessive QB rushing opportunities with a player-conditioned yardage tail. These findings support mechanism changes; they do not justify hard-capping a player at his mean, P95, or historical maximum.

## QB run-role holdout evidence

The opt-in QB style layer was evaluated against pinned play-by-play data in [`qb-run-role-style-holdout-2026-10-30/RESULTS.md`](../qb-run-role-style-holdout-2026-10-30/RESULTS.md). The 2025 evaluation fits 2022–2024; the forecast-target evaluation fits 2022–2025 and scores only 2026 Weeks 1–7. Both aggregate Brier point estimates improve, but the game-clustered 95% intervals include zero:

| Evaluation window | Eligible run decisions | QB runs | Control Brier | Style Brier | Difference, style − control | Clustered 95% interval |
|---|---:|---:|---:|---:|---:|---:|
| 2025 holdout | 12,815 | 639 | 0.043723 | 0.043493 | −0.000229 | [−0.000508, 0.000054] |
| 2026 Weeks 1–7 | 5,056 | 235 | 0.039945 | 0.039621 | −0.000324 | [−0.000823, 0.000162] |

For Brissett in Arizona during 2026 Weeks 1–7, 16 of 168 eligible team-run decisions were QB runs (9.52%). The mean control probability was 8.70%; the style adjustment lowered it to 6.65%. Across those observed team-run opportunities, that corresponds to 14.6 expected QB credits under control and 11.2 under style, versus 16 observed. This is a conditional role-rate test, not a full-game SLC ablation; it does not establish that the layer fixes Brissett's simulated rushing-yard tail. Keep the layer opt-in pending the paired full-game evaluation.

## Fix order

1. Enforce QB participation from frozen active status plus an explicit entry/substitution mechanism; add a negative test for an unused backup QB receiving a carry or target.
2. Use player-specific QB run style and event class (designed run, scramble, sneak, kneel) with down, distance, score, clock, and dropback state. Brissett’s 2025 holdout has 2.71 rush attempts and 12.0 yards per game; 1,387 simulated games above 50 yards is not supported by that role evidence.
3. Refit player share tails and workload-dependent substitutions using held-out game distributions. Preserve rare records as alerts rather than clipping them.
4. Re-evaluate team play volume and run/pass choices before tuning yards per carry.
5. Add paired-seed ablations that change one mechanism at a time and report per-player means, variance, zero rate, P95/P99, maximum, and record-exceedance rates.

## Verification status

The benchmark builder produces train 2022–2024, holdout 2025, multi-season 2022–2025, and target 2026 Weeks 1–7 files, with cutoff, coverage, source hashes, and published-source reconciliation. V2 corrects two hard-coded named-example IDs and leaves the distribution tables unchanged. A five-yard receiving reconciliation difference remains documented in `player-workload-reference-2026-10-30-v2/published_source_reconciliation.csv`; other checked player totals reconcile. The audit preserves source hashes and all 10,000 seed records.

The research branch has deterministic assertions for participation/accounting and the updated serializer; its recorded verification was 126 tests across the NFL-sequence modules, plus 31 Model D tests and `git diff --check`. The full same-seed ablation matrix and calibrated player-style model are **not yet complete**. These remain open research items; this audit does not certify the entire player-realism task as closed.
