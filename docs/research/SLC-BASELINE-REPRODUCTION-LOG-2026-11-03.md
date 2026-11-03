# SLC baseline reproduction log, 2026-11-03

Status: open. The committed baseline (`73b3becc`) reproduces its own behaviour on the frozen snapshot. The current working
tree (`slc-v1.5` plus uncommitted overlay) has not reproduced the baseline's game under any run so far. This file records
each attempt, what it showed, and what it ruled out, so the next attempt starts from the record and not from memory.

Frozen snapshot: `docs/research/slc-week8-2026/snapshots/2026_08_BAL_BUF.json`. Seed 1. Artifact
`docs/research/SLC-PLAYCALL-ARTIFACT-v1.json`. Streak file `wl-streaks-2026-10-29.json`. Profile `v1_full_stack`.

## Code under test

- **Baseline:** committed `73b3becc`, extracted to a scratch tree.
- **Current:** `slc-v1.5` working tree with uncommitted edits to `e2_reference.py`, `slc_engine.py`, `run_slc_game.py`,
  `simulate_pregame_batch.py` and `team_tendency.py`. Two untracked files (`team_season_adapt.py`,
  `current_season_adapt.py`) are not imported when the adaptation flag is off.

## Attempts

| # | Attempt | Result | What it ruled out or showed |
|---|---|---|---|
| 1 | Local run, flags off, live DB: baseline vs current | Snapshot digest `7513d942…` (baseline, Python 3.8) vs `c6efa23d…` (current) | Live DB is not the cause. Baseline digest reproduces on the frozen snapshot. |
| 2 | Local run, frozen snapshot: baseline vs current | `7513d942…` vs `0b016c93…` | The frozen snapshot is not the cause. The difference exists on identical inputs. |
| 3 | Fast host (Python 3.12), frozen snapshot | Baseline `43a59ca8…`, current `0a36b5c8…` | Same difference on a second machine and Python version. Pinned hashes are Python 3.8 only. |
| 4 | Bisect with rebuilt trees: `team_tendency.py` alone | Matches baseline (`bis-C`) | `team_tendency.py` does not change the result on its own. |
| 5 | Bisect: `e2_reference.py` plus `team_tendency.py` | Differs (`bis-B`, `0037ef65…`) | The loader change is involved, but the first attempt did not isolate it. |
| 6 | Bisect: `e2_reference` and `slc_engine` with the new edits | Failed at load (`TypeError`: unexpected keyword `playcall_season_adapt`) | A file-by-file swap is invalid while the other overlay file still passes the new keyword. |
| 7 | Play-level probe, both trees, seed 1 | Baseline: blocked at decision 58 (`qb_scramble_source_rows_missing`, `slc_playcall.py:528`). Current: complete regulation, 146 decisions | The two trees differ in game behaviour, not only in seed. First logged draw (the toss) differs. |
| 8 | Snapshot digest: the seed is `sha256(seed:digest)` | Digest differs: baseline `85fcaf…`, current `1bff5b…` | The seed difference is produced after load. `run_slc_game` reseals the snapshot after `load_reference`. |
| 9 | Reference pool dump at play entry (pool, kickoff, kick table, participants, position usage, missed FG, blocked kick) | All seven components identical in both trees | The data the engine samples from is the same. |
| 10 | Full fingerprint blob diff (340,349 blobs) | One blob differs: `contextual-sampler`, the `integration_code_sha256` of the four overlay files | The fingerprint difference is a code hash, not data. |
| 11 | Attribute dump of the reference and the sampler, two levels deep | No attribute differs except `model_inputs.sha256` | The sampler's state and manifests match. The difference is in code, not state. |
| 12 | Same seed forced to the baseline's model seed (`12290881310983089595`), current tree | Complete regulation, 145 decisions (33-12). Still not the baseline | Seed alone does not explain the behaviour difference. |
| 13 | `PYTHONHASHSEED=0` in both trees | Baseline blocked at 58 (17-7). Current complete, 146 (34-13) | Hash randomisation is not the cause. |
| 14 | Single-file swap, `team_tendency.py` committed, seed forced | Complete regulation, 145 decisions (33-12) | Not `team_tendency.py`. |
| 15 | Single-file swap, `run_slc_game.py` committed, seed forced | Complete regulation, 146 decisions (34-13) | Not `run_slc_game.py` by itself. |
| 16 | Single-file swap, `e2_reference.py` committed, `slc_engine.py` kwarg removed, seed forced | Complete regulation, 132 decisions (19-34). Not the baseline | Not `e2_reference.py` by itself. |
| 17 | Single-file swap, `slc_engine.py` committed, `run_slc_game.py` kwargs removed, seed forced | Complete regulation, 149 decisions (16-23). Not the baseline | Not `slc_engine.py` by itself. |

Each single-file swap gives a different complete game (145, 146, 132, 149 decisions), so the current tree's behaviour
depends on the full set of overlay files together. Removing any one of them does not restore the baseline's blocked game.
The baseline's runtime files were also checked: `docs/fixtures` is identical to the repro clone's, and `e2_reference.py`
is the committed file, so the scratch tree is not missing a runtime input.

| 18 | Diagnostic only: current tree, with the sampler's `integration_code_sha256` replaced by the committed values, seed 1 (no forced seed). The actual hashes are kept in a separate record | Digest at entry `85fcaf81…` (equal to the baseline). Blocked at decision 58, score 17-7. All 58 events identical to the baseline's trace | The divergence is caused by the code-provenance hash feeding the snapshot digest. No football-behaviour difference remains on this game. |

**Correction to attempts 12 to 17.** Those runs forced only `game_state`'s model seed. `pre_event.choose` (line 122) also seeds
participant selection from `snapshot_sha256`, the game seed and the decision index. So a single-file revert changed the
snapshot hash and with it the participant draws. Those results do not show which file changes football behaviour. Attempt
18 is the controlled comparison: it changes only the provenance hash and leaves every seeded input as in the baseline.

## What is established

- The baseline's blocked game is stable across runs on the fast host and locally.
- The current tree's difference is not in the data the engine samples from (attempts 9 to 11).
- The seed difference is produced by the code hash of the overlay files, and it also changes every draw (attempts 8 and 10).
- Forcing the seed does not restore the baseline (attempt 12). Neither does pinning the hash seed (attempt 13).
- Restoring any one of the four overlay files to its committed version does not restore the baseline (attempts 14 to 17).
- The baseline's runtime inputs match the repro clone (fixtures identical, `e2_reference.py` committed).

- The divergence is caused by the code-provenance hash inside the snapshot digest. Normalizing only that hash makes the
  digest, the seeds and the full 58-event trace identical to the baseline (attempt 18).

## What is not established

- Whether the current tree matches the baseline on any game other than BAL/BUF seed 1. Attempt 18 covers one game and
  one seed.
- Whether the provenance normalization is the right permanent design. The paste proposes separating semantic model
  identity (used for RNG seeding) from actual code hashes (kept for audit). That is a seeding-contract change and needs
  its own decision, versioned so archived V1 results are not rewritten.
- Whether the change lies in the sampler's weight computation (`slc_playcall.py` around line 500 to 530) or in the
  order of calls. The attribute dump does not show a state difference, so a code path must differ.
- Whether the baseline's Python 3.8 hash (`7513d942…`) reproduces on Python 3.12. It does not: the fast host gives
  `43a59ca8…` for the baseline, so only the Python 3.8 hash is pinned.

## Next

1. Extend attempt 18 to more games and seeds, with the same normalization, before calling the tree equivalent to V1.
2. Decide the permanent seeding contract (separate semantic identity from code provenance, versioned, with a regression
   test that V1.5 with adaptation off gives the same trace as V1). This needs owner approval because it changes how
   seeds are derived.
3. Do not ship the normalized hash as provenance. It is diagnostic only.
