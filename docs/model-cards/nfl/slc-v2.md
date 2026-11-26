# SLC V2

[NFL sequence registry](README.md) · [Architecture](../../architecture/SLC.md)

**Objective and definition:** Frozen V2 statistical full-game model adds participation lineup, snap-count update, kicker-specific field goals, backoff/blocker fixes, season adaptation and RNG v2; source pin distinct from moving slc-v2 branch.

**Frozen identity:** `v2`, source `8a1d9842` in the inspected [executable registry](https://github.com/micahp/legendarypicks/blob/e0d3f603/scripts/nfl_sequence/slc_model_registry.py). The registry specifies exact commit, profile, layer flags, build args, input dependencies and cutoff. Consult the actual package manifest for a specific run; branch head is not package identity.

**Execution and inputs:** [Statistical playcall sampler](https://github.com/micahp/legendarypicks/blob/9a2e8624/scripts/nfl_sequence/slc_playcall.py) and SLC rules/game lifecycle; historical event/yardage, frozen game context and eligible participants; exact inputs depend on the pinned manifest.

**Limits/status:** Current research branch at 9a2e8624 supports personnel-first participation with formation priors; frozen pack must not be relabeled. PBV1/personnel-first incompatible at reviewed head. Research only; no deployment or new parity claim. [Portable runtime evidence](https://github.com/micahp/legendarypicks/blob/e0d3f603/docs/research/SLC-PORTABLE-MODEL-PACK-2026-11-18.md) records initial build/smoke and incomplete full-family parity gates. See [model comparison](../../evaluation/MODEL-COMPARISON.md) for cohort-specific results; absent matched results must remain unknown.

**Evidence:** [Current personnel-first implementation](https://github.com/micahp/legendarypicks/blob/9a2e8624/scripts/nfl_sequence/pre_event.py#L426).

