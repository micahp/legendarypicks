# NFL model learnings

The single record of gate testing, experiment results and go/no-go calls for the NFL track.
Append-only. Failed arms stay in the record so they are never re-run as if untested.

**Benchmark discipline:** every arm is scored against the de-vigged market on the identical
game set, with a paired block bootstrap. Beating a previous arm is not a result.

## Decision register

| Item | Result | Verdict |
| --- | --- | --- |
| History window W=2/3/all vs W=1 | pooled −0.000095 / −0.000079 / −0.000080, all CIs span zero | **NO-GO** — the prior window is not a lever |
| PROE (`proe_net`) | pooled −0.000045; 2025 +0.002423 significantly worse | **NO-GO** |
| Elo + PROE | pooled +0.000244; 2025 +0.001229 worse | **NO-GO** |
| Turnover luck (`tl`) | pooled −0.000186 [−0.000703, +0.000329] | **NO-GO** |
| Elo + turnover | pooled +0.000048 [−0.000300, +0.000400] | **NO-GO** |
| v2-platt as the prop model | 0.24916 vs market 0.24681, CI [−0.00066, +0.00527] | indistinguishable from market — not skill |
| Marcel-lite vs v2 on identical rows | marcel 0.26989, v2 raw 0.26881, platt 0.24916, market 0.24681 | **v2-platt replaces Marcel-lite** — 0.0207 better, no edge on the market |
| Closing the platt→market gap | per-market Platt 0.25333, isotonic 0.24946, PMF mean shift 0.26961 | **NO-GO** — calibration is exhausted; the gap is passing-yards modelling |
| Pre-kickoff line capture | 18 games / 49 rows, 19.4% coverage, 3 in-play prices written | plumbing fixed; scale still missing |

## Entries

### 2026-10-18 — A point projection is not a probability
**Learned:** Marcel-lite produced Brier 0.3082 against the market's 0.2463. Turning a rough
point estimate straight into an over/under probability is far worse than not modelling at all.
**Evidence:** NFL Marcel-lite backtest, 2026-10-18.
**Consequence:** never publish P(over) from a mean alone. Every prop probability must come from
a calibrated distribution, and calibration is graded before accuracy is discussed.

### 2026-10-19 — The served NFL model is outside the evaluation contract
**Learned:** the live prop API is the old unversioned history route, self-labelled Marcel-lite,
reading `player_game_logs`. The v2-platt route exists but the production image predates it.
Served props scored 0.2486 against the market's 0.2463, paired +0.00227 [+0.00005, +0.00449].
Spread 0.2646 vs 0.2498 and total 0.2634 vs 0.2499 are worse than a constant.
**Evidence:** `research/nfl/SERVED-MODEL-RECONCILIATION-2026-10-19.md`, commit `dec84c6d`;
prod image `sha256:b63c0c5e…` created 2026-10-17T10:37Z, v2-platt merged `c71529cf` 2026-10-18.
**Consequence:** do not quote served NFL numbers as model performance. Spread and total outputs
must never be presented as forecasts. Shipping v2-platt is a deploy decision, not a modelling one.

### 2026-10-19 — The prior's history window is not a lever
**Learned:** the incumbent prior uses exactly one prior season. Widening to 2, 3 or all available
moves pooled Brier from 0.2222262 by −0.000095, −0.000079 and −0.000080 respectively; every
interval spans zero and both holdouts are unresolved or slightly worse. Benchmarks on the same
1,914-game overlap: Elo 0.218971, market 0.210637 against our 0.2222.
**Evidence:** `research/nfl/history-window-2026-10-19`, prereg `a91d136f`, result `8a591e72`;
1,915 games / 128 blocks, 6 ties excluded and counted.
**Consequence:** stop looking for the ladder gap in the prior window. The gap to market is the
features and the model, not how much history the prior averages.

### 2026-10-19 — PROE adds nothing on top of the existing stack
**Learned:** `proe_net` scored pooled −0.000045 [−0.001034, +0.000901] against stack B, and in
2025 it was significantly *worse* at +0.002423 [+0.000340, +0.004566]. Elo+PROE behaved the same
way (pooled +0.000244, 2025 +0.001229 worse). The feature was already registered and backfilled
in `nfl_proe_feature.py` and had simply never been run.
**Evidence:** `research/nfl-proe-2026-10-19`, commit `8a7e908f`; 3,158 graded games 2011–2023,
10 ties and 1 no-moneyline counted.
**Consequence:** do not re-propose PROE. A registered-but-unrun feature is still a test, and
this one is now spent.

### 2026-10-19 — Turnover luck does not predict, and it hurts in recent seasons
**Learned:** `turnover_luck` scored −0.000186 [−0.000703, +0.000329] pooled, with 2024 +0.000518
and 2025 +0.000753 — worse when it matters most. Elo+turnover was +0.000048
[−0.000300, +0.000400]. Neither passed the unchanged keep rule.
**Evidence:** `research/nfl-turnover-luck-2026-10-19`, prereg `b6b24a98`, result `84315ed3`;
registered group 2011–2023 n=3,158, B 0.222892, tl 0.222706, market 0.210415.
**Consequence:** regression-to-the-mean features are not automatically predictive. Margin MAE
improved 10.511 → 10.500, which is not the registered verdict and must not be sold as one.

### 2026-10-19 — Marcel-lite is reproducible, and v2 beats it on the same rows
**Learned:** `eng.marcel()` in `nfl_player_projection_v2.py` is the live Marcel-lite route, so it
can be regenerated. Scored on the identical 25,566 graded line-items (2026 weeks 3–5):
Marcel-lite **0.26989**, v2 raw **0.26881**, v2-platt **0.24916**, market **0.24681**. Point
accuracy agrees: MAE 30.93 vs 29.38, bias −1.30 vs −7.72.
**Caveat that must travel with the number:** Marcel-lite only produces a mean. It has no
probability of its own; the score above gives it v2's dispersion so the comparison is possible.
**Evidence:** head-to-head on `nfl-2026-w03-w05.jsonl.gz` with `nfl_player_projection_v2.marcel`.
**Consequence:** replacing Marcel-lite with v2-platt is a real improvement, not a lateral move —
and still not an edge over the books. Also settled: the served probability field is **raw v2**, not
Marcel-lite — it matches raw on 26,638 of 26,638 rows and platt on 4.

### 2026-10-19 — The remaining gap to market is passing yards, and calibration cannot close it
**Learned:** platt sits 0.0024 behind market overall, but the gap is one market: passing_yards
+0.0087 (week 4) and +0.0060 (week 5), consistent. Every other market changes sign between weeks.
Three calibration levers were tested on weeks 3–4 and scored on week 5: per-market Platt
**0.25333** (worse — overfits), isotonic **0.24946** (no gain vs 0.24749), and a passing-yards PMF
mean shift, which moves 0.27128 → 0.26961 and stays far behind platt at 0.25147.
**Evidence:** `nfl-2026-w03-w05` rows, per-market and per-week decomposition.
**Consequence:** stop tuning the probability map. Passing yards needs a better model — opponent
pass defense, game script, or its dispersion — and that is a new pre-registered experiment, not a
knob. Everything else is at market parity or better.

### 2026-10-19 — The line capture was recording in-play prices
**Learned:** only 18 games / 49 rows exist in `nfl_line_snapshots`, weeks 5–6, 19.4% coverage.
Worse, both capture scripts filtered on `home_score IS NULL` and never checked kickoff, so three
rows were in-play prices at −116.5, −96.5 and −96.5 minutes. `nfl_schedule.line` is a post-game
refresh and differs from the lock line on 18 of 18 games.
**Evidence:** `research/nfl-line-capture-audit-2026-10-19`, audit `9f84b271`, guard `3e2a19dc`.
**Consequence:** any pre-kickoff grading set built before this guard is poisoned. A missing
kickoff check is a silent contamination bug, not a data gap.

### 2026-10-19 — The prop capture harness works but grades nothing prospectively
**Learned:** the backfill produced 26,638 side rows, all correctly labelled `backfill` and
`cp4_evidence_eligible=false`. Graded: platt Brier 0.24916, raw 0.26881, market 0.24681; the
platt difference [−0.00066, +0.00527] spans zero. The stored integer PMF also puts P(over)
above the served continuous value by +0.00386 on average.
**Evidence:** `research/nfl-prop-capture-2026-10-19` `4a37cd90`, grade `5202d247`; 12,783
gradeable items over 359 player-games.
**Consequence:** CP4 must reference the explicit probability field, never the `v2-platt` row
label, which matches raw on 26,638 of 26,638 rows. Backfill is not prospective evidence.

### 2026-10-19 — A third-party prediction feed cannot be graded retrospectively
**Learned:** swcrockett's published predictions cover exactly six files, 2026 weeks 1–6, with
zero prior seasons. Of 14 games, 13 are post-kickoff and 0 are graded.
**Evidence:** `research/swcrockett-weekly-import-2026-10-19` `1d2a0358`, memo `5c8a0f91`.
**Consequence:** their published 0.2213–0.2244 is not a target and not a comparison. Only
forward capture, from week 7 onward, can produce a defensible number.
