# TASK — M7 DESIGN: EV / CLV / calibration compute + endpoints

**For:** reasonix. READ-ONLY design doc — M7 consumes M6's odds snapshots. Design it
against the now-final+reviewed M6 schema (`docs/ODDS-CAPTURE-DESIGN.md` incl. the
Appendix review, especially the `de_vig_status` column + de-vig math §7).
**Output:** `docs/M7-EV-CLV-DESIGN.md`. No code/DB writes.

## Scope — design doc covering:
1. **EV compute** — from a settled prop's bet-time odds + result:
   - american→decimal, implied prob, de-vig (use `de_vig_status`: paired →
     proportional de-vig; single → raw implied, flagged lower-confidence; stale →
     skip). EV = p_fair×(d−1) − (1−p_fair).
   - How to pick the "bet-time" snapshot (opening vs last-before-close) and the
     "close" snapshot (`is_close=1`).
2. **CLV compute** — p_close_implied − p_open_implied for the bet side; aggregate
   CLV per market / per league. Tie to [[project_prediction_market_trading]] v3
   reckoning (edge is selection not timing) — how CLV validates selection quality.
3. **Calibration** — bucket settled props by EV decile / by p_fair decile; predicted
   vs realized hit-rate; reliability + Brier score. Define the query shape + the
   `/api/.../calibration` endpoint.
4. **Endpoints** — `/api/props/ev`, `/api/props/clv`, `/api/.../calibration` (shapes,
   filters by league/market/date-range).
5. **Kalshi crossover (event-level)** — how an ESPN win-prob (from the ESPN
   `/summary` winprobability feed) compares to a Kalshi market price for the same
   event, to find +EV event bets. (Micah = `geoppls` on Kalshi.) Identify the join
   key (ESPN event ↔ Kalshi market) and the data we'd need to capture.
6. **What M6 must expose** — confirm the snapshot schema is sufficient; flag gaps
   for M6-impl (coordinate via the orchestrator, don't edit M6-impl's files).

## GUARDRAILS
- READ-ONLY. Doc only. No code/DB writes, no live Kalshi/API calls (design against
  documented endpoint shapes; curl ONE payload to verify if needed, bounded).
- Bounded; no machine-wide greps/strings-on-DB/unbounded loops.
- Write `logs/AGENT-M7-design-reasonix.md`. Do NOT commit/push/deploy.

## Done criteria
- `docs/M7-EV-CLV-DESIGN.md` with the 6 sections; math formulas explicit; the
  Kalshi-ESPN join key concretely identified (or the gap to resolve it).
