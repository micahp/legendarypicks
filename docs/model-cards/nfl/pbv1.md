# PBV1

[NFL sequence registry](README.md) · [Architecture](../../architecture/SLC.md)

**Objective and definition:** Personnel-package sampler on HPV1 historical NFL scrimmage records 2022–25. The cross-season primary target combines RB and FB; SLC integration retains the RB-only package representation. Cell = run/pass, down, distance bucket, red zone; shrink cell counts to parent (play family, down), K=20. Observed support only. Label-only and off controls are distinct; not an executable playbook.

**Frozen identity:** `pbv1 / pbv1-off`, source `8a1d9842` in the inspected [executable registry](https://github.com/micahp/legendarypicks/blob/e0d3f603/scripts/nfl_sequence/slc_model_registry.py). The registry specifies exact commit, profile, layer flags, build args, input dependencies and cutoff. Consult the actual package manifest for a specific run; branch head is not package identity.

**Execution and inputs:** [Statistical playcall sampler](https://github.com/micahp/legendarypicks/blob/9a2e8624/scripts/nfl_sequence/slc_playcall.py) and SLC rules/game lifecycle; optional PBV1 personnel draw rather than a separate physics or outcome engine.

**Limits/status:** Label-only does not enable participation field; PBV1 is not automatically integrated into V1 Complete. Research only; no deployment or new parity claim. [Portable runtime evidence](https://github.com/micahp/legendarypicks/blob/e0d3f603/docs/research/SLC-PORTABLE-MODEL-PACK-2026-11-18.md) records initial build/smoke and incomplete full-family parity gates. See [model comparison](../../evaluation/MODEL-COMPARISON.md) for cohort-specific results; absent matched results must remain unknown.

**Evidence:** [Sampler specification](https://github.com/micahp/legendarypicks/blob/9a2e8624/docs/research/PBV1-SAMPLER-SPEC-2026-11-02.md); [Sampler source](https://github.com/micahp/legendarypicks/blob/50c15508/scripts/nfl_sequence/pbv1_package.py).

