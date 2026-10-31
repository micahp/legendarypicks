# LABÈ›y¯ßy”LA source-yardage recovery

Two seed failures from the live research-8b7d5a2e-2026-10-31 batch were replayed with the committed source-row filter at f1c82e553698830590b75d9402d57eeb21bb306d.

The cause was one historical completed-pass source row whose passing and receiving yards disagree: 2022_16_LAC_IND, play 3371 (13 passing yards, 12 receiving yards). The patched source pool excludes this inconsistent row. Each recovery used the original frozen LAKßuÁ‚ùÁSLA snapshot, cutoff, database, playcall artifact, streak input, and seed-specific settings; boxscore export was enabled.

| Seed | Recovery status | Score (LKßuÁ‚ùÁSLAC) | Boxscore |
| ---: | --- | ---: | --- |
| 196 | complete_regulation, valid | 36È›y¯ßy”30 | valid_complete; reconciliation passed |
| 344 | complete_regulation, valid | 1;ßuÁ‚ùÁS23 | valid_complete; reconciliation passed |

The original run ledgers and their two simulation_error records remain unchanged. These are separate, provenance-pinned recovery artifacts; they are not silently substituted into the original batch.

## Six entries reported as missing a final status

The six entries were the one header object at the start of each of the six worker seed ledgers. Headers describe shard metadata and do not have game outcomes. Game rows store their final status at outcome.status. No header was edited, and no seed row was added or rewritten. A prior point-in-time tally of 3,527 game rows had 3,380 complete_regulation, 145 complete_overtime, and the two errors above; that was an in-progress tally, not a final batch count.

SUMMARY.json records the replay provenance and outcomes. SHA256SUMS covers the copied seed, boxscore, worker-manifest, and log artifacts.
