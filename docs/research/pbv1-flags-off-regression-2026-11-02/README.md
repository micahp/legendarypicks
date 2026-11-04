# PBV1 flags-off regression, 2026-11-02: passing

Runs made 2026-11-02 (16:00 to 16:42 local) by `run_all.sh`, copied here from the session scratchpad on 2026-11-04 so the
result can be cited. Rechecked 2026-11-04 with `compare_semantic.py` on these files.

Command: Week 8 frozen snapshot `2026_08_KC_DEN`, `v1_full_stack`, seeds 1 to 3, every run reading the same frozen
reference extract (`scratchpad/frozen/reference-inputs.sqlite`, 498 MB, not copied) instead of the live dev DB.

| Comparison | Seeds with semantic differences |
|---|---|
| `baseline_v1_full_stack_seeds1-3` vs `legacy_v1_orig` (HEAD code, legacy RNG) | 0 of 3; the files are byte-identical (SHA-256 `f22f1200...`) |
| `v2_orig` vs `v2_orig_repeat` (HEAD code, RNG protocol v2, run twice) | 0 of 3; byte-identical |
| `v2_orig` vs `v2_wt_flagsoff` (PBV1 hook code, flags off, RNG v2) | 0 of 3 |

`compare_semantic.py` ignores provenance fields only (code and artifact hashes, the reference fingerprint, the resealed
snapshot hash, the RNG manifest). Everything else in each per-seed record must match.

Why the earlier flags-off run did not match: each seed's random stream is keyed on `snapshot_sha256`, and the batch
reseals the snapshot with the live reference fingerprint. A reference read from a changing DB therefore changes every
seed. Reading a frozen extract removes that. The code edits were not the cause.
