# Repaired-engine single-seed regression, 2026-11-08

At source commit `03fc1ea835b7c2f0a607591e22c83e7d2f50bd21`, the repaired engine ran ARI–SEA seed 1 twice, sequentially, using RNG v2 and the same frozen snapshot and reference inputs on the fast host. Both runs reported a valid completed regulation game, away 27 to home 20. Their entire seed ledger rows and RNG stream roots match; the boxscore exports also have identical file hashes. The boxscore reconciliation passed in both runs.

Both runs recorded 402 fallback events across 21 kinds. All 40 exported players have unknown roster eligibility because the snapshot did not supply it. This is a single-seed determinism and accounting check, not proof of roster eligibility, forecast quality, or general validity. At the time of this run the separate layer-ablation matrix was disabled; a later change added verified control-stream binding.

The [manifest](manifest.json) records hashes of the copied raw batch outputs, seed ledgers, boxscore/realism exports, and logs. Batch-output hashes differ between runs; the matching evidence is the seed row, stream root, and boxscore export, not byte equality of the overall batch files. The source host originals remain at `/tmp/slc-v2-regression-03fc1ea8/`.

The execution used `/tmp/bench/snapshots/2026_09_ARI_SEA.json`, the host's read-only `/root/legendarypicks/backend/data/picks.dev.db`, the `v1_full_stack` profile, the pinned playcall artifact, `/tmp/bench/wl-streaks-2026-11-07.json`, and the five ordinary blocker fixes used by the historical slate. It requested `--rng-protocol v2 --export-boxscores --export-plays --games 1 --seed-start 1`. Exact identities are retained in the ledger headers and batch outputs.

The focused `test_rng_protocol`, `test_slc_outputs`, `test_slc_boxscore_invariants`, `test_slc_football_invariants`, `test_game_legality`, and `test_slc_engine` suites passed 151 tests locally.

## Historical refusal records

The 15 failures in the separate 13-game, 2,600-seed historical regeneration cannot be fully revalidated from its saved outputs: its seed ledgers preserve failure envelopes and its boxscores omit complete drive/play records. Their status remains **unclassified against the current validator**; the original errors are retained in the [Sunday rerun seed results](../slc-sunday-rerun-2026-11-08/seed-results.csv).

Six full records from the older historical batch—ARI–SEA seeds 196 and 197, and GB–NE seeds 64, 96, 100, and 190—each passed all ten stages of the current `game_legality.check`. Those saved records have a different execution identity, so matching seed IDs do not establish that the regenerated failures pass. They remain available under [the earlier refusal investigation](../slc-sunday-failures-2026-11-08/refused-records/).

No full-slate or paired ablation run was performed as part of this check. The fast host had less than 1 GB free after the isolated checkout was prepared.
