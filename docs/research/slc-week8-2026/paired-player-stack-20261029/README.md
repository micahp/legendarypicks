# Week 8 paired player stack run archive

Archived from `/tmp/lp-slc-week8-10k-20261029` on 2026-11-10. These files preserve the available outputs, pilot summaries, and logs for the Week 8 paired player-stack experiment.

## Run state

The files under `10k/` are **partial runs**, not completed 10,000-seed runs. Each seed ledger starts at seed 1 and ends at the count shown below. The five corresponding primary logs end in `KeyboardInterrupt`; resume logs are preserved alongside them. Do not interpret these as 10,000 completed games per arm.

| Game and arm | Seed records | Outcome counts |
| --- | ---: | --- |
| CLE–PIT, full player stack | 423 | 370 regulation, 13 overtime, 40 blocked |
| CLE–PIT, pooled | 2,095 | 1,972 regulation, 75 overtime, 48 blocked |
| CLE–PIT, team conditioned | 1,036 | 963 regulation, 45 overtime, 28 blocked |
| IND–JAX, full player stack | 409 | 375 regulation, 9 overtime, 25 blocked |
| LAC–LA, full player stack | 417 | 383 regulation, 17 overtime, 17 blocked |

The `pilot-100/` and `pilot-100-dirichlet-fix1/` directories each contain three CLE–PIT arms with 100 seed records per arm, plus their aggregate JSON outputs. Their per-seed status counts are preserved in the ledgers; `pilot-100` full-player-stack includes 12 `simulation_error` outcomes. These pilot outputs are exploratory.

## Provenance

The seed headers identify `as_of` as `2026-10-29T00:02:21Z`, game IDs, source commit `5e6c8de15edffe6aeee983ee0b643b976f188b02`, reference hashes, and play-call artifact hash `27c02afd6d9f6f80a38b3bc7ae278b1efebcc7caa5664688c64c55bc0c698ac7`. The original checkout also had local edits to `pre_event.py` and `test_pre_event.py`; their exact diff is archived at `provenance/local-source-diff.patch` for historical traceability. Current `slc-v2` already has the receiver-population invariant and regression coverage, so this patch is not applied to the branch code.

No complete run manifest or captured full launch command was present in the source checkout. The raw ledgers and all primary/resume logs are retained, but these artifacts alone do not guarantee byte-for-byte rerun reproduction.

`SHA256SUMS` covers every archived file except itself.
