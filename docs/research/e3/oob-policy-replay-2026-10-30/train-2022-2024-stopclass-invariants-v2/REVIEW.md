# Model D out-of-bounds and clock replay review

**Training:** 2022–2024, with two 2022 Week 5 games excluded for development.

**Holdout:** 2025 Weeks 1–18.

**Purpose:** Validate event-specific out-of-bounds runoff support and clock boundaries independently of the completed SLC 10K batch.

## Training support by quarter and clock window

Counts below are event examples before excluding quarter-ending/censored runoff. Windows are remaining-clock seconds. `oob_snap` means the ball is snapped while the runner is out of bounds; `oob_ready` means the runner went out and the next snap/ready-for-play phase governs the clock.

| Stop class | Quarter | 1–15s | 16–30s | 31–60s | 61–120s | 121–900s | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| oob_snap | Q1 | 0 | 0 | 0 | 0 | 0 | 0 |
| oob_snap | Q2 | 28 | 45 | 78 | 101 | 0 | 252 |
| oob_snap | Q3 | 0 | 0 | 0 | 0 | 0 | 0 |
| oob_snap | Q4 | 13 | 11 | 27 | 67 | 115 | 233 |
| oob_ready | Q1 | 5 | 7 | 24 | 36 | 531 | 603 |
| oob_ready | Q2 | 0 | 0 | 0 | 0 | 532 | 532 |
| oob_ready | Q3 | 9 | 10 | 19 | 52 | 510 | 600 |
| oob_ready | Q4 | 0 | 0 | 0 | 0 | 397 | 397 |

Totals: **485 oob_snap** events (479 uncensored; six quarter-ending examples, three each in Q2 and Q4) and **2,132 oob_ready** events (2,088 uncensored; 44 quarter-ending examples). The machine-readable file contains the full counts and censoring detail for each quarter/window cell.

There are no `oob_snap` examples in Q1 or Q3 and no `oob_ready` examples inside 120 seconds in Q2 or Q4. The model must refuse unsupported cells or use a tested rule-preserving mechanism. It must not silently replace a missing `oob_snap` cell with a generic clock-running distribution.

## 2025 holdout results

The holdout includes 272 games and 1,088 quarters. The boundary test has 785 quarters; 303 are excluded by its eligibility filter.

| Measure | Observed | Model D | Interpretation |
|---|---:|---:|---|
| `oob_snap` runoff ≤15s | 98.1% (n=537) | 98.5% | Close event-specific fit |
| `oob_ready` runoff ≤15s | 2.6% (n=2,307) | 3.4% | Better than generic running-clock baselines (13.9–15.1%) |
| Correct quarter-end classification | — | 518 / 15,700 | Low overall accuracy |
| Premature quarter ends | — | 740 / 15,700 (4.71%) | Average 2.64 plays lost per premature quarter |
| Missed quarter ends | — | 14,442 / 15,700 (91.99%) | Principal remaining clock-calibration error |

Model D therefore distinguishes the two OOB stop classes correctly at short runoff, but its quarter-end hazard calibration remains poor. Preserve the 2025 holdout while improving event/clock hazards; do not tune away the OOB class distinction to improve aggregate clock-running rates.

## Rule boundaries and evidence

The replay keeps Q2’s two-minute warning and Q4’s five-minute policy boundaries explicit. Training used 234 games and 29,657 plays after excluding the two development games. The replay artifact includes source hashes, event support, model comparisons, quarter-end tallies, and the selected clock-window policy.

Reproduce from the pinned replay inputs and code hashes in `clock-d-replay-holdout.json`. This is a clock-model result only; it is not evidence that player workload calibration or the 10K matchups are complete.
