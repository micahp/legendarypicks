# Transition-strength offline diagnostic — 2026-11-10

This limited diagnostic compares transition-category probabilities on observed plays. It does not run games or change the simulator. Training uses 2022–2024 for the 2025 evaluation and adds 2025 for 2026. Penalty-tagged plays and plays with unknown penalty status are excluded after sequence classification. Source hashes are recorded in `source-sha256.txt`; `audit.py` is the scorer and `results.json` contains the complete output.

| Held-out season | Scored plays | League log loss | Event-team log loss | Joint-transition log loss |
| --- | ---: | ---: | ---: | ---: |
| 2025 | 32,732 | 1.9920 | 2.0152 | 2.0576 |
| 2026 | 12,478 | 1.9811 | 2.0087 | 2.0450 |

Lower is better. On this diagnostic, the joint candidate does not beat the league baseline. These are transition-category scores, not the event-only scores in the prior audit.

This does not satisfy the full strength-model gates: it omits current-season adaptation, matchup-tier breakdowns and game-clustered uncertainty, and source acquisition timing is unverified. It includes overtime where the E1 pool permits it. The scorer uses the frozen 2026-10-27 local parquet release; the source files themselves are not included. No release decision follows from this diagnostic alone.
