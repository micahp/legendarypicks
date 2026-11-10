# SLC-v2 profile integration check

Date: 2026-11-10  
Branch: `slc-v2`  
Research integration: `f288679f`
Week 9 kicker default fix: `a755592c`

## Paired SLC-v2 smoke run

The actual `--slc-v2` profile completed 10 control games (C) and 10 D1 games for `2026_09_BUF_MIN`, seeds 100001–100010. Both arms used the same pre-final-roster snapshot, Week 1–8 snap counts, participation field, Week 9 kicker table, play-call artifact, blocker fixes, and RNG-v2 root.

| Arm | Valid games | Box-score reconciliation |
| --- | ---: | --- |
| C | 10/10 | 10/10 passed |
| D1 | 10/10 | 10/10 passed |

Both arms used stream root `19390d88410a2f010930d51c2720f225635b128c2ce28e05d84fc963e9e7332d`. Per-seed paired stream evidence matched for all 10 seeds. The D1 adapter changed only the workload layer, as checked by the pairing code.

This verifies that C and D1 run through the actual SLC-v2 command path. Ten seeds are an integration smoke sample, not evidence to select a production default. D1 remains behind `--experimental-workload-estimator D1`.

## Separate 10,000-seed run

The earlier 10,000-seed run used `v1_full_stack`, not `--slc-v2`. All 10,000 seeds used the same snapshot, taken at `2026-11-09T20:28:32Z`, before the 90-minute roster-finalization point. Roster timing did not determine game validity.

The final set has 9,990 valid complete games and 10 game-validation errors. It has no missing or duplicate seed IDs. The first 1,000 games were not rerun. Their saved full records passed the current game validator and their saved box scores passed reconciliation, so the derived report counts all 1,000 as valid. The original files remain unchanged.

The 10 failed seeds are:

- Blocked-kick state errors: 2547, 3242, 4659, 5859, 7110, 8512.
- Duplicate kickoff sequence: 4317, 6751.
- A Q4 safety did not end the game: 5321, 8562.

All 10 failed seeds have preserved error records. Their box-score reconciliation passed, but the game validator failed, so they remain invalid.

## Input and evidence limits

The Week 1–8 snap-count file has SHA-256 `36f28e18af3080df9f160d42dd5e3e59c37cfacf0dd24772ea51cfd41cadcfca`. Its source files were downloaded at `2026-11-10T00:13:56Z`, after the forecast snapshot and roster-finalization point. The source publication time is unknown. Game-day player eligibility also remains unknown. Treat the paired smoke run as exploratory.

The Week 9 kicker table is pinned at SHA-256 `4d21b4de6e0ccbced271cd2cd81ded42528a6ad928319fa6e2157f47bacd9caf`. The SLC-v2 default now uses this table, which includes the BUF and MIN Week 9 kicker assignments. The previous default lacked Week 9 assignments and stopped before simulation.

After the default changed, a fresh `--slc-v2` run with no kicker-table override completed seed 100011: 1/1 valid game. This verifies that the default profile loads the Week 9 table.

## Fast-host artifacts

The raw simulation artifacts remain on the fast host under `/root/ot-sim-out/`.

- 10,000-seed validity report SHA-256: `a9495641551c271fa240d4b4d775ed52b80822f839b23db84ce5652aa39bddc6`.
- Combined aggregate SHA-256: `7ba897aec6c16bcda07a2a76d9dcd20f2e646fee0494d1f63acf3c4d59b23c8e`.
- Derived original 1,000 box scores SHA-256: `1a0b56bf870bb1222e8975af818971ece6a9f9039dcc126bacd9b031afaa4c54`.
- C run summary SHA-256: `d067e20a13a874894eb7abb7d128ae2e3fca3a6259ebfc14a19f920b0320fcde`.
- D1 run summary SHA-256: `8fac7b1aa4f316d2a553b92ac9891324c1ffb3e8ff36009974a453f50c736bc1`.
