# LAC–LA seed recovery and ledger status reconciliation

The two simulation errors from run `research-8b7d5a2e-2026-10-31` were replayed with the source-row filter committed at `f1c82e553698830590b75d9402d57eeb21bb306d`.

The source error was a completed-pass row with inconsistent yardage: `2022_16_LAC_IND`, play 3371, has 13 passing yards and 12 receiving yards. The patched source pool excludes that row. Both replays used the original frozen LAC–LA snapshot, cutoff, database, playcall artifact, streak input, and seed-specific settings. Box-score export was enabled.

| Seed | Recovery status | LA Rams | LAC Chargers | Box score |
| ---: | --- | ---: | ---: | --- |
| 196 | `complete_regulation`, valid | 35 | 30 | `valid_complete`; reconciliation passed |
| 344 | `complete_regulation`, valid | 17 | 23 | `valid_complete`; reconciliation passed |

The two original seed rows remain recorded as `simulation_error` in the immutable original run. Their successful outcomes are in separate, provenance-pinned recovery artifacts; they are not silently substituted into the original batch.

## Six ledger objects reported as missing final status

Each of the six worker seed ledgers begins with one header object. Those six objects contain shard metadata, not game outcomes, so a final game status does not apply. Their audit disposition is `not_a_seed_outcome`. Actual seed rows carry status at `outcome.status`.

No original header or seed row was edited. The earlier tally of 3,527 game rows (3,380 regulation completions, 145 overtime completions, and two simulation errors) was an in-progress snapshot, not a final batch count.

`SUMMARY.json` records recovery outcomes and the header classification. `SHA256SUMS` verifies the copied seed ledgers, box-score sidecars, worker manifests, and logs.
