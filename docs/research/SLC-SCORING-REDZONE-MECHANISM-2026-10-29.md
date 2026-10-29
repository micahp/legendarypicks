# SLC red-zone mechanism, corrected status (2026-10-29)

The earlier exact-yardline comparison is superseded. Its actual-side code counted any play type at or inside the 20 despite the report saying scrimmage play, counted `Opp touchdown` as a touchdown conversion, and compared against simulation seeds that had not all completed. Its trip-rate and conversion comparisons are not calibration evidence.

The corrected 2024 matched-cohort analysis is in [SLC-SCORING-REDZONE-DECOMPOSITION-2024-2026-10-29.md](SLC-SCORING-REDZONE-DECOMPOSITION-2024-2026-10-29.md) and its raw output is [SLC-SCORING-REDZONE-DECOMPOSITION-2024-CORRECTED-2026-10-29.json](SLC-SCORING-REDZONE-DECOMPOSITION-2024-CORRECTED-2026-10-29.json).

On 228 matched games, simulated trips were 3.294 per team-game versus 3.311 actual; the game-clustered interval includes zero. Offensive touchdown conversion was 0.495 per trip versus 0.583 actual, and red-zone plays were 10.350 per team-game versus 9.669 actual. Therefore the evidence points to conversion and extra plays within the red zone, not too few trips.

The older claim that exact-yardline sampling closed about 30% of the trip-conversion gap is withdrawn. Exact-yardline sampling still needs a corrected same-seed, same-cohort comparison before its effect can be judged. The original raw output remains available as historical exploratory data, not as a calibration result.
