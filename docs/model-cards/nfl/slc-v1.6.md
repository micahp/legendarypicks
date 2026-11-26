# SLC V1.6 (ALT - cond. pass lbl, xct dist + yrd, + sack suppress. fix)

[NFL sequence registry](README.md) · [Architecture](../../architecture/SLC.md)

**Objective and definition:** Alternative to V1.5's current-season weighting approach: conditional pass labels, exact-distance and yardage conditioning, and a sack-suppression fix. Retains season adaptation and removes the coverage-outcome layer relative to the V1 stack. The shorthand in the title describes the design motivation, not the complete frozen configuration or a claim that sack rates are fully calibrated.

**Frozen identity:** `v1.6`, source `1bb3bd50` in the inspected [executable registry](https://github.com/micahp/legendarypicks/blob/e0d3f603/scripts/nfl_sequence/slc_model_registry.py). The registry specifies exact commit, profile, layer flags, build args, input dependencies and cutoff. Consult the actual package manifest for a specific run; branch head is not package identity.

**Execution and inputs:** [Statistical playcall sampler](https://github.com/micahp/legendarypicks/blob/9a2e8624/scripts/nfl_sequence/slc_playcall.py) and SLC rules/game lifecycle; historical event/yardage, frozen game context and eligible participants; exact inputs depend on the pinned manifest.

**Limits/status:** Before-game-week training cutoff. November 12 comparison exposed excess third/fourth-down states; later fixes need separate evidence. Research only; no deployment or new parity claim. [Portable runtime evidence](https://github.com/micahp/legendarypicks/blob/e0d3f603/docs/research/SLC-PORTABLE-MODEL-PACK-2026-11-18.md) records initial build/smoke and incomplete full-family parity gates. See [model comparison](../../evaluation/MODEL-COMPARISON.md) for cohort-specific results; absent matched results must remain unknown.

**Evidence:** [Bounded V1.6 comparison](https://github.com/micahp/legendarypicks/blob/8d2284b8/docs/research/slc-v1.6-release-comparison-2026-11-12/README.md).

