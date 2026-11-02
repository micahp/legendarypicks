# M3 freeze amendment 1, 2026-11-02

Status: owner-approved amendment. Research only. The original freeze, `PLAYCALL-M3-FREEZE-2026-11-02.md` (commit `dbac437c`), is not edited. Its hashes and values stay as written. This document records two changes and one confirmation.

## 1. playbook_prior.py pin

| Item | Value |
|---|---|
| File | `scripts/nfl_sequence/playbook_prior.py` |
| Hash pinned in the freeze (preserved) | `837e6de9ea6816725d64db30ddec31daf66db0cdd8e81b455d7918bdb240b6a0` (parent commit `adbb5b22^`) |
| Recognized hash (amendment) | `c632cd84c99ba13d144de03d7f8548f494e10032f19475d9bfe1ce10c5ddb72b` (commit `adbb5b22` and current tree) |
| Change | `open(path)` replaced by a context-managed `with open(path) as stream:` in `load()`. Two lines changed, one line removed (see `git show adbb5b22`) |
| Owner ruling | Approved (decision D2(c), 2026-11-02) |

Behaviour equivalence, checked by `playcall-m3-freeze-amendment-1-2026-11-02/check_playbook_prior_equivalence.py`:

| Cutoff | Result | SHA-256 prefix, both versions |
|---|---|---|
| 2023 | identical | `77ab72e594d0fd3d` |
| 2024 | identical | `c683c870d7e55df6` |
| 2025 | identical | `79ca57371f4c3d34` |

Each comparison pickles the full `load(cutoff)` output of the parent and of the current file and compares the bytes. The consumer tests (`test_playbook_prior.py`, `test_playbook_prior_historical.py`, `test_playbook_prior_compact.py`) pass 14 of 14.

The amendment recognizes the new hash for the M3 runs. The old hash stays on record. The original freeze is not rewritten.

## 2. Bootstrap settings for the final evaluation

The spec (`PLAYCALL-ABLATION-SPEC-M3-2026-11-02.md`, section 2) said 2,000 replicates with seed `20261028`. The freeze (section 2) said 10,000 replicates with seed `20261102`. The development folds used the freeze values.

Owner ruling: the final evaluation uses the already selected **10,000 game-clustered bootstrap draws, seed 20261102**. The spec's 2,000 and `20261028` do not govern M3 and are superseded for it. The spec is not edited.

The development verdict does not depend on this choice: A2's point estimates fail the gate in both folds.

## 3. Confirmation: A2

A2 (the situation cell model, K = 20) remains rejected in its current form. Fold A (2023) and fold B (2024) both show A2 worse than A0 on log loss (+0.0166 and +0.0116).

## What this amendment does not change

- No SLC default. No deployment. No production database write.
- No archived 10K batch is rerun.
- No 2026 result is read for development, selection or evaluation.
- The M3 thresholds, A0 control, and the 2025 retrospective rule are unchanged.
