# Playbook prior manifest check (Q1, 2026-11-02)

Requirement (`PLAYCALL-DECISIONS-2026-11-02.md`, Q1 and `PLAYCALL-M3-FREEZE-2026-11-02.md` section 6): the resolved profile
manifest must show the playbook prior enabled, the enabled-layer flags, the source hashes, and nonzero playbook-prior usage.
A prior that is enabled but unused is a diagnostic failure. The profile was not edited.

## Result

| Check | Expected | Found | Status |
|---|---|---|---|
| `v1_full_stack` resolves `playbook_priors` | enabled (`V1_OPTIONS.playcall_playbook = True`) | enabled | pass |
| Enabled-layer flags, all 18 engine layers | equal to `_expected_layers(V1_OPTIONS)` | no mismatch in 2 manifests | pass |
| Playbook-prior usage | nonzero, status `executed` | 145 applications (LAC_LA seed-196); 129 (IND_JAX seed-4382) | pass |
| Playbook table artifact | same fitted table | `layer_artifact_sha256.playbook_priors` = `44a532480735...` in both | pass |
| Playbook input files | pinned | `playbook:*-2025.json` hashes match across runs | pass |
| `playbook_prior.py` source hash | `837e6de9...` (freeze) | `837e6de9...` in LAC_LA seed-196; `02a6c82c...` in IND_JAX seed-4382 | partial, see below |

## Source hash difference

`playbook_prior.py` has two committed versions: `a56b1a5b` (2026-10-28, hash `02a6c82c...`) and `8b7d5a2e` (2026-10-31,
hash `837e6de9...`, the freeze hash). The only change is the team-code import (`TEAM_CODE` replaced by
`nfl_team_codes.to_pbp_team_code`). The two mappings give identical codes for all 32 playbook team IDs, and the fitted
table hash is the same in both versions. The IND_JAX Week 8 batch ran the older version. The freeze's hash applies to
new runs.

## Limits

- Every manifest checked is a 2026 Week 8 holdout-season run. The staged playbook files cover 2025 only
  (`data/playbooks/research-2026-10-27`), and a 2026 cutoff uses the 2025 files. No pre-2026 run can exercise this prior
  with the files present, so there is no pre-2026 execution evidence.
- Usage counts show the prior was drawn. They do not show that it changes any outcome.
- These 2026 manifests were read after the fact, and the access is logged as entry 14 in `HOLDOUT-EXPOSURE-RECORD-2026.md`.
  Only configuration and count fields were read, not outcomes.
- Fold A does not include the playbook prior. A playbook arm on 2023 would need 2022 to 2023 playbook files, which are not
  staged.
