# SLC v2 Milestone 6 freeze: candidates and retrospective 2025 rules, 2026-11-02

Status: written before the 2025 retrospective run. The candidates, comparators, code and thresholds below are fixed. The 2025 fold is previously exposed, so this run is a retrospective check, not an untouched test, and it is reported as such. No 2026 result is read. Nothing is committed.

## 1. Candidates frozen for the 2025 run

Chosen from development evidence only (2023 and 2024). A candidate is frozen if its in-season update showed a positive gain with an interval above zero in both development seasons over its primary comparator.

| Candidate | Metric | Primary comparator | Development gain (2023 / 2024) | Frozen |
|---|---|---|---|---|
| C1, P1 team pass share | team pass share per game | coach-era prior, no in-season update | +0.00066 (+0.00013 to +0.00118) / +0.00088 (+0.00031 to +0.00147) | yes |
| C2, P2 player target share | player target share per game | prior-only estimate, no in-season update | +0.00039 (+0.00036 to +0.00043) / +0.00046 (+0.00041 to +0.00051) | yes |

Not frozen, and not run on 2025:
- P1 tempo (plays per game): significantly worse than the league baseline in 2024; no in-season gain over the coach-era prior with an interval above zero in either season.
- P1 fourth-down go rate: worse than the team prior-only estimate in both seasons, intervals include zero.
- P2 snap share (`off_pct`): skipped in development. Coverage 0.0000 in 2023 and 0.2947 in 2024 (the field is absent in 2023 and covers a subset in 2024), below the 0.95 requirement. No development result, so no 2025 run.
- P3 defensive matchup: rejected in development (no outcome beats the baseline in both seasons with an interval above zero).
- PBV1 package sampler: the 2025 retrospective fold was pre-specified in `PBV1-SAMPLER-SPEC-2026-11-02.md` and already run.

## 2. Fixed definitions

- Availability lag: 10 hours after scheduled kickoff, for the weekly logs and play-by-play (an assumption; the publisher does not state timing).
- Cutoff: final horizon, kickoff minus one hour.
- Shrinkage: K = 4 pseudo-games for both candidates.
- P1 prior: head-coach prior-season mean with at least 8 team-games, else team prior-season mean, else league prior-season mean. Head coach carried from the team's latest usable earlier game.
- P2 prior: player's prior-season mean with at least 4 prior-season games, else position-group prior-season mean.
- Loss: squared error. Intervals: game-clustered, 10,000 draws, seed 20261102.

## 3. Code hashes at freeze (SHA-256)

- `slc-v2-p1-team-2026-11-02/p1_team.py`: `14256db1a626c2bdce8ea4184c89686162448e1597e832f956b6ae904e36a7dd`
- `slc-v2-p1-team-2026-11-02/p1_eval.py`: `d800ed661553721a1ed356584593c1486fa44dfb824e3d631c2e785814f471dc`
- `slc-v2-p2-usage-2026-11-02/p2_usage.py`: `601cb0b6e98c8d69f46ec11d06bd234b8e80a6f099d4a827d2d3280e64c86e25`
- `slc-v2-p2-usage-2026-11-02/p2_eval.py`: `84aadd78cdb3cc42a72fae4b807169d28a331ba7c29d3f5e480e863ba61c561b`
- `pbv1-sampler-2026-11-02/pbv1_sampler.py`: `30e5c5c2817429607446648440563d5576600b79c67863bee90a20f46849509f`
- `slc-v2-depth-adapter-2026-11-02/depth_adapter.py`: `ff8086cb2b599ca7c6540ae9e0256513986e2b1680b68ee0d2019d09f9e93766`

## 4. Adoption categories for the 2025 result (predeclared)

For each candidate, the 2025 improvement over its primary comparator, with its 95% game-clustered interval:

- **ADOPT (research only):** point estimate above zero and lower bound above zero.
- **REVISE:** point estimate above zero, interval includes zero.
- **INCONCLUSIVE:** point estimate at or below zero, interval includes zero.
- **REJECT:** upper bound below zero.

A research ADOPT is not production adoption. Production adoption would need an independent final evaluation (the strategy document, Phase G).

## 5. Run rules

- Run `p1_eval.py --retro` and `p2_eval.py --retro` once, with the frozen code above. Metrics: pass share only for P1, target share only for P2.
- No threshold, K, prior rule or metric is changed after seeing 2025 results. Any change would be a new candidate, reported separately and not claimed as frozen.
- 2026 is not read.
