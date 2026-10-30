# QB run-role style: cutoff-safe holdout evaluation

**Purpose:** Test whether the opt-in player-versus-team QB run-role adjustment improves conditional run-role probabilities outside its training data.

**Disposition:** The aggregate point estimates improve slightly in both windows, but the game-clustered 95% intervals include zero. For Jacoby Brissett in 2026 Weeks 1–7, the layer lowers the predicted QB share below the observed rate. This diagnostic does not validate the layer as a correction to SLC's full-game rushing distribution.

## Method and cutoff

The first window fits 2022–2024 regular-season PBP, then scores 2025. The target-season window fits 2022–2025 and scores only 2026 Weeks 1–7. The evaluator verifies the source hashes against the workload-reference v3 manifest before reading the five PBP files and player identity table.

An eligible observation is an ordinary team run attempt with a unique primary QB identified by that team-game's dropback leader. Explicit scrambles, QB dropbacks, penalties, two-point plays, relief-QB runs, and games with an ambiguous primary QB are excluded. The outcome is whether the primary QB carried the ball.

The control probability is the team's historical QB-run share by situation, shrunk toward the league situation rate. The style probability applies `qb_run_role_style` to that same control probability. This isolates the player-versus-team adjustment, but it does not use SLC's decision-label B probability or simulate a full game. The evaluation is therefore a conditional role-rate diagnostic, not the paired same-seed engine ablation still required for final acceptance.

## Aggregate results

| Window | Fit → evaluation | Eligible run observations | QB runs | Control Brier | Style Brier | Difference (style − control) | Game-cluster 95% interval | Log-loss difference |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2025 holdout | 2022–2024 → 2025 | 12,815 | 639 | 0.043723 | 0.043493 | −0.000229 | [−0.000508, 0.000054] | −0.001133 |
| 2026 Weeks 1–7 | 2022–2025 → 2026 W1–7 | 5,056 | 235 | 0.039945 | 0.039621 | −0.000324 | [−0.000823, 0.000162] | −0.002121 |

Both windows favor the style adjustment by the Brier point estimate, but neither interval excludes no change. This is weak evidence of aggregate improvement, not a reliable calibration result. In the 2026 window, 4,282 of 5,056 observations received a non-neutral adjustment; 774 had no player history. The 2025 window had 8,522 adjusted observations out of 12,815.

## Jacoby Brissett

| Window | Eligible team-run observations | QB runs | Observed QB-run rate | Mean team-rate probability | Mean style probability | Player history support |
|---|---:|---:|---:|---:|---:|---|
| 2025 holdout | 217 | 13 | 5.99% | 10.15% | 10.15% | No Arizona history in the 2022–2024 fit; no adjustment |
| 2026 Weeks 1–7 | 168 | 16 | 9.52% | 8.70% | 6.65% | 12 all-context, 64 exact-cell, 92 shrunk exact-cell observations |

In the 2026 sample, the control implies about **14.6** Brissett carries across these 168 ordinary run opportunities; the style adjustment implies about **11.2**, while the observed total is **16**. These are expected role credits within the observed team-run opportunities, not total rushing attempts or full-game SLC projections. The 2026 sample covers seven games, so the result is preliminary, but it shows that the current player-specific adjustment can push Brissett's projected role below his observed rate.

## Interpretation and next validation

The prototype should remain opt-in. It has not demonstrated a statistically clear aggregate benefit, and the Brissett target window shows a directional underprediction in mean QB role share. The next acceptance step is a paired, same-seed, full-game SLC comparison with the `qb_run_role_style` layer toggled alone, reporting QB carries, scrambles, non-scramble runs, yards, game-level tails, and reconciliation failures. Do not use this evaluation to hard-cap workloads or change SLC defaults.

## Reproduction and provenance

Run from the research checkout:

```sh
python scripts/nfl_sequence/evaluate_qb_run_role_style.py \
  --data-dir /root/gridiron-playbooks-research/data/raw \
  --reference-manifest docs/research/player-workload-reference-2026-10-30-v3/manifest.json \
  --out docs/research/qb-run-role-style-holdout-2026-10-30/RESULTS.json
```

`RESULTS.json` contains per-QB scores, game-cluster bootstrap output, year-level row coverage, input hashes, the reference-manifest hash, and evaluator/model-code hashes.
