# E2 successor evidence package (2026-10-24)

Branch `feat/nfl-sequence-e2-successor-2026-10-24`. Producer commit `c131fda249dcf9af642dd6ba267905e88803a74a`. Frozen `a442dcd7` is untouched.
`valid_full_game` is false. Every file below is in this folder.

| part | file | what it shows |
|---|---|---|
| 1. provenance | `PROVENANCE-2026-10-24.json` | producer and parent SHAs, Gridiron heads, contract hash `ae7b8a30…` (matches in LP and both Gridiron heads), engine and evidence file hashes, frozen fixture hashes, output hashes |
| 2. immutable seed-1 game | `seed1-game-successor.json` | the successor record for seed 1, regenerated from the committed engine and byte-matched |
| 2b. recomputed statistics | `seed1-stats-recomputed-successor.json` | team and player statistics recomputed from the plays: all match stored, 121 players |
| 3. per-seed survey | `SURVEY-300-SUCCESSOR-2026-10-24.md`, `legality-survey-300.csv`, `legality-survey-300-summary.json` | 288 complete, 12 blocked, 300 legal under the modelled rules, 0 legal complete games |
| 4. independent legality | `test_legality.py` (run output in the report) | 21 tests: 2 positive, 18 negative, 1 pin; the checker imports nothing from the engine |
| 5. source semantics | `SOURCE-SEMANTICS-AUDIT-2026-10-24.md` | publisher fields for tries, penalty and two-minute scope, overtime pool, toss, kick table, timeouts |
| 6. Gridiron integration | `e2-game-envelope-seed1-successor.json`, `e2-game-seed1-successor.v1.json`, `gridiron-adapter-proof-de64ae12.json`, `gridiron-adapter-proof-13b18faa.json` | both heads accept the envelope: 141 plays, 18 drives, A 24, B 27, 0 findings |
| toss (blocker 4) | `toss-sampling-300.json` | winner A 153 / B 147, choice receive 155 / defer 145; both sides sampled |

Known limits, stated in the audit: two-minute warning and penalties are not modelled; overtime is excluded from the pool and a
tied game blocks; `duration_seconds` is null for all 141 plays; the published kick table includes overtime kicks.
