# Cutoff-safe player workload reference v2

This release corrects the named-player examples in the prior workload reference. The old hard-coded IDs for DK Metcalf and Ja'Marr Chase resolved to Terry McLaurin and Puka Nacua. V2 resolves examples from the pinned nflverse player names and positions, adds Tyler Allgeier as a lower-volume RB example, and fails on missing or ambiguous identities. All five non-example benchmark tables are byte-identical to v1; historical distribution results did not change.

## Cutoff and coverage

The 2026 Week 8 forecast cutoff is **2026 Week 7**. The last included game date is 2026-10-26. The artifact includes regular-season windows for train 2022–2024, holdout 2025, multi-season 2022–2025, and target 2026 Weeks 1–7.

Historical eligibility uses offensive participation: 1,087 games and 40,899 player-game pairs. Target-season 2026 participation is event-derived from PBP and explicitly a lower bound, not a complete snap-eligible denominator. The manifest records all 13 source file hashes and hashes for every output.

The 2025 published-source reconciliation has a disclosed receiving-yard difference: published total 122,413 versus PBP total 122,418 (+5 PBP yards). Two player-level differences offset partially: ID `00-0034827` is 682 published versus 678 PBP; `00-0036252` is 784 versus 793. Other checked 2025 player totals reconcile. See `published_source_reconciliation.csv` for details.

## QB style references

Rates below are per player-game in the multi-season 2022–2025 window. The player-game sample size is shown; these are empirical reference summaries, not action caps.

| Archetype / QB | Games | Rush att. | Rush yds | Scrambles | Designed QB runs | Kneels | Spikes |
|---|---:|---:|---:|---:|---:|---:|---:|
| Pocket: Kirk Cousins | 49 | 1.67 | 2.63 | 0.41 | 0.67 | 0.59 | 0.24 |
| Pocket: Matthew Stafford | 57 | 1.63 | 2.04 | 0.51 | 0.37 | 0.75 | 0.12 |
| Pocket: Jared Goff | 68 | 1.69 | 2.87 | 0.60 | 0.32 | 0.76 | 0.15 |
| Mobile: Lamar Jackson | 58 | 8.03 | 49.12 | 2.90 | 4.41 | 0.72 | 0.16 |
| Mobile: Jayden Daniels | 24 | 8.58 | 48.71 | 4.58 | 3.33 | 0.67 | 0.17 |
| Mobile: Jalen Hurts | 63 | 9.16 | 38.35 | 2.70 | 5.48 | 0.98 | 0.05 |
| Mobile: Josh Allen | 67 | 6.70 | 35.76 | 2.84 | 3.09 | 0.78 | 0.07 |
| Brissett reference | 41 | 2.56 | 12.00 | 1.37 | 0.95 | 0.24 | 0.12 |

Brissett’s 2025 holdout alone has 14 games: 2.71 carries and 12.00 rushing yards per game, including 1.57 explicit scrambles and 1.00 designed QB run per game. Through 2026 Week 7, seven event-observed games show 3.71 carries, 11.43 yards, 1.00 scramble, and 2.29 designed runs per game. That small target sample is not a stable season estimate.

`qb_scrambles` uses the explicit PBP `qb_scramble` flag. `designed_qb_runs` excludes scrambles, kneels, and dropback plays; it includes detected QB sneaks. Sneaks are identified by a description regex and are a heuristic, not an official field. Kneels and spikes use the PBP `qb_kneel` and `qb_spike` flags. Throwaways are identified from the description and are a lower bound. Total rushing attempts still include scrambles, sneaks, and kneels for box-score comparison.

## Named dated examples

`ARCHETYPE-EXAMPLES.md` lists dated RB, receiver, pocket-QB, and mobile-QB game examples with actual usage and explicit event decomposition. `named_player_game_examples.csv` contains the top five nonzero games for each named metric. Player identity is resolved by exact pinned-source display name and position; a repeated name at a different position cannot silently substitute another athlete.

## Provenance and use

The benchmark is historical evidence for workload distributions, role comparisons, and model calibration. Historical maxima are review boundaries, not legal or physical caps. The 2026 Week 8 target data is included only through Week 7. Rebuild with:

```sh
python scripts/nfl_sequence/build_player_workload_reference.py \
  --data-dir /root/gridiron-playbooks-research/data/raw \
  --out-dir docs/research/player-workload-reference-2026-10-30-v2
```

The corrected named examples and identity policy are covered by six builder unit tests. V1 is retained as the original committed output; use v2 for player-specific examples.
