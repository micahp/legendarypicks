# MIN–DET 10K outcome-ledger audit: live snapshot

**Audit interval:** 2026-10-31 22:34:38–22:34:51 UTC · **Run:** `research-8b7d5a2e-2026-10-31` · **Game:** `2026_08_MIN_DET`
**Result:** No blocked, errored, unsupported-rule, or unfinalized outcomes were found among the ledger rows read in this scan.

This is an interim status audit of an active 10,000-seed run. It is not the final batch report. The six worker ledgers were read sequentially during the stated 13-second interval and could still be appended while scanning.

## Audited outcomes

The scan parsed **7,055 of 10,000 requested seed outcomes (70.55%)** from the six `raw/worker-*.seeds.jsonl` files. Every parsed outcome had a complete status, `complete_game=true`, and `valid_full_game=true`.

| Outcome status | Count |
|---|---:|
| Complete regulation | 6,717 |
| Complete overtime | 338 |
| **Total parsed** | **7,055** |

| Audit condition | Count |
|---|---:|
| Nonempty blocker field | 0 |
| Nonempty simulation or boxscore error field | 0 |
| Nonempty unsupported-rules field | 0 |
| Unfinalized or invalid full-game outcome | 0 |
| Invalid or partial JSON lines | 0 |

The seed IDs in the scanned rows were unique and within the requested range 1–10,000. No duplicate or out-of-range IDs were found. **2,945 assigned seeds were not yet present in the ledgers during the scan.** They are unobserved run work, not failed or missing outcomes.

## Worker progress at scan time

| Worker | Assigned seed range | Parsed | Regulation | Overtime | Not yet present |
|---|---:|---:|---:|---:|---:|
| 01 | 1–1,667 | 1,172 | 1,116 | 56 | 495 |
| 02 | 1,668–3,334 | 1,193 | 1,147 | 46 | 474 |
| 03 | 3,335–5,001 | 1,156 | 1,115 | 41 | 511 |
| 04 | 5,002–6,668 | 1,164 | 1,114 | 50 | 503 |
| 05 | 6,669–8,334 | 1,214 | 1,146 | 68 | 452 |
| 06 | 8,335–10,000 | 1,156 | 1,079 | 77 | 510 |
| **Total** | **1–10,000** | **7,055** | **6,717** | **338** | **2,945** |

Within each worker shard, the observed seed IDs formed a contiguous prefix starting at that shard's assigned seed. The remaining IDs were beyond that prefix at scan time.

## Audit method and scope

The scan read every JSONL row after each file's header. It counted outcomes by `outcome.status` and inspected `blocker`, `error`, `boxscore_error`, `unsupported_rules`, `complete_game`, and `valid_full_game`. Seed uniqueness and range were checked using the top-level ledger seed IDs.

This pass checks ledger status and seed coverage. It does **not** reconcile player/team box scores, quarter scoring, drive summaries, or workload distributions. Those checks belong in the completed-batch report after all 10,000 seeds are accounted for.

## Run provenance

- Fast-host artifact root: `/root/slc-week8-player-workload-10k-2026-10-30/artifacts/MIN_DET/research-8b7d5a2e-2026-10-31/`
- Run started: `2026-10-31T20:42:48.060596+00:00`
- Source commit: `8b7d5a2ec818d4e53751f5c4baf5a2956b317a7f`
- Pregame cutoff: `2026-10-29T00:02:21Z`
- Profile: `v1_full_stack`; boxscore export enabled; ordinary field-goal cutoff 60 yards.
- Enabled blocker fixes: `run_scramble_backoff`, `long_field_goal_feasibility`, `blocked_kick_source_audit`, `blocked_kick_geometry`, `safety_free_kick_boundaries`.
- Run header SHA-256: `4da63b1404efc28ec257f0811a8b81587088fe39218e90d4726af3823f4d9299`
- Frozen snapshot SHA-256: `476715b5a0f94cac919638b9666b571945cb847b3a6f4e6977b79ae0a36531b1`
- Simulation database SHA-256: `feb5179f1c6c2f8cd2265a25ff68f3552d6e68bbba00354e0688f22505aa028f`
- Play-call artifact SHA-256: `c8f16540931f6fddc61b6e62797ecd71dfff11897c393c531033eef623328ce5`
- Streak input SHA-256: `4d3e0d712134396ea91d1d9d8bca11ce9d6089679d6e2360696f44e311af5c`

The worker ledgers were actively changing during this audit, so this snapshot does not assign them final content hashes. Re-run the audit and produce the final report once all worker partitions finish.
