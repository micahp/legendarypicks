# Model D OOB support and 2025 holdout replay — full-season training

**Training:** 2022–2024 regular seasons, Weeks 1–18; 815 source games, with the six named development games excluded (809 fit games; 103,072 fitted plays).

**Holdout:** 2025 regular season, Weeks 1–18; 272 games. The replay uses 20 replicates and evaluates 785 eligible quarter boundaries (15,700 quarter-replicates); 303 quarters are excluded by the boundary-test eligibility rule.

**Scope:** This is the event-driven Model D clock evaluation, separate from the SLC 10K matchup batch. The machine-readable replay records input and code hashes, train/evaluation windows, and all quarter/window support cells.

## Training support by quarter and exact clock window

Counts include classifiable OOB plays that can contribute to Model D hazard support. “Censored” is the quarter-ending count, which is excluded from runoff samples. The final column in each class is the uncensored runoff support. The two-minute Q2 boundary is inclusive at 120 seconds; the Q4 five-minute policy is strict at 300 seconds.

| Quarter | Clock window | Policy window | `oob_snap` examples (censored) | `oob_snap` runoff n | `oob_ready` examples (censored) | `oob_ready` runoff n |
|---|---|---|---:|---:|---:|---:|
| Q1 | 1–15s | none | 0 (0) | 0 | 32 (32) | 0 |
| Q1 | 16–30s | none | 0 (0) | 0 | 31 (30) | 1 |
| Q1 | 31–60s | none | 0 (0) | 0 | 65 (24) | 41 |
| Q1 | 61–120s | none | 0 (0) | 0 | 124 (1) | 123 |
| Q1 | 121–900s | none | 0 (0) | 0 | 1,913 (0) | 1,913 |
| Q2 | 1–15s | at or inside 2:00 | 77 (7) | 70 | 0 (0) | 0 |
| Q2 | 16–30s | at or inside 2:00 | 148 (1) | 147 | 0 (0) | 0 |
| Q2 | 31–60s | at or inside 2:00 | 279 (0) | 279 | 0 (0) | 0 |
| Q2 | 61–120s | at or inside 2:00 | 409 (0) | 409 | 0 (0) | 0 |
| Q2 | 121–900s | outside 2:00 | 0 (0) | 0 | 1,828 (0) | 1,828 |
| Q3 | 1–15s | none | 0 (0) | 0 | 29 (29) | 0 |
| Q3 | 16–30s | none | 0 (0) | 0 | 25 (25) | 0 |
| Q3 | 31–60s | none | 0 (0) | 0 | 71 (24) | 47 |
| Q3 | 61–120s | none | 0 (0) | 0 | 145 (1) | 144 |
| Q3 | 121–900s | none | 0 (0) | 0 | 1,802 (0) | 1,802 |
| Q4 | 1–15s | inside final 5:00 | 32 (6) | 26 | 0 (0) | 0 |
| Q4 | 16–30s | inside final 5:00 | 46 (0) | 46 | 0 (0) | 0 |
| Q4 | 31–60s | inside final 5:00 | 102 (2) | 100 | 0 (0) | 0 |
| Q4 | 61–120s | inside final 5:00 | 232 (0) | 232 | 0 (0) | 0 |
| Q4 | >120 and <300s | inside final 5:00 | 449 (0) | 449 | 0 (0) | 0 |
| Q4 | 300–900s | outside final 5:00 | 0 (0) | 0 | 1,387 (0) | 1,387 |
| **Total** |  |  | **1,774 (16)** | **1,758** | **7,452 (166)** | **7,286** |

There are no `oob_snap` examples in Q1 or Q3, and no `oob_ready` examples in Q2 at or inside two minutes or in Q4 inside five minutes. Sparse cells must refuse or use an explicitly tested rule-preserving mechanism; they must not borrow a generic clock-running distribution.

The often-cited **375 completed passes** are only one event subtype in Q4’s `>120 and <300s` `oob_snap` cell: that cell contains **449** examples total—375 completed passes, 71 runs, and 3 sacks. A pass-only count is not the stop-class denominator.

## 2025 holdout results

| Measure | Observed | Model D | Same-window E2 baseline | Interpretation |
|---|---:|---:|---:|---|
| `oob_snap` runoff ≤15s | 98.1% (n=537) | 98.6% | 17.6% | Event-specific restart is close to observed |
| `oob_ready` runoff ≤15s | 2.6% (n=2,307) | 3.7% | 14.6% | Better than generic running-clock sampling; still 1.1 pp high |
| Accurate quarter-end classification | — | 547 / 15,700 (3.48%) | — | Low |
| Premature quarter ends | — | 676 / 15,700 (4.31%) | — | 2.68 observed plays lost per premature quarter |
| Missed quarter ends | — | 14,477 / 15,700 (92.21%) | — | Principal remaining clock-calibration error |

Model D preserves the OOB restart distinction at 2025 holdout. Its quarter-end hazard remains poorly calibrated; this report does not support changing SLC defaults.

## Scope correction and provenance

The earlier [`train-2022-2024-stopclass-invariants-v2`](../train-2022-2024-stopclass-invariants-v2/REVIEW.md) report was labeled as a 2022–2024 training window, but its machine-readable run used **Weeks 1–5**, 236 source games, and 234 fit games after excluding two development games. Its 485 `oob_snap` and 2,132 `oob_ready` figures—and its 4.71% premature / 91.99% missed quarter-end results—are for that narrower sample, not the requested full-season window. A separate older replay used the full training window but only two replicates (1,570 quarter-replicates). Both older outputs remain preserved; this v3 run provides the full-season 20-replicate result.

OOB class counts are derived from nflverse PBP and the OOB policy; these derived stop classes are not a separately published NFL statistic. The source `out_of_bounds` field is description-derived (`ran ob`, `pushed ob`, or `sacked ob`), as documented by [nflfastR](https://nflfastr.com/reference/clean_pbp.html), so the counts inherit that source classification.

I independently rebuilt the support table from the hash-pinned nflverse `pbp_2022.csv.gz` through `pbp_2024.csv.gz` files rather than the local DB and sparse flags. Their hashes match the [local workload-reference manifest](../../../player-workload-reference-2026-10-30-v3/manifest.json). The 141,830 regular-season game/play keys match the local `nfl_pbp` keys exactly, all 12,246 raw OOB keys match the sparse `play_extras` fixture, and a game/play-sorted raw-source reconstruction matches all 42 support cells. The replay JSON records the database, play-extras, `clock_d.py`, `clock_d_replay.py`, and `e1_drive.py` hashes. Its 103,072 fitted-play count also matches the existing full-season 2022–2024 replay.

Rebuild the full-window 2025 holdout artifact with:

```sh
python scripts/nfl_sequence/clock_d_replay.py \
  --window holdout \
  --train-season-from 2022 --train-season-to 2024 \
  --train-week-from 1 --train-week-to 18 \
  --replicates 20 \
  --out-dir docs/research/e3/oob-policy-replay-2026-10-30/train-2022-2024-full-season-v3
```
