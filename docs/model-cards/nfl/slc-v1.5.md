# SLC V1.5

[NFL sequence registry](README.md) · [Architecture](../../architecture/SLC.md)

**Objective and definition:** Full-stack historical sampler; distinct frozen source policy from V1. A season-adaptation N0=4 control appears in the November 12 bounded comparison; do not assume every V1.5 package has that configuration.

**Frozen identity:** `v1.5`, source `2eab8a89` in the inspected [executable registry](https://github.com/micahp/legendarypicks/blob/e0d3f603/scripts/nfl_sequence/slc_model_registry.py). The registry specifies exact commit, profile, layer flags, build args, input dependencies and cutoff. Consult the actual package manifest for a specific run; branch head is not package identity.

**Execution and inputs:** [Statistical playcall sampler](https://github.com/micahp/legendarypicks/blob/9a2e8624/scripts/nfl_sequence/slc_playcall.py) and SLC rules/game lifecycle; historical event/yardage, frozen game context and eligible participants; exact inputs depend on the pinned manifest.

**Limits/status:** Registry lists same base layers and pre-season cutoff; configuration and manifest identify any adaptation. Research only; no deployment or new parity claim. [Portable runtime evidence](https://github.com/micahp/legendarypicks/blob/e0d3f603/docs/research/SLC-PORTABLE-MODEL-PACK-2026-11-18.md) records initial build/smoke and incomplete full-family parity gates. See [model comparison](../../evaluation/MODEL-COMPARISON.md) for cohort-specific results; absent matched results must remain unknown.


