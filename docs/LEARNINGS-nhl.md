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
| Special teams xG over 5v5-only | Brier 0.243912 → 0.243299, log loss 0.680833 → 0.679578, CRPS 0.960078 → 0.958671 | **PASS on the keep rule, not adopted** — CRPS interval spans zero |
| Historical market benchmark | SBR archive via Wayback, 5,131 complete games 2018-19 → 2022-23 | **AVAILABLE** — no-vig close Brier 0.23554 |
| Tiered leeway cascade vs always-away +1.5 | cover tier 72.5% of games, 69.3% hit, Brier 0.2114 vs 0.2099 | **NO-GO** |
| Leeway pick hierarchy (`leeway-2`) | implemented and unit-tested; not yet observed on a real slate | live, unproven |
| Standalone moneyline selectivity | 886 bets, −3.11% ROI; −1.072 pp/game vs no-vig market | **NOT_ADOPTED** |
| `leeway-2` historical replay | 5,126 picks, −2.6% ROI; corrected book settlement | **NOT_ADOPTED** for trading |
| Six-feature strict-lag goalie rule | OOF ΔBrier +0.014774 vs market | **DISCARD** |
| Historical player props | no target-period quote archive; sampled outcomes fail settlement-grade gate | **NO PRICE-BASED TEST** |

## Entries

### 2026-10-19 — The NHL market benchmark now exists, and it sets the bar at 0.23554
**Learned:** SBR's historical odds archive survives in the Wayback Machine (the live URLs 404).
16 season files, 2007-08 → 2022-23. Only 2018-19 onward carries a complete two-sided market:
moneyline open and close, puck line, and total open and close. Normalised to **5,131 complete
games**, no-vig closing moneyline Brier **0.23554** pooled (0.24150 / 0.24323 / 0.23169 / 0.22562 /
0.23897 by season).
**Evidence:** `docs/NHL-MARKET-BENCHMARK-SBR.md`, `research/nhl/sbr-odds-archive-2026-10-19/`.
**Consequence:** every NHL model claim is now measured against a market number instead of against
another model. Pre-2018-19 seasons cannot produce a no-vig benchmark — one row in two carries a
total string instead of a price, so the pair is not priced on both sides. Do not quote them as one.

### 2026-10-19 — Closing prices are a benchmark, never a bettable price
**Learned:** the archive has open and close columns and **no intraday timestamp** — no T−90, no
book, no capture time. A closing price cannot be treated as what the model could have bet earlier
in the day.
**Evidence:** field inventory of every season file.
**Consequence:** backtests may use the open or the close, and must say which. Strategy results
quoted at "historical prices" without that distinction are unfalsifiable.

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

### 2026-10-19 — The special-teams result is now reproducible, and still not adoptable
**Learned:** the auditor gap closed. `forecasts_all_arms.csv` carries 36,588 rows (9,147 games ×
4 arms) and `verify_from_csv.py` recomputes every score from it without calling `fit_arm`.
REPRODUCTION PASS: 0 non-PIT mismatches above 1e-9, max absdiff 4.4e-05 on 4-dp PIT rounding.
Leakage audit: 73,176 checks, 0 mismatches, 0 source-date violations.
**Evidence:** `research/nhl-special-teams-2026-10-19` `d3105e3d` (CSV normalised to LF in
`dc1c7d57`); the verifier still passes after the reformat.
**Consequence:** reproducibility was the blocker and it is gone. The verdict is still not-adopted
because CRPS's interval [−0.000467, +0.000293] spans zero — the conjunctive keep rule fails, and a
recomputable result is not a keepable one. Do not re-litigate this as an audit problem.

### 2026-10-19 — Do not let a CSV's line endings masquerade as a finding
**Learned:** both special-teams CSVs were CRLF, so `git diff --check` flagged every one of 45,737
lines. A reformat-only commit is safe when the verifier runs before and after.
**Evidence:** `dc1c7d57`, reproduction PASS on both sides.
**Consequence:** normalise generated deliverables to LF at write time; a dirty `diff --check`
should never be mistaken for a content change.

### 2026-10-19 — The printed edge is points, not probability
**Learned:** the card's "Edge 1.3 pts (ANA)" is `|locked puck line| − favourite margin`, the gap
between the Vegas line and the model line. The first implementation compared a probability
difference (7.8 percentage points) against the 1.0 threshold, which every game cleared, so rule 1
fired on all of them and every pick came out as the underdog +1.5.
**Evidence:** `d007e540`; four card games now resolve to ANA +1.5 (S 1.3), COL ML (S 0.4),
SJS +1.5 (S 1.2), UTA ML (S 0.9).
**Consequence:** when a rule is copy of a printed quantity, test it against the printed number on
real cards before shipping. A threshold that never fails is a broken threshold.

### 2026-10-20 — Existing NHL team features do not beat the moneyline market
**Learned:** the frozen opening-price policy selected 886 of 2,686 eligible games (32.99%) and
returned **−27.58 units / −3.11% ROI** (90% season-clustered interval [−7.5%, +0.3%]). Paired
profit versus the no-vig market policy was **−1.072 pp per eligible game** ([−2.569, +0.000]).
Market Brier was 0.2352 and beat every augmented variant. Removing the three underround pairs
still returned −3.44%; closing-price sensitivity was −5.38%, though closing quotes have no
execution timestamp. The final archive block is only 339 games, Oct 11–Nov 27, 2022; the frozen
holdout made three bets in that seven-week slice.
**Evidence:** `research/nhl/ml-selectivity-2026-10-20/RESULTS.md`, `7e26e37e`; coverage
disclosure `71d9690c`.
**Consequence:** **NOT_ADOPTED**. Do not retune the existing team-feature thresholds on these same
seasons. A future candidate needs genuinely new pregame information and a fresh, complete holdout.

### 2026-10-20 — The corrected `leeway-2` replay still loses at posted prices
**Learned:** corrected walk-forward replay graded 5,126 picks at **−132.64 units / −2.6% ROI**
(90% season-clustered interval [−4.1%, −0.9%]); moneyline returned −2.4% and +1.5 returned
−2.7%. The 2022–23 contribution is only the 339-game archive slice, Oct 11–Nov 27, 2022. No
regime had a positive interval excluding zero. Review found the earlier harness graded
moneyline from a statistical target that omits the shootout-deciding goal: all 2,141 shootout
games could be settled incorrectly, moving the result by about 101.7 units in the frozen-model
comparison. The corrected rule uses the official winner for moneyline and the regulation-plus-OT
target for puck lines and totals.
**Evidence:** `research/nhl/matchup-strategy-2026-10-20/RESULTS.md`, `56d954ed`.
**Consequence:** **NOT_ADOPTED** for trading. Settlement semantics must follow the market contract;
even after fixing the large evaluation defect, the strategy remains negative.

### 2026-10-20 — Six strict-lag goalie features fail the preregistered keep rule
**Learned:** of 4,763 eligible games, 1,254 from 2018–19 were training-only; the distinct
out-of-fold denominator was 3,509 games across four blocks. The final block is the same partial
339-game 2022–23 archive slice, with 307 eligible rows. Goalie-model Brier was **0.250295** vs
**0.235522** for the raw no-vig opening market (Δ +0.014774; 90% season-block interval
[+0.010330, +0.019367]); log loss was 0.695958 vs 0.664212. The frozen policy returned −99.012
units / −4.946% ROI on 2,002 bets. The no-vig policy control fired on only 3 of 3,509 games, so
the paired policy comparison has very low control activation. Strict-lag feature construction
passed its source-date audit; this result is about the registered six-feature learner, not
announced starters or the broader V3 simulation design.
**Evidence:** `research/nhl/goalie-features-2026-10-20/RESULTS.md` and `JOIN-AUDIT.md`,
`3ed20903`; preregistration `52951d5b`.
**Consequence:** **DISCARD** this keep rule. Do not treat a clean leakage audit as evidence of
predictive value, or generalize this null result to future confirmed-starter or shot-location
features.

### 2026-10-20 — The audited local sources contain no historical pregame starter or injury feed
**Learned:** the source inventory matched all 5,132 SBR rows to canonical game IDs (4,872 regular
season, 260 playoff). The audited injury, roster, and availability tables had no NHL historical
game-status rows; starter flags and actual goalie usage were postgame. Historical goalie-season
summaries and rolling team features exist, but must be strictly lagged and do not identify the
announced starter. Shot-level rows also lack a direct canonical game key and do not cover the
entire target archive through an unambiguous bridge.
**Evidence:** `research/nhl/newinfo-audit-2026-10-20/AVAILABILITY.md`, `5ee6b5f8`.
**Consequence:** the local archive cannot support a historical test of announced starters,
injuries, scratches, or pregame line assignments. State the source and coverage when claiming a
data gap; never recast postgame use as pregame knowledge.

### 2026-10-20 — SOG and saves outcomes are reconstructable, but not yet settlement-grade
**Learned:** the NHL archive has 175,289 skater-game SOG values, including 40,224 explicit zeros,
and 10,410 goalie appearances with nonnegative saves reconstructed as shots against minus goals
against, across the 4,872 regular-season SBR games. A seeded official GameCenter audit of 300
games found 10,759/10,798 union skater rows exact (99.639%), but 13 games had two or more SOG row
mismatches; the signed correction rule therefore failed. Goalie shared-row agreement was 98.140%,
but official boxscores also returned 555 zero-minute backup slots absent from the archive. Verdict:
**NOT_SETTLEMENT_GRADE**. The sample used a 4,876-game canonical regular-season frame, four games
larger than the SBR target population; it is an audit sample, not a census.
The local NHL prop table had 83,720 rows, all dated in 2026, and **zero** quotes in the
2018–19 through partial 2022–23 target window. Its snapshots table had no NHL rows, so these are
current/last-captured quotes rather than historical price movement.
**Evidence:** `research/nhl/prop-feasibility-2026-10-20/FEASIBILITY.md` and
`RESULTS-RECON.md`, `c1fa948e` (reconciliation audit `cc50e244`).
**Consequence:** outcome coverage alone does not establish official settlement quality, and no
historical price comparison or ROI can be calculated without target-period player-prop quotes.
Keep any outcome-only work separate from a market or profitability claim.
