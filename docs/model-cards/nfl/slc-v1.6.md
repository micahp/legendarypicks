# SLC V1.6 (ALT - cond. pass lbl, xct dist + yrd, + sack suppress. fix)

[NFL sequence registry](README.md) · [Architecture](../../architecture/SLC.md)

**Objective and definition:** Alternative to V1.5's current-season weighting approach: conditional pass labels, exact-distance and yardage conditioning, and a sack-suppression fix. Retains season adaptation and removes the coverage-outcome layer relative to the V1 stack. The shorthand in the title describes the design motivation, not the complete frozen configuration or a claim that sack rates are fully calibrated.

**Frozen identity:** `v1.6`, source `1bb3bd50` in the inspected [executable registry](https://github.com/micahp/legendarypicks/blob/e0d3f603/scripts/nfl_sequence/slc_model_registry.py). The registry specifies exact commit, profile, layer flags, build args, input dependencies and cutoff. Consult the actual package manifest for a specific run; branch head is not package identity.

**Execution and inputs:** [Statistical playcall sampler](https://github.com/micahp/legendarypicks/blob/9a2e8624/scripts/nfl_sequence/slc_playcall.py) and SLC rules/game lifecycle; historical event/yardage, frozen game context and eligible participants; exact inputs depend on the pinned manifest.

**Limits/status:** Before-game-week training cutoff. November 12 comparison exposed excess third/fourth-down states; later fixes need separate evidence. Research only; no deployment or new parity claim. [Portable runtime evidence](https://github.com/micahp/legendarypicks/blob/e0d3f603/docs/research/SLC-PORTABLE-MODEL-PACK-2026-11-18.md) records initial build/smoke and incomplete full-family parity gates. See [model comparison](../../evaluation/MODEL-COMPARISON.md) for cohort-specific results; absent matched results must remain unknown.

**Evidence:** [Bounded V1.6 comparison](https://github.com/micahp/legendarypicks/blob/8d2284b8/docs/research/slc-v1.6-release-comparison-2026-11-12/README.md).

**Development integration (2026-11-27):** [`14e26d0b`](https://github.com/micahp/legendarypicks/commit/14e26d0b509b6cd9254d523bdeb0c6e0b6582648) integrates the V1.6 geometry candidate (off by default), strict observed overtime preflight, verified snapshot validity gate, and preserves default box-score export. The geometry flag is recorded in replay commands, run ledger and resealed model snapshot. A completed game on an unverified snapshot is not certified as a valid forecast by this branch. Frozen source and packages above are unchanged. Three focused source-extracted Python checks passed; repository suites, original stopped-seed full-game replays, portable-pack integration and matched distributions remain unverified.

**Portable memory correction (development):** See [shared historical-pool format](../../architecture/SLC.md#portable-historical-pool-representation-development). The portable codec preserves the existing pool/source_pool alias for new schema-2 artifacts. The frozen `1bb3bd50` engine and original package hashes are unchanged. The exact V1.6 package must be repacked and the original 500-seed cohort matched before adopting the new artifact; load RSS improvement and full-game parity remain unmeasured.

**Shared workers (development):** The [portable runtime](../../architecture/SLC.md#shared-worker-execution-development) can fork seed workers from one decoded reference per matchup and stream optional game records; the original model identity remains unchanged. No full-size V1.6 multiworker parity or memory measurement has been executed.
