
## Exact-yard-line draw (added 2026-10-29)

Inside the 20, the outcome drawn from rows at the state's exact yard line when there are any (`--exact`, branch
`research/slc-layered-2026-10-29`), same two seeds per game:

| Measure | Default | Exact yard line | Actual 2024 |
|---|---|---|---|
| Touchdown per red-zone trip | 0.485 | 0.527 | 0.623 |
| Touchdown per red-zone run or pass play | 0.201 | 0.189 | 0.196 |
| Red-zone trips per team-game | 3.29 | 3.38 | 3.94 |

The exact draw closes about 30 percent of the trip-level touchdown gap, and it makes the per-play rate fall slightly below actual. So
the geometry mechanism is real but is not the whole gap. Red-zone trips are still short (3.38 against 3.94), which points to the drive
progression outside the red zone. This is a partial result and not a calibrated fix. Output: `SLC-SCORING-REDZONE-EXACT-YARDLINE-2024-2026-10-29.json`.
