# SLC V2

[NFL sequence registry](README.md) · [Architecture](../../architecture/SLC.md)

**Objective and definition:** Frozen V2 statistical full-game model adds participation lineup, snap-count update, kicker-specific field goals, backoff/blocker fixes, season adaptation and RNG v2; source pin distinct from moving slc-v2 branch.

**Frozen identity:** `v2`, source `8a1d9842` in the inspected [executable registry](https://github.com/micahp/legendarypicks/blob/e0d3f603/scripts/nfl_sequence/slc_model_registry.py). The registry specifies exact commit, profile, layer flags, build args, input dependencies and cutoff. Consult the actual package manifest for a specific run; branch head is not package identity.

**Execution and inputs:** [Statistical playcall sampler](https://github.com/micahp/legendarypicks/blob/9a2e8624/scripts/nfl_sequence/slc_playcall.py) and SLC rules/game lifecycle; historical event/yardage, frozen game context and eligible participants; exact inputs depend on the pinned manifest.

**Limits/status:** Current research branch at 9a2e8624 supports personnel-first participation with formation priors; frozen pack must not be relabeled. PBV1/personnel-first incompatible at reviewed head. Research only; no deployment or new parity claim. [Portable runtime evidence](https://github.com/micahp/legendarypicks/blob/e0d3f603/docs/research/SLC-PORTABLE-MODEL-PACK-2026-11-18.md) records initial build/smoke and incomplete full-family parity gates. See [model comparison](../../evaluation/MODEL-COMPARISON.md) for cohort-specific results; absent matched results must remain unknown.

**Evidence:** [Current personnel-first implementation](https://github.com/micahp/legendarypicks/blob/9a2e8624/scripts/nfl_sequence/pre_event.py#L426).

**Moving V2 candidate (2026-11-27):** [`6d2db7e1`](https://github.com/micahp/legendarypicks/commit/6d2db7e1ec0cbebbeba08ce1049f1f64b08a2bad) integrates the HE branch's feasible rotation repair and provenance. The existing target already had HE and a newer PBV1 coupling path, unlike the earlier 9a2e8624 pin; this integration retains that path without validating it. HE defaults on when participation is active and requires the cutoff-scoped snap-count artifact; `--no-participation-entry-current-season` (or `--no-participation-entry-current`) is the HS control. Repaired rotations fill eligible slots deterministically; true shortages stop before a partial lineup reaches participant selection. Replay/ledger record the setting and actual entry shares. Frozen V2 identity remains unchanged. No runtime/forecast acceptance. [Handoff](https://github.com/micahp/legendarypicks/blob/6d2db7e1ec0cbebbeba08ce1049f1f64b08a2bad/docs/research/SLC-SHARED-PARTICIPATION-2026-11-26.md).
