# Playcall M3: development folds A and B, A0 versus A2 (2026-11-02)

Status: research only. Offline development evidence for one candidate arm (A2). It is not a simulator result, and it does
not pass or adopt anything. No 2025 or 2026 outcome was used. No SLC default changed. Nothing was deployed or merged.

## What was run

| Item | Fold A | Fold B |
|---|---|---|
| Train | 2022 | 2022 and 2023 |
| Validate | 2023 | 2024 |
| Reference season for recency weights | 2023 | 2024 |
| Script | `playcall-m3-fold-a-2026-11-02/fold_a.py` (imports from `lp-slc-player-workload-2026-10-30`, commit `d0e495d0`) | `playcall-m3-fold-b-2026-11-02/fold_b.py` (imports `e1_drive` and `playcall_model` from this worktree) |
| Output | `fold_a_results.json` | `fold_b_results.json` |
| Frame equivalence | 67,488 rows, multiset equal to the production frame | 100,823 rows, multiset equal to the production frame (0 symmetric difference) |
| Validation plays and games | 33,836 plays, 272 games | 33,335 plays, 272 games |

Arms (same definitions in both folds, nothing selected on the validation season):
- A0: production score-clock hierarchical logistic, production penalties and tau (penalties chosen on 2023).
- A2: situation cell model over down, distance, field, score and clock, shrunk level by level with K = 20.
- Baselines: 24-cell down by distance rate, and the training league rate.
- Labels: primary (QB scramble counts as a run) and sensitivity (production intent, scramble counts as a dropback).
- Bootstrap: game-clustered, 10,000 draws, seed 20261102 (freeze section 2; see deviation 2).

## Results: A2 minus A0 (negative is better for A2)

| Fold | Labels | Log loss difference (95% CI) | Brier difference (95% CI) | Gate |
|---|---|---|---|---|
| A | primary | +0.0166 (+0.0137 to +0.0196) | +0.0075 (+0.0063 to +0.0087) | fails |
| A | sensitivity | +0.0186 (+0.0155 to +0.0218) | +0.0080 (+0.0068 to +0.0092) | fails |
| B | primary | +0.0116 (+0.0091 to +0.0143) | +0.0053 (+0.0043 to +0.0063) | fails |
| B | sensitivity | +0.0142 (+0.0115 to +0.0170) | +0.0059 (+0.0048 to +0.0069) | fails |

Gate (from the freeze and the spec): A2 advances only if its log loss is at least 0.001 lower than A0, the paired 95% CI
is below zero, and its Brier score is at most 0.001 higher than A0. A2 is higher than A0 on log loss in all four rows, by
0.012 to 0.019. The point estimate fails the gate, so the choice of bootstrap settings cannot change the verdict.

Fold B log loss and Brier, primary labels (validation season 2024):

| Arm | Log loss | Brier |
|---|---:|---:|
| A0 production logistic | 0.5851 | 0.2002 |
| A2 situation cell, K = 20 | 0.5968 | 0.2054 |
| 24-cell down by distance | 0.6227 | 0.2175 |
| League rate | 0.6829 | 0.2449 |

A0 beats both baselines on both folds, and A2 beats both baselines on the primary labels but not A0. The baseline
comparisons are descriptive only, and no gate uses them.

## Verdict for the arms evaluated so far

- A2 does not advance. It is worse than A0 in both development folds and both label definitions.
- Fold B is a stronger check than fold A for A0, because A0's penalties were chosen on 2023 and 2024 was not used for
  that choice. Fold B shows the same direction.
- Multiple comparisons: one candidate arm has been evaluated (A2). The correction procedure has to be fixed before the
  final 2025 evaluation, as the spec requires.

## What is not done

- **A1 (drive and possession volume) has no frozen functional form.** The spec says its form is open, and that a form must
  be written and committed before any fit. No A1 result exists.
- **No simulator run.** The matched-seed comparisons, game-level opportunities, simulated run and dropback rates, drive
  structure, and team opportunity bias (the spec's section 2 and gate for opportunity-count bias) need simulated games.
  A2 exists only as an offline classifier in `fold_a.py` and `fold_b.py`. It is not wired into the SLC run path, so no
  simulated A2 game exists. No archived 10K batch was rerun.
- **Q1 playbook-prior manifest check** (enabled flag, source hashes, nonzero usage) applies only to simulated runs, so it
  has not been checked.
- **No 2025 evaluation** (final retrospective fold) and no 2026 work.

## Deviations and open items

1. **Frozen hash of `playbook_prior.py` is stale.** The freeze (commit `dbac437c`) and the spec pin `playbook_prior.py` at
   `837e6de9ea6816725d64db30ddec31daf66db0cdd8e81b455d7918bdb240b6a0`. The file now has
   `c632cd84c99ba13d144de03d7f8548f494e10032f19475d9bfe1ce10c5ddb72b`, after commit `adbb5b22`. That commit is the
   context-managed open the owner approved under D2(c). The change is behaviour-neutral by test: the consumer tests pass
   8 of 8 on the v2 build, and the file's pre-commit content is recoverable from `adbb5b22^`. Owner decision needed:
   amend the freeze with the new hash (recommended), or revert the file for the M3 runs. This report does not edit the
   freeze.
2. **Bootstrap settings conflict between the two frozen documents.** The spec (section 2) says 2,000 replicates, seed
   `20261028`, using `playcall_uncertainty.py`. The freeze (section 2) says 10,000 replicates, seed `20261102`. Both folds
   used the freeze values. Because the point estimates fail the gate, the verdict does not depend on this choice. The
   owner should still settle which value governs the final evaluation.
3. **Fold A reads its code from a different worktree.** `fold_a.py` imports `e1_drive` and `playcall_model` from
   `/root/lp-slc-player-workload-2026-10-30/scripts/nfl_sequence`. Both files match the freeze hashes
   (`433c02df…` and `b472cb80…`). Fold B is self-contained: it imports only those two modules from this worktree, with the
   same hashes, and copies the helper functions rather than importing fold A (importing fold A would load the other
   worktree's modules).
4. **Fold B reference season is 2024.** The spec does not fix the reference season. Fold B follows fold A's convention, in
   which the reference is the validation season (fold A used 2023). Stated here, not inferred from results.
5. **A1 needs an owner decision.** The spec's section 4 leaves A1's form open. A reasonable candidate is a drive-count
   baseline shrunk toward the league mean (K = 20, as A2), with its opportunity gate evaluated on simulated drives. That is
   a design choice, so it is not taken here.

## Reproduction

```
python3 docs/research/playcall-m3-fold-b-2026-11-02/fold_b.py   # about 30 seconds, reads 2022 to 2024 raw files only
```

Fold A: `python3 docs/research/playcall-m3-fold-a-2026-11-02/fold_a.py` (its results file is the committed one).
