# Matched playbook-input run, 2026-10-29

This compares the decision layer with the fixed prior-season player-share adapter, with and without `--playcall-playbook`. Both arms used the same current source tree, frozen CAR-GB Week 8 snapshot, artifact, observed reference, decision filter, and seeds 1 to 100. Dirichlet shares were off in both arms.

| Arm | Valid games | Mean total points | Mean home margin | Blocked |
|---|---:|---:|---:|---:|
| Decision + fixed player shares | 100/100 | 50.24 | +2.60 | 0 |
| Same + playbook input | 98/100 | 49.48 | +2.30 | 2 |

There were 98 paired valid seeds. Playbook-on minus off averaged -0.86 total points per game (seed-level SE 1.76) and -0.47 home-margin points (SE 1.80). The paired differences are small relative to their seed uncertainty in this one matchup; this is not a calibration estimate or a default decision. The two blocked playbook seeds were 5 and 68, for an unresolved field-goal outcome and a missing run-outcome cell.

The share-distribution model is not evaluated by this pair. It uses the fixed-share adapter in both arms, and the decision-row filter stays enabled in both. No default changed. The row filter, playbook default, pace excess, and red-zone gap remain separate review items.

The run inputs, flags, per-seed outputs, hashes, and source fingerprint are in [SLC-PLAYBOOK-MATCHED-2026-10-29.json](SLC-PLAYBOOK-MATCHED-2026-10-29.json). The run reported base commit `000ff3fa` with a dirty worktree; source files were committed unchanged at `567845ff` for reproducibility.
