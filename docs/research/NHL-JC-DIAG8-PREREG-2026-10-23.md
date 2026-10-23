# NHL JC-DIAG8 preregistration: cross-game identity feasibility

**Source base:** `e67c23f2ab65c4ae58498c58f4e6ef148c2dcef7`

**Step 0 correction commit:** `e9806e61d2e252a4d55eb7da85fe74c7993b4795`

**Branch:** `research/nhl-multi-agent-movement-2026-10-23`
**Status:** commit this protocol before measuring any DIAG8 identity coverage or source counts.

## Purpose and scope

DIAG7's B/C corrections did not apply to any held-out pair because no verified cross-game pair key was available. Their zero differences are support-degenerate, not an estimate of identity value. DIAG8 asks only whether the local frozen/vendored assets contain a documented identity source capable of linking these ten games. It performs a read-only inventory: no model fitting, forecasting, scoring, database access, network requests, provider contact, or production changes.

The new evaluator is necessary because this is a project-specific, file-level identity-coverage question and no existing repo script or report was found by `scripts/prior_art.py "NHL JC-DIAG8 cross-game identity feasibility stable athlete identifiers vendored roster boxscore tracking"`. The source availability and row counts are not published in a local catalog; the evaluator will inventory local files and preserve hashes and count methods so the finding can be falsified.

## DIAG7 correction and fail-closed provenance gate

The isolated Step 0 correction was committed alone as `e9806e61d2e252a4d55eb7da85fe74c7993b4795`. It changes only the DIAG7 report. The report as frozen at source base `e67c23f2`—including the DIAG7-era correction from commit `f7be2a19`—has SHA-256 `f0bad14ac437df5465ab6689d8971eb686f7841da2aee14e6b6bbad290345bd6`. The additive DIAG8 Step 0 report now has SHA-256 `28fa57506071a490f5a92c2426e14e9713aa9c7e95101a3703d989a14ded21b3`.

Before Q1 or Q2, the evaluator must verify all of the following and emit no identity-inventory or coverage values on failure:

| Frozen artifact/value | Required value |
|---|---|
| Source commit | `e67c23f2ab65c4ae58498c58f4e6ef148c2dcef7` is an ancestor |
| Step 0 commit | `e9806e61d2e252a4d55eb7da85fe74c7993b4795` is an ancestor |
| DIAG7 result JSON | `research/nhl-multi-agent-movement-2026-10-23/results/jc-diag7-oos-pair-value-2026-10-23-v1.json`, SHA-256 `fa0d853a39cc33591e1157896572c40a58e374270cf26603cd56850ae6311dce`, 76,326 bytes |
| DIAG7 evaluator | `research/nhl-multi-agent-movement-2026-10-23/diagnose_jc_diag7_oos_pair_value.py`, SHA-256 `199d0f759fbc0642f027f89b6167cb23abe951ce69690c2db15fc7e6b5e85dd2` |
| DIAG7 preregistration | SHA-256 `e5644b1a65098ffa070cf81bbdd8e46978558358ca74696276936124823aab99` |
| DIAG7 report at source base | SHA-256 `f0bad14ac437df5465ab6689d8971eb686f7841da2aee14e6b6bbad290345bd6` when read from the source-base Git object |
| DIAG7 report after Step 0 | SHA-256 `28fa57506071a490f5a92c2426e14e9713aa9c7e95101a3703d989a14ded21b3` |
| DIAG7 inherited source chain | All 17 source paths and SHA-256 values embedded in the pinned DIAG7 result must match local files |
| DIAG7 gate counts | pinned artifacts `22/22`, DIAG6 values `16/16`, inherited source hashes `17/17`, inherited reassertions `41/41` |
| DIAG7 population | 10 games; 200 raw rollout starts; 172 scored starts; 2,164 +45 pairs; 541 pairs in each of four distance bins |
| DIAG7 identity and decision | Q2 verified pair-key count `0`; Q3 reading `pair_identity_line_closes` |
| DIAG7 variance-component range | Across the stored outer folds, `tau²` minimum `2.1137048754904875`, maximum `2.933435460884494` |

Re-read the exact pinned values from the DIAG7 result. A hash, ancestry, population, or value mismatch stops execution before Q1/Q2.

## Q1 — local identity-source inventory

The frozen population is the ten game identifiers and 2,164 +45 within-team pairs in DIAG7. Image Id is ordinal. The current tracking player-object field inventory recorded by DIAG7 is `history`, `id`, `jersey`, `raw_id`, `team`, `x`, and `y`; DIAG8 will inspect all player and event fields in the frozen tracking artifacts, not assume that this list is complete.

Inventory scope is the checked-out repository and already-present research data under `/root/lp-research-data`. No network fetch, external endpoint, or provider contact is allowed. Search versioned and non-ignored local files plus NHL/frozen-game data files in that research-data tree. Exclude Git internals, dependency/build caches, and files proven unrelated to NHL or the ten games; record these exclusions in the result. Do not open the production application database. If another local database is a candidate, inspect it strictly read-only and report its tables/count unit. Follow symlinks only when their resolved targets remain inside the two declared roots.

Enumerate identity-bearing field paths in files containing the frozen games or their tracking/event records. Inspect local manifests, schemas, READMEs, source comments, and provenance documents for field semantics. For every identity-source candidate, record its exact path, SHA-256 of file bytes, row/record count and count unit, game coverage, persistent athlete-ID field, game-ID field, and the local documentation supporting stability. Count tabular data records excluding headers; JSON array/object records by the declared record list; JSONL records by nonblank lines; Parquet rows from metadata; and compressed files from their decompressed record stream. Do not invent a count for a format that cannot be read: fail the candidate inventory with an explicit unsupported-format error.

An eligible cross-game identity source must be an external, local source covering one or more of these ten games, contain a persistent athlete identifier and a game identifier on joinable records, and have local documentation establishing those semantics. It must also provide a direct, documented linkage from each matched tracking identity to that athlete ID and from the frozen game to the source game ID. Similar dates, team labels, names, jersey numbers, and numeric collisions are not a documented linkage. Track `id`/`raw_id`, jersey number, name, team, and numeric collisions are not proof of identity. Do not join on jersey, names, or track-ID collisions.

For the tracking `id` and `raw_id`, report per-game numeric ranges, whether their numeric intervals overlap across games, and exact cross-game value intersections as collision diagnostics only. For `jersey`, report whether values recur across games and state explicitly that recurrence does not establish identity. Inventory every observed player-object field and classify its available evidence; quote a local source definition when one exists or state that none exists. Do not infer missing semantics.

If no candidate satisfies all requirements, report `verified_cross_game_identity_source = none` and list no speculative source paths. For each candidate investigated, report SHA-256, row count, game coverage, documented persistent-ID status, and joinability. The report's first sentence must state the `none` outcome if that is what Q1 finds.

## Q2 — conditional coverage arithmetic

Run only if Q1 identifies at least one qualifying source. For the fixed 2,164 +45 pairs, count unique pair rows, games, and frozen distance bins matched to that source, with percentages against the unchanged DIAG7 denominators. Count pairs that retain at least two training observations under the DIAG7 leave-one-game-out scheme. Do not fit, score, or tune a model.

If Q1 returns `none`, Q2 is `not_applicable`: report 2,164 unmatched pairs (100%), all 10 games unmatched, and all four bins unmatched at their frozen 541-pair denominators. Do not produce partial estimates.

## Registered reading (verbatim)

- `verified_cross_game_identity_source = none` → **the pair-identity question is closed permanently on this source.** No further diagnostics on these ten games; any resumption requires new data acquisition (an identity-bearing roster/boxscore feed or a tracking vendor with persistent athlete IDs), and that acquisition is a data question, not a modelling one.
- Source exists but matches < 60% of +45 pairs → the question stays open only at reduced power; report the exact matched pair count and do not interpret any effect.
- Source exists and matches ≥ 60% → pair identity is testable; the next brief is a re-run of DIAG7 Q1 on the matched subset only, preregistered separately. Do not run it here.

This is a data-availability finding on ten inspected development games, not an independent evaluation. No accuracy, AUC, hit-rate, or profit claims.

## Reproducibility contract

Write the evaluator, JSON, and report only after this preregistration commit. The evaluator will support a gate-only mode that performs no Q1/Q2 inventory counts and a deterministic full run. It will write `research/nhl-multi-agent-movement-2026-10-23/results/jc-diag8-identity-feasibility-2026-10-23-v1.json` and `docs/research/NHL-JC-DIAG8-REPORT-2026-10-23.md`.

Run with `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3`. Run `ast.parse`, `git diff --check`, then a deterministic rerun to a temporary JSON and `cmp` byte-for-byte. Record evaluator/result SHA-256, result byte count, runtime, all candidate file hashes/counts, gate assertions, and reproduction commands. Commit the preregistration separately before the inventory; commit evaluator/result/report together; push the Step 0, preregistration, and result commits to the research branch.
