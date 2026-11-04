# SLC v2 Milestone 5 and Milestone 6 (prospective): what is blocked, and why, 2026-11-02

Status: blocker record. These two steps cannot be completed inside the research scope of this session without owner decisions. Nothing here changes SLC behaviour. No simulator run. No 2026 result read.

## Milestone 5: integrate the adopted components behind research flags

Adopted components to integrate: C1 (P1 pass share), C2 (P2 target share), and the PBV1 package sampler.

What the simulator pins. `scripts/nfl_sequence/slc_config.py` lists the code file for each layer and pins its hash. The layers that the adopted components would touch are:

| Component | Layer in the pinned config | Pinned code file | What the change would touch |
|---|---|---|---|
| C2 P2 target share | `fixed_player_target_carry_shares` | `player_shares.py` | `load()` builds prior-season shares; `weight()` returns them. An as-of in-season estimate would replace this table. |
| C2 P2 target share (alternative) | `dirichlet_player_target_carry_shares` | `share_distributions.py`, `pre_event.py` | A different target-share layer already in SLC. P2 would need comparing with it. |
| C1 P1 pass share | `score_clock_playcalling` | `slc_playcall.py`, `playcall_model.py` | The dropback probability (`_dropback_probability`, `sample`) is where a team pass tendency would enter. |
| PBV1 package sampler | `formation_personnel_outcomes` (formation layer) | `formation_layer.py` | Not yet read in detail. The sampler is a package-level distribution, so the hook is probably the personnel draw. |

Why this blocks. Adding the components means editing pinned files. The owner has already set the pattern: a freeze amendment records each approved hash change (the `playbook_prior.py` amendment, `PLAYCALL-M3-FREEZE-AMENDMENT-1-2026-11-02.md`). Each new hook needs the same treatment. The amendment rules are owner decisions, not mine to make.

Decisions needed before Milestone 5 can start:

1. **Freeze amendment for pinned files.** Approve flag-gated hooks in `player_shares.py` and `slc_playcall.py` (with the default unchanged and the old hash preserved), or require new research-only modules that the flagged path calls instead.
2. **Comparator for C2.** Compare P2 against the existing fixed-share layer only, or also against the Dirichlet share layer already in SLC.
3. **Scope of the first paired batch.** A smoke on one historical game, then a small paired batch of seeds. The paired full-game batch needs a compute budget: the box has 5.8 GB RAM and a root disk at 99%.

Work that does not need the decisions and is not started: reading `slc_playcall.py` and `pre_event.py` in full, and deciding the exact hook points. Starting that reading now would be exploratory; the decisions above determine which hook points matter.

## Milestone 6, prospective 2026

The plan requires that prospective 2026 evidence be locked (model version, inputs, predictions and hashes) before kickoff. The holdout-exposure record applies, and the owner's standing rule is that prospective snapshots are authorized and logged explicitly.

Not done: no prospective 2026 snapshot has been locked. That needs explicit authorization for the prospective snapshot, and a decision on which weeks and which candidates are locked. The plan's rule is that 2026 is not read for development or selection, so this cannot start from the current state.

## What this means for the plan's stopping condition

Milestones 1 to 4 and 7 are complete as research records. Milestone 6's 2025 retrospective is complete for the frozen candidates. Milestone 5 and the prospective part of Milestone 6 are blocked on the owner decisions above. The plan's stopping condition therefore cannot be satisfied by more work in this session without those decisions.
