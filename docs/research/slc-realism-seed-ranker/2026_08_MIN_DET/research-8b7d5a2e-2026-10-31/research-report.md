# MIN–DET Realism Based Seed Ranking

Run: `research-8b7d5a2e-2026-10-31` · source commit `8b7d5a2ec818d4e53751f5c4baf5a2956b317a7f`.

Scored 10,000 archived seeds against 1,087 historical regular-season games from 2022–2025.
Historical comparison uses leave-one-season-out nearest neighbors; each held-out game is compared with other seasons only.

## Method

Robust median/IQR scaling is applied within four explicit groups. Each group uses the mean distance to its 20 nearest historical game rows, with the team and exact-opponent cohorts shrunk toward the league-wide neighbors by cohort size. Group distances are converted to 0–100 typicality scores using the held-out historical distance distribution.
Candidate distances used the `numpy` backend (version 2.5.4); the NumPy path applies the same clipping, group masks, neighbor means, and cohort shrinkage as the standard-library implementation.

| Group | Weight |
|---|---:|
| drives | 30% |
| decisions | 25% |
| workloads | 25% |
| game | 20% |

The four score contributions are emitted for every seed in `seed-realism-rankings.csv`. The ranking never uses the SLC 10K mean as its realism reference. Marketing interest is scored after realism and replay gates.

Visual interest is a separate 0–100 heuristic from close margin, comeback, defensive-game and bounded star flags, turnover count, and fourth-quarter scoring. It never changes the realism score; the scenario label describes why a seed was selected.

## Historical and model limits

The pinned reference contains 1,087 regular-season games (2022–2025). Team/opponent conditioning is weak for the exact DET–MIN pair and is shrunk accordingly. The historical PBP snapshot has no authoritative final-score or extra-point-result fields; the score group therefore uses a documented score proxy (touchdowns, field goals, and recorded extra-point attempts). The score proxy is not an exact scoreboard reconstruction.

The frozen matchup comparison also documents model-level differences: simulated punt terminals average 2.66 for DET and 2.78 for MIN versus historical 3.09 and 3.75; Jahmyr Gibbs averages 31.99 carries of Detroit’s 36.83 team carries (86.9%). Seed ranking cannot correct these calibration issues. See `docs/research/slc-week8-2026/reviews/2026_08_MIN_DET_drive_distribution_comparison_2022-2025_final/report.md` and `docs/research/slc-week8-2026/reviews/2026_08_MIN_DET_realism_review_2026-10-31.md`.

Stage A archived sidecars provide boxscores, drive summaries, player workload, quarter points, and aggregate play-call decisions, but not complete per-play traces. Replay is required before any seed enters the marketing shortlist. Four-down conversion choices and full score-clock decisions remain replay-stage features.

Rare outcomes are not hard-rejected for rarity. Hard gates cover run status, full-game validity, accounting reconciliation, unsupported sequences, replay equivalence, and renderability. Score-only overtime is retained for statistical scoring but excluded from full-game visualization unless its sequence is present and supported.

## Stage A summary

- Seeds read: 10,000
- Scoreable seeds: 10,000
- Stage A top replay candidates: 150
- Realism score median: 24.76
- Held-out historical distance and weight sensitivity results: `ranking-validation.json`.

## Highest Stage A scores

| Rank | Seed | Score | Drives | Decisions | Workloads | Game | Replay |
|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 6644 | 84.04 | 28.18 | 23.02 | 14.14 | 18.69 | not_tested |
| 2 | 3397 | 77.40 | 25.45 | 14.93 | 22.95 | 14.08 | not_tested |
| 3 | 8327 | 70.81 | 28.43 | 17.53 | 13.18 | 11.68 | not_tested |
| 4 | 8597 | 70.32 | 26.96 | 23.83 | 4.90 | 14.63 | not_tested |
| 5 | 7580 | 69.56 | 28.54 | 21.78 | 6.88 | 12.36 | not_tested |
| 6 | 9503 | 69.00 | 27.57 | 21.00 | 1.43 | 19.01 | not_tested |
| 7 | 1759 | 68.95 | 26.14 | 24.45 | 0.64 | 17.72 | not_tested |
| 8 | 7752 | 68.54 | 26.69 | 22.59 | 0.83 | 18.44 | not_tested |
| 9 | 2027 | 68.45 | 25.89 | 22.72 | 0.51 | 19.34 | not_tested |
| 10 | 2362 | 67.44 | 21.55 | 21.00 | 20.12 | 4.77 | not_tested |

Scores are historical resemblance ranks for examples produced by this simulator. They do not show that the simulator is calibrated or that a seed is a likely future game.

## Stage B replay and GridIron adapter validation

- Pinned-source replays attempted: 150
- Exact boxscore and score matches with a supported full sequence and passing E2 adapter: 134
- Rejected: 16
- Missing replay outputs: 0

Marketing shortlist (interest is separate from realism):

| Scenario | Seed | Realism | Visual interest | Replay |
|---|---:|---:|---:|---|
| most_representative | 3397 | 77.40 | 51 | passed |
| close_finish | 8597 | 70.32 | 82 | passed |
| comeback | 9503 | 69.00 | 82 | passed |
| defensive_game | 7752 | 68.54 | 96 | passed |
| star_showcase | 7580 | 69.56 | 60 | passed |
| additional_realistic_scenario | 1759 | 68.95 | 63 | passed |
| additional_realistic_scenario | 2362 | 67.44 | 47 | passed |
| additional_realistic_scenario | 7664 | 66.96 | 94 | passed |
| additional_realistic_scenario | 9163 | 66.81 | 98 | passed |
| additional_realistic_scenario | 5053 | 66.78 | 78 | passed |
| additional_realistic_scenario | 2948 | 66.66 | 78 | passed |
| additional_realistic_scenario | 3952 | 66.22 | 69 | passed |
| additional_realistic_scenario | 1422 | 65.66 | 58 | passed |
| additional_realistic_scenario | 4060 | 65.60 | 54 | passed |
| additional_realistic_scenario | 2403 | 65.48 | 58 | passed |

E2 compatibility means the pinned statistical event record passes the GridIron viewer adapter. It does not provide measured player trajectories or establish shared-v1 physical replay conformance.

## Stage B replay and GridIron adapter validation

- Pinned-source replays attempted: 134
- Exact boxscore and score matches with a supported full sequence and passing E2 adapter: 134
- Rejected: 0
- Missing replay outputs: 0

Marketing shortlist (interest is separate from realism):

| Scenario | Seed | Realism | Visual interest | Replay |
|---|---:|---:|---:|---|
| most_representative | 3397 | 77.40 | 51 | passed |
| close_finish | 8597 | 70.32 | 82 | passed |
| comeback | 9503 | 69.00 | 82 | passed |
| defensive_game | 7752 | 68.54 | 96 | passed |
| star_showcase | 7580 | 69.56 | 60 | passed |
| additional_realistic_scenario | 1759 | 68.95 | 63 | passed |
| additional_realistic_scenario | 2362 | 67.44 | 47 | passed |
| additional_realistic_scenario | 7664 | 66.96 | 94 | passed |
| additional_realistic_scenario | 9163 | 66.81 | 98 | passed |
| additional_realistic_scenario | 5053 | 66.78 | 78 | passed |
| additional_realistic_scenario | 2948 | 66.66 | 78 | passed |
| additional_realistic_scenario | 3952 | 66.22 | 69 | passed |
| additional_realistic_scenario | 1422 | 65.66 | 58 | passed |
| additional_realistic_scenario | 4060 | 65.60 | 54 | passed |
| additional_realistic_scenario | 2403 | 65.48 | 58 | passed |

E2 compatibility means the pinned statistical event record passes the GridIron viewer adapter. It does not provide measured player trajectories or establish shared-v1 physical replay conformance.

## Stage B replay and GridIron adapter validation

- Pinned-source replays attempted: 150
- Exact boxscore and score matches with a supported full sequence and passing E2 adapter: 134
- Rejected: 16
- Missing replay outputs: 0

Marketing shortlist (interest is separate from realism):

| Scenario | Seed | Realism | Visual interest | Replay |
|---|---:|---:|---:|---|
| most_representative | 3397 | 77.40 | 51 | passed |
| close_finish | 8597 | 70.32 | 82 | passed |
| comeback | 9503 | 69.00 | 82 | passed |
| defensive_game | 7752 | 68.54 | 96 | passed |
| star_showcase | 7580 | 69.56 | 60 | passed |
| additional_realistic_scenario | 1759 | 68.95 | 63 | passed |
| additional_realistic_scenario | 2362 | 67.44 | 47 | passed |
| additional_realistic_scenario | 7664 | 66.96 | 94 | passed |
| additional_realistic_scenario | 9163 | 66.81 | 98 | passed |
| additional_realistic_scenario | 5053 | 66.78 | 78 | passed |
| additional_realistic_scenario | 2948 | 66.66 | 78 | passed |
| additional_realistic_scenario | 3952 | 66.22 | 69 | passed |
| additional_realistic_scenario | 1422 | 65.66 | 58 | passed |
| additional_realistic_scenario | 4060 | 65.60 | 54 | passed |
| additional_realistic_scenario | 2403 | 65.48 | 58 | passed |

E2 compatibility means the pinned statistical event record passes the GridIron viewer adapter. It does not provide measured player trajectories or establish shared-v1 physical replay conformance.
