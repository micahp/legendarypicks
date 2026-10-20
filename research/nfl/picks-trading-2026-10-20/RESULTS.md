# RESULTS — NFL model picks: predictions vs qualifying wagers (2026-10-20)

Branch `research/nfl-picks-trading-2026-10-20`, forked from `origin/dev` at `9ebd6423`
(origin/dev has since moved to `67e7e5e9`; this branch was not rebased).
Research only: no production code, no Model-page change, no deploy.
Read-only on the dev database. Every number below is reproduced by
`python3 research/nfl/picks-trading-2026-10-20/run_audit.py --db <dev db>`.

## 1. Audit — what each surface actually claims

| Surface | File | What it derives | What it does **not** establish |
|---|---|---|---|
| Straight-up pick | `backend/routers/nfl_model.py` (`su_result`) | pick = side with `p_home_win > 0.5`; win/loss/tie/no_pick from the final | no price, no stake, no return |
| ATS record | `backend/grade_nfl_locks.py` (`ats`) | model takes home when `proj_margin > spread`, away when below; grades against the locked spread | no price; a 6–4 ATS record says nothing about units |
| Total | `backend/grade_nfl_locks.py` | `total_err = actual total − projected total` | no over/under pick and no price at all |
| Lock | `backend/nfl_lock.py` | one row per (game, model_version), first projection wins; line copied from nflverse schedule at lock time | — |
| Capture | `backend/capture_nfl_game_lines.py` | Bovada pregame spread/total/ML, dry-run by default | only run when invoked; nothing scheduled |

The page reports a straight-up **record** and an ATS **record**. Neither is a wager. The brief's
lesson (NHL: winning predictions and profitable wagers are different claims) applies directly.

## 2. Price coverage — 2026 REG weeks 5–7

| Metric | Count |
|---|---|
| REG games in weeks 5–7 | 43 |
| Games with any captured snapshot | 33 |
| Games with a **pregame** snapshot | 30 |
| Games with a pregame snapshot **and** a final result | **16** |
| Games final in the window | 29 |
| Snapshots total | 78 (75 pregame, 3 post-kickoff) |
| Sources | nflverse 45, theoddsapi:draftkings 20, bovada 13 |

- **Captured pregame prices exist for 16 gradeable games only.** These are the only games in
  the window where a return can be computed from a real offered price. Everything else is a
  disclosed gap, not a result.
- The three post-kickoff snapshots (`2026_05_DEN_LAC`, `2026_05_DET_ARI`, `2026_05_SF_SEA`,
  all `theoddsapi:draftkings` at 2026-10-11T22:01Z) cannot price a wager and are excluded.
- No 2010–2025 captured prices exist. Historical lines are nflverse closing lines with no
  timestamp; they are sensitivity only and cannot establish executable returns (§4).
- The week-5 genuine captures (bovada 2026-10-11T21:46Z) were **after** kickoff for the 13:00 ET
  games, so week 5 contributes 2 gradeable games; weeks 6–7 contribute 14.

## 3. Six baselines on the 16 gradeable games

Flat 1 unit per game; spread/total at −110; ML at the offered price for the picked side.
Only games with a captured **pregame** price and a final result. `run_audit.py` output:

| # | Baseline | Wins | Pushes | Units | ROI |
|---|---|---|---|---|---|
| 1 | model straight-up winner ML | 9/16 | 0 | −1.39 | −8.7% |
| 2 | sportsbook favourite ML | 8/16 | 0 | −3.84 | −24.0% |
| 3 | model ATS side | 8/16 | 0 | −0.73 | −4.5% |
| 4 | model total side | 6/16 | 0 | −4.55 | −28.4% |
| 5 | both ML sides | — | — | +3.93 | +24.6% |
| 5 | both spread / total sides | — | — | −1.45 each | −9.1% each |
| 6 | no trade | — | — | 0.00 | 0.0% |

**What this says.** The model's straight-up ML and ATS selections lost money at the captured
prices; the total selection lost the most. The favourite ML lost most of all. `both_sides_ml`
being positive is a realized-outcome artifact of underdogs winning at plus odds in this 16-game
sample — it is not a strategy and not a basis for adoption. The spread/total both-sides rows sit
exactly at the −9.09% two-way hold, as they must.

**What this does not say.** n = 16 is far too small for significance; the interval on any ROI here
spans a wide range. The ATS and total baselines use −110 as the offered price; actual captured
prices for those markets were not recorded (only the line, not the juice). No game without a
captured pregame price is assigned a return.

## 4. Sensitivity — frozen v1 vs closing lines 2010–2025

Retrospective only. nflverse closing lines carry no timestamp, so these are **not** executable
returns; they can only show whether the model's sides beat the closing number in aggregate.

| Window | ATS W–L–P | Total W–L–P | Brier model | Brier market |
|---|---|---|---|---|
| 2011–2023 | 1488–1588–92 | 1512–1624–32 | 0.2231 | 0.2104 |
| 2024–2025 | 249–258–5 | 265–244–3 | 0.2249 | 0.2069 |

The model is on the wrong side of the closing spread in 2011–2023 (48.4% cover) and essentially
even in 2024–2025. Its total side is near 50/50. Brier is worse than the de-vigged market in both
windows, consistent with `docs/RESULTS-market-baseline-2010-2025-2026-10-11.md`.

## 5. Selectivity

Not tested. The 16 gradeable pregame games cannot support a chronological fit/evaluate split; any
selector fitted here would be fit on the same games it is scored on. Verdict: **INCONCLUSIVE —
insufficient captured pregame prices.** This is a data limitation, not a model finding. A larger
pregame capture archive is the prerequisite for §4 of the brief.

## 6. Verdicts

| Policy | Verdict | Basis |
|---|---|---|
| Straight-up pick as a wager | **NOT_ADOPTED** | −8.7% on 16; no edge vs price |
| Favourite ML | **NOT_ADOPTED** | −24.0% on 16 |
| ATS side as a wager | **NOT_ADOPTED** | −4.5% on 16; 48% cover 2011–2025 |
| Total side as a wager | **NOT_ADOPTED** | −28.4% on 16 |
| Both ML sides | **NOT_ADOPTED** | positive is sample artifact; structurally loses the hold |
| Selectivity policy | **INCONCLUSIVE** | 16 games cannot be split |
| Prediction accuracy vs trading | **separate surfaces** | §6 proposed rule below |

## 7. Proposed Model-page rule

Prediction accuracy and trading results are displayed separately. A 9–7 straight-up record says
9–7 straight up and never implies units. Any units figure appears only beside captured pregame
prices and correct settlement, with the game count and the excluded games stated. Show three
distinct labels: **Prediction** (projected scores, margin, total, win/cover/total probabilities),
**Lean** (model side vs the posted line — not a bet), and **Qualifying wager** (a named side/price
or "no qualifying wager"). Do not print "record" without "straight up".

## 8. What could not be measured

- No captured pregame prices before 2026 week 5; 2010–2025 stays sensitivity-only.
- Spread/total juice not stored; ATS/total ROI uses −110 as an assumption.
- No pre-kickoff prospective capture; the 3 week-5 snapshots were post-kickoff.
- 16 gradeable games — every ROI here is directional, not established.

## Reproduction

```
cd /root/lp-nfl-picks-trading
python3 research/nfl/picks-trading-2026-10-20/run_audit.py \
  --db /root/legendarypicks/backend/data/picks.dev.db
```

Writes `coverage_2026.csv` and `audit.json` in this directory. Interpreter needs `numpy`,
`scipy`, `pytz` (this run used `/root/meeseek/.venv/bin/python`).
