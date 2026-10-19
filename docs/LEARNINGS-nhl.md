# NHL model learnings

The single record of gate testing, experiment results and go/no-go calls for the NHL track.
Append-only. A null result is an entry; so is a bug that produced confident nonsense.

**Settlement basis:** official final score, shootouts decided separately. Statistical and
official goals are tracked independently.

## Decision register

| Item | Result | Verdict |
| --- | --- | --- |
| Goaltender adjustment on xG | G1 0.26657/0.72935 vs G2 0.26673/0.72961, intervals contain zero | **NO-GO** — no measurable gain |
| Starting-goalie feed | 49.7% heuristic; future payload has no probable/starter fields | **DROP** |
| Special teams xG over 5v5-only | Brier 0.243912 → 0.243299, log loss 0.680833 → 0.679578, CRPS 0.960078 → 0.958671 | **PASS, pending reproducible artifact** |
| Tiered leeway cascade vs always-away +1.5 | cover tier 72.5% of games, 69.3% hit, Brier 0.2114 vs 0.2099 | **NO-GO** |
| Leeway pick hierarchy (`leeway-2`) | implemented and unit-tested; not yet observed on a real slate | live, unproven |

## Entries

### 2026-10-17 — Market settlement and the lock must agree, or the record lies
**Learned:** pricing settlement disagreed with the recorded grade, so the same game could be
banked as a win and a loss depending on which table was read.
**Evidence:** market-pricing fix `d48350a2`, integration `e34e55bf`; recorded in
`docs/AUDIT-nhl-settlement-fixes-and-model-brief-gaps-2026-10-17.md`.
**Consequence:** a pick is graded once, from the immutable locked quote, using the official
final score. Diagnostics may use statistical goals; settlement may not.

### 2026-10-18 — A missing intercept is a silent, total model break
**Learned:** the research prototype saved `coef_` without `intercept_` and predicted
`exp(X @ beta)`, while the production runner used `exp(intercept + X @ coef)`. Every research
number produced from that cache was computed on a different model than the one that ships.
**Evidence:** fix `7dd1b62b`; 16 seasons refit; `test_regressions.py` 16/16 including exact
`.predict(X)` reproduction under scikit-learn 1.9.0.
**Consequence:** a prototype must reproduce the production estimator's `.predict` on the same
rows before any of its scores are quoted. Invalidating `fit_cache.json` is mandatory, not
optional.

### 2026-10-18 — Shot difficulty is testable; the missing signal is the starting goalie
**Learned:** 2,079,359 located shots exist across 2007–2025, so shot-quality modelling is not
blocked. What is genuinely missing is a reliable pre-puck-drop starting-goalie declaration, and
null `homeTeamScore` / `roadTeamScore` at lock time.
**Evidence:** `research/nhl-goalie-adjustment-2026-10-18` `ecf95a63`.
**Consequence:** do not describe shot difficulty as untestable. State the missing field precisely.

### 2026-10-18 — A goaltender adjustment is not worth shipping
**Learned:** G1 scored 0.26657 Brier / 0.72935 log loss against G2's 0.26673 / 0.72961. Both
intervals contain zero. The starter heuristic that would drive the adjustment hits only 49.7%.
**Evidence:** goaltender research, seasons through 2025.
**Consequence:** no goaltender feature ships on this evidence. Coins are not a signal.

### 2026-10-19 — The starting-goalie feed does not exist in the payload
**Learned:** the gamecenter payload for a future game returns 200 with `gameState: FUT` and
contains **zero** occurrences of "probable", "starter" or "projected". `goalieComparison` is team
totals plus goalie leaders — not a starter declaration.
**Evidence:** `research/nhl-starter-feed-2026-10-19` `ce89b619`, corrected `84985d14`.
**Consequence:** the feed is DROP. Do not re-open it as a data-integration task. The correct
statement is that the perfect-feed ceiling is the observed-starter recomputation, which already
failed the outcome gates.

### 2026-10-19 — Special teams xG is the first thing that has passed
**Learned:** adding power-play and penalty-kill xG to the 5v5-only input improves Brier
0.243912 → 0.243299, log loss 0.680833 → 0.679578 and CRPS 0.960078 → 0.958671, with
game-clustered intervals excluding zero, over 9,147 graded games (2019–2025). Per-season counts
weighted by n reproduce every pooled value exactly.
**Evidence:** `research/nhl-special-teams-2026-10-19` `627e0d6e`, prereg `854ad6f2`.
**Consequence:** promising, but **not adoptable yet**: no per-game predictions were saved, so the
scores are not recomputable without refitting, and the 92,008-value leakage audit has not been
run here. Publish the forecasts and the verifier output before this is treated as evidence.
Known caveat: 2025 is negative and 2024 is CRPS-negative.

### 2026-10-19 — The leeway cascade loses to the dumbest possible rule
**Learned:** on 2025 `b7_elo_xg`, the corrected cascade selects a cover on 72.5% of games at a
69.3% hit rate with Brier 0.2114. Taking away +1.5 every single game scores 0.2099.
**Evidence:** `research/nhl/model-call-research-2026/run_policy_comparison.py`, artifact
regenerated 2026-10-19 13:07; baseline identical under both prior-season constructions.
**Consequence:** the tiered selector is not promotable. A selection rule must beat the constant
baseline on proper score, not on hit rate.

### 2026-10-19 — The printed edge is points, not probability
**Learned:** the card's "Edge 1.3 pts (ANA)" is `|locked puck line| − favourite margin`, the gap
between the Vegas line and the model line. The first implementation compared a probability
difference (7.8 percentage points) against the 1.0 threshold, which every game cleared, so rule 1
fired on all of them and every pick came out as the underdog +1.5.
**Evidence:** `d007e540`; four card games now resolve to ANA +1.5 (S 1.3), COL ML (S 0.4),
SJS +1.5 (S 1.2), UTA ML (S 0.9).
**Consequence:** when a rule is copy of a printed quantity, test it against the printed number on
real cards before shipping. A threshold that never fails is a broken threshold.
