# SLC V1.6 versus frozen V1.5: bounded full-game comparison

**Run date:** 2026-11-12
**Code commit:** `3f98f07e` (`Fix V1.6 runtime evidence and outcome sampling`)
**Decision:** Do not freeze V1.6. The exact-distance correction now runs, but fourth-down and third-down opportunity rates remain above the historical reference. The available box-score exports do not preserve ordered plays, so they do not identify the exact first- or second-down transition causing the remaining excess.

## Scope and inputs

The comparison covers two Week 8 snapshots, ARI–DAL and ATL–TB, with seeds 1–10 in each arm: 20 games per arm and 40 team-games. The V1.5 control used `v1_full_stack`, season adaptation, and `N0=4`. The V1.6 candidate used `v1_6_candidate` with conditional pass-label outcomes and the exact-distance yardage layer.

Both arms used the same source snapshot files, play-call artifact (`c8f16540931f6fddc61b6e62797ecd71dfff11897c393c531033eef623328ce5`), streak file (`4d3e0d712134396ea91d1d9d8bca11ce9d6089674d9d6e2360696f44e311af5c`), blocker-fix set, and read-only database path. The source snapshot inventory hash in both run reports is `78452a420dc73206554600afc39effb5946cfcc87931d200cb850113765c4733`.

The model snapshot and reference hashes differ between arms because each profile builds a different model reference. Therefore, matching seed numbers do **not** mean identical RNG roots; this is a same-source-input comparison, not a strict common-random-number pairing. The source reports preserve each arm's identities and code hashes.

All 20/20 games in each arm completed with `valid_complete` status and passed box-score reconciliation. The V1.6 reports recorded 1,146 exact-distance applications for ARI–DAL and 1,124 for ATL–TB. The sampler-order fix and regression test are in code commit `3f98f07e`.

## Results

Historical references are from the 2022–2025 regular-season audit in [the V1.6 mechanism-gates report](../slc-v1.6-mechanism-gates-2026-11-11/fourth-down-opportunity-audit.md). Rates below are per team-game unless stated otherwise.

| Measure | Frozen V1.5 | V1.6 candidate | Historical |
|---|---:|---:|---:|
| Third-down attempts | 13.50 | 14.00 | 12.55 |
| Third-down conversion rate | 50.2% | 43.6% | 39.7% |
| Fourth-down states | Not reliably captured | 7.42 | 6.82 |
| Fourth-and-1–2 states | Not reliably captured | 1.68 | 1.37 |
| Sacks | 0.53 | 2.00 | 2.43 |
| Turnovers | 0.70 | 0.85 | 1.15 |
| Negative scrimmage plays | 4.40 | 5.10 | 5.18 |
| Drives | 9.85 | 10.90 | 10.86* |

Third-down attempts and conversion by distance:

| Distance | V1.5 attempts / conversion | V1.6 attempts / conversion | Historical attempts / conversion |
|---|---:|---:|---:|
| 1–2 yd | 3.15 / 60.3% | 2.92 / 67.5% | 2.61 / 63.8% |
| 3–5 yd | 4.17 / 59.9% | 4.53 / 49.2% | 3.14 / 46.7% |
| 6–9 yd | 3.88 / 40.0% | 3.62 / 36.6% | 3.45 / 35.4% |
| 10+ yd | 2.30 / 35.9% | 2.92 / 19.7% | 3.34 / 18.8% |

V1.6 fourth-down states occurred at 0.681 per drive, compared with 0.628 historically. Its 1–2 yard fourth-down rate was 23% above the historical rate. The fourth-down decision policy was unchanged.

Drive terminal rates (share of drives):

| Ending | V1.5 | V1.6 | Historical |
|---|---:|---:|---:|
| Punt | 30.5% | 34.4% | 35.6% |
| Touchdown | 25.9% | 23.2% | 21.8% |
| Field-goal attempt | 17.8% | 17.9% | 18.3%* |
| Turnover | 7.1% | 8.0% | 10.1% |
| Turnover on downs | 8.6% | 6.9% | 5.7% |
| Scoring drives (TD or FG) | 41.6% | 38.3% | 40.1% |

`*` Historical drive volume and terminal rates were derived from the local play-by-play extract. It contains 23,579 classifiable drives, while the earlier audit reports 23,599; the 20-drive difference is unresolved. Historical field-goal endings combine made and missed attempts.

## Interpretation

V1.6 improves the full-game sack count over V1.5, and its negative-play count is close to historical. Turnovers remain low. Third-down attempts are high, especially at 3–5 yards; overall third-down conversion remains above historical. These conditions accompany the excess fourth-down states and short fourth downs.

This run does not establish which earlier-down transition creates those states. The archived outputs include per-game box scores and seed summaries, but not ordered play transitions. The next correction should be based on a play-level transition trace that separates first- and second-down gains, third-down failures leaving 1–2 yards, and drive-ending sacks or turnovers. Do not change the fourth-down decision policy based on this comparison.

The V1.5 wrapper counted only scrimmage plays when recording fourth-down opportunities. Its fourth-down state and fourth-and-short figures are therefore omitted from the comparison; its 1.10 short-fourth value from earlier summaries is a go-for-it count, not an opportunity count.

The two-matchup sample is diagnostic, not a release-grade held-out evaluation. **V1.6 remains unfrozen.**

## Verification

Focused tests passed: 248 tests across `test_slc_playcall`, `test_slc_config`, `test_slc_engine`, and `test_game_state`.

The 12 original run files (14,288,568 bytes) are retained in [`artifacts/paired-game-outputs.tar.gz`](artifacts/paired-game-outputs.tar.gz). The archive contains both arms' per-game reports, box-score JSONL, and seed JSONL for both matchups. [`SHA256SUMS.json`](artifacts/SHA256SUMS.json) records the archive hash and SHA-256/size of every original file.
