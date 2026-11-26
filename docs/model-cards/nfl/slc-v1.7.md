# SLC V1.7

[NFL sequence registry](README.md) · [Architecture](../../architecture/SLC.md)

**Objective and definition:** V1.6 candidate with penalty proposal and enforcement under a research ruling policy.

**Frozen identity:** `v1.7`, source `1ca59e0d` in the inspected [executable registry](https://github.com/micahp/legendarypicks/blob/e0d3f603/scripts/nfl_sequence/slc_model_registry.py). The registry specifies exact commit, profile, layer flags, build args, input dependencies and cutoff. Consult the actual package manifest for a specific run; branch head is not package identity.

**Execution and inputs:** [Statistical playcall sampler](https://github.com/micahp/legendarypicks/blob/9a2e8624/scripts/nfl_sequence/slc_playcall.py) and SLC rules/game lifecycle; historical event/yardage, frozen game context and eligible participants; exact inputs depend on the pinned manifest.

**Limits/status:** Research penalty fit, not release-validated in inspected portable pack report. Research only; no deployment or new parity claim. [Portable runtime evidence](https://github.com/micahp/legendarypicks/blob/e0d3f603/docs/research/SLC-PORTABLE-MODEL-PACK-2026-11-18.md) records initial build/smoke and incomplete full-family parity gates. See [model comparison](../../evaluation/MODEL-COMPARISON.md) for cohort-specific results; absent matched results must remain unknown.

**Evidence:** [16-type penalty enforcement](https://github.com/micahp/legendarypicks/blob/575d97f1/docs/research/SLC-V1.7-PENALTY-16-TYPE-ENFORCEMENT-2026-11-12.md).

