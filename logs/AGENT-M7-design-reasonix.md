# AGENT-M7-design-reasonix — M7 EV/CLV/Calibration Design Log

**Agent:** reasonix (deepseek-v4-pro)
**Task:** Design M7 (EV/CLV/calibration compute + endpoints consuming M6 snapshots)
**Output:** `docs/M7-EV-CLV-DESIGN.md` (610 lines, 9 sections)
**Started:** 2026-06-24 07:30 UTC
**Status:** COMPLETE

## Recon steps

1. Read TASK-M7-design-reasonix.md — 6-section deliverable, read-only.
2. Read ODDS-CAPTURE-DESIGN.md (incl. Appendix review) — M6 schema + de_vig_status fix incorporated.
3. Read ANALYTICS-BACKBONE.md — Layer 1b (Kalshi crossover) + Layer 1c (ESPN win-prob).
4. Read /root/prediction-market-trading/espn_resolve.py — confirmed Kalshi ticker→ESPN gid mapping:
   ticker format `KX{NBAGAME|MLBGAME|NHLGAME|NFLGAME}-YYMMMDD{TEAM1}{TEAM2}[-{SIDE}]`
5. Read Kalshi orderflow sample — confirmed fields: best_yes_bid, best_yes_ask, ticker, mid-price computable.
6. Checked ESPN win-probability availability — NOT currently captured; goes in summary endpoint under
   `winprobability[]` during live games. Gap noted in §5.
7. Wrote docs/M7-EV-CLV-DESIGN.md.

## Decisions

- EV uses OPENING snapshot's de-vigged p_fair (not closing) — per review Appendix fix #4.
- de_vig_status from M6 drives the computation path (paired→proportional, single→raw with flag, stale→skip).
- CLV aggregates at market + league level with summary stats (mean, positive-%, n).
- Calibration uses Brier score + decile-bucketed reliability table. Only settled props (hit IS NOT NULL) included.
- Kalshi crossover reads from existing /root/prediction-market-trading/data/orderflow/ JSONL files (same server, no duplication). ESPN win-prob capture is a prerequisite gap.
- Endpoints designed: /api/props/ev, /api/props/clv, /api/calibration, /api/kalshi/ev with full query params + response shapes.

## Open items

1. ESPN win-probability capture not built — needs a live-game poller (similar to M6 --capture cadence). Kalshi crossover blocked until this exists.
2. Kalshi snapshot dedup — 5,781 JSONL files in trading repo; need import logic that reads the latest per-ticker.
3. Brier score reference values — the design includes a qualitative scale but no baseline. First calibration run establishes the baseline.
