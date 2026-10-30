# Cutoff-safe player workload reference v3

V3 corrects a false-zero QB-sneak distribution in v2. The source has no structured QB-sneak field, and the pinned play descriptions produced no QB-sneak label matches. V3 therefore marks `qb_sneaks` unavailable instead of reporting zero workload. It renames `designed_qb_runs` to `qb_non_scramble_runs`, which accurately describes the residual class and may include unlabeled sneaks.

All non-sneak player and position observations are unchanged from v2. I compared 17,285 player-metric rows and 115 position-metric rows after mapping the renamed residual metric; the values match. The published-source reconciliation, situational usage, and team-game usage CSVs are byte-identical. V1 and v2 remain intact.

## Cutoff and coverage

The forecast cutoff is 2026 Week 7, immediately before the Week 8 target. The inputs cover regular seasons 2022–2025 and 2026 Weeks 1–7. Historical eligibility uses offensive participation: 1,087 games and 40,899 player-game pairs. Target-season participation is derived from PBP participant IDs and is explicitly a lower bound. The manifest pins all 13 source files and hashes every machine-readable output.

## QB rushing evidence

Rates below are per player-game. The 2022–2025 entries use the multi-season reference; the Brissett 2025 and 2026 rows show the holdout and target windows separately.

| QB | Window | Games | Carries | Rush yards | Explicit scrambles | Non-scramble QB runs* | Kneels | Spikes |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Kirk Cousins | 2022–2025 | 49 | 1.67 | 2.63 | 0.41 | 0.67 | 0.59 | 0.24 |
| Matthew Stafford | 2022–2025 | 57 | 1.63 | 2.04 | 0.51 | 0.37 | 0.75 | 0.12 |
| Jared Goff | 2022–2025 | 68 | 1.69 | 2.87 | 0.60 | 0.32 | 0.76 | 0.15 |
| Lamar Jackson | 2022–2025 | 58 | 8.03 | 49.12 | 2.90 | 4.41 | 0.72 | 0.16 |
| Jayden Daniels | 2022–2025 | 24 | 8.58 | 48.71 | 4.58 | 3.33 | 0.67 | 0.17 |
| Jalen Hurts | 2022–2025 | 63 | 9.16 | 38.35 | 2.70 | 5.48 | 0.98 | 0.05 |
| Josh Allen | 2022–2025 | 67 | 6.70 | 35.76 | 2.84 | 3.09 | 0.78 | 0.07 |
| Jacoby Brissett | 2022–2025 | 41 | 2.56 | 12.00 | 1.37 | 0.95 | 0.24 | 0.12 |
| Jacoby Brissett | 2025 holdout | 14 | 2.71 | 12.00 | 1.57 | 1.00 | 0.14 | 0.07 |
| Jacoby Brissett | 2026 Weeks 1–7 | 7 | 3.71 | 11.43 | 1.00 | 2.29 | 0.43 | 0.29 |

\* `qb_non_scramble_runs` counts a QB rush with a rushing attempt when the PBP flags it as neither a scramble, kneel, nor dropback. Sneaks remain inside this residual; it is not a confirmed designed-run count.

### Experimental simulator component

The research branch exposes `qb_run_role_style` as an opt-in layer requiring both the QB decision model and decision labels. For ordinary run decisions, it adjusts the QB role's log odds by the named QB's historical non-scramble run share relative to the team rate, with 20-opportunity shrinkage. It is off in the standard SLC profile. This is a bounded prototype, not a validated workload correction: it does not impose carry caps, and a same-seed outcome ablation is still needed before claiming that it fixes Brissett's projected tail.

### Sneak classification status

The nflverse PBP dictionary documents `qb_kneel`, `qb_spike`, and `qb_scramble` flags, but no structured `qb_sneak` flag. Its descriptions are free text. The v3 builder’s pinned regular-season descriptions yielded **zero** matches for the QB-sneak label pattern, across **3,777** non-scramble QB rush rows in the training, holdout, and target windows. That is zero detected labels, not evidence that no sneaks occurred. V3 writes null statistics and `unavailable_source_classification` for every QB-sneak row.

| Season/window | Non-scramble QB run residual rows | Sneak description matches | Short-yardage middle-run proxy rows |
|---|---:|---:|---:|
| 2022 training | 985 | 0 | 207 |
| 2023 training | 906 | 0 | 228 |
| 2024 training | 887 | 0 | 187 |
| 2025 holdout | 747 | 0 | 191 |
| 2026 Weeks 1–7 target | 252 | 0 | 96 |

The short-yardage middle-run proxy is not a confirmed sneak label. It is reported only to show how many residual rows satisfy that situational filter.

The [`nflverse PBP release`](https://github.com/nflverse/nflverse-data/releases/tag/pbp) and [nflfastR PBP field dictionary](https://nflverse.r-universe.dev/nflfastR/nflfastR.pdf) are the pinned source references. The dictionary describes run plays as including scrambles and separately documents kneels, spikes, and scramble flags; it does not define a sneak indicator.

## Dated usage examples

`ARCHETYPE-EXAMPLES.md` preserves dated examples for RB workload roles, high-target receivers, pocket QBs, and mobile QBs. QB examples distinguish explicit scrambles and kneels. Their remaining rushing carries use the residual definition above, so they must not be read as exact designed-run versus sneak labels.

## Provenance and rebuild

The v3 machine-readable distributions are in this directory. Rebuild from the same hash-pinned inputs with:

```sh
python scripts/nfl_sequence/build_player_workload_reference.py \
  --data-dir /root/gridiron-playbooks-research/data/raw \
  --out-dir docs/research/player-workload-reference-2026-10-30-v3
```

Historical maxima remain review boundaries, not legal or physical caps. V3 preserves the multi-season and holdout evidence while making the missing QB-sneak classification explicit.
