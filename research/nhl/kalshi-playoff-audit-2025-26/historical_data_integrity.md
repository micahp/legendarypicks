# NHL historical data integrity status

The standalone NHL modeling DuckDB was opened read-only. Historical game canonicalization and pregame rolling-feature readiness are documented in the [canonicalization discrepancy report](canonicalization_discrepancy_report.md). The content-addressed canonical table, corrections list, full tied-game classifications, and rolling-feature table are linked there with SHA-256 hashes.

## Resolved in the current audit

- All **23,222** team-log games across seasons 2008–2025 were matched to the official NHL schedule.
- **115** Phoenix/Arizona venue labels were corrected from official home/away schedule records.
- **2** contradictory `shots.homeTeamWon` labels were corrected to NHL winners.
- **8** team-log score records differed from NHL regulation/overtime goal targets; all are listed with official evidence. Shootout final scores are kept separately, and the awarded shootout goal is removed from the model-goal target.
- All **2,140** tied team-log records were classified against NHL results: 2,139 are shootouts matching the tied team-log goals; one is an anomalous regulation game, Anaheim–St. Louis on 2020-03-11, whose logs say 1–1 while the NHL record is 2–4.
- The missing shot-table game `2021021028` was reconciled to Buffalo 3–3 Washington in regulation/OT goals and Washington's official shootout win (official final 3–4).
- Pregame rolling features were generated with same-date and current-game information excluded. Temporal provenance and perturbation checks passed.

This is feature readiness only. No model was trained and no official backtest was started.
