# RESULTS: real scores in the NFL season simulation (history option)

Run 2026-10-13 on the dev DB, opened read-only. The rules and gates are in the
`backend/nfl_sim_scores.py` docstring, committed in 1e5fce6 before any run. The harness is
`backend/backtest_nfl_sim_scores.py` (04b49e9). Runtime was 1121 s in one process under nice.
K = 25 was chosen by the pre-registered walk-forward rule on 2011-2019 decisive games only.
Conditional score-pair log loss: K=25 3.8150, K=50 4.4284, K=100 4.9577, K=200 5.3632, n = 2155.

**Verdict: G4 FAILS, so "placeholder" stays the default.** G1, G2, G3, G5 and G6 pass. The
history option is in the code and can be selected, but the pre-registered rule says it does
not become the default.

## Pool
The pool comes from the DB through `nfl_backtest.backtest_season`. For 2010-2023 it is the same as
`nfl_score_dist.load_history` (rehearsal CSV): 3408 of 3408 games matched, the largest coordinate
difference is 1e-13, and 0 scores differ. Pool sizes by test season: 2401 (2020) to 3664 (2025).
The pool holds 6 to 9 tie games. The tie rate is measured from nfl_schedule over 2010..s-1:
0.313% (2020) to 0.357% (2023). For 2026 it is 13 / 4175 = 0.311%.

## G1 Outcome calibration: PASS
Test set: 1519 test games (2020-2025, weeks 2+), 20000 draws each, 30.38M draws in total.
- In every p bin, the simulated P(home | decisive) is within 1.51 SE of the mean p (the bins hold
  59,796 to 6.46M decisive draws). The tie rate in the draws is 0.3251% against 0.3253% expected,
  z = -0.22.
- Win Brier on 1515 decisive games: simulated p_hat 0.228285, Normal 0.228281. The difference is
  4e-6, which is Monte Carlo noise, inside the 0.0005 bound.

## G2 Validity: PASS
- The G1 draws contain 0 invalid pairs. Every distinct drawn pair, total and margin appears among
  the nfl_schedule REG finals of 2010..s-1, which were read directly and not from the pool.
- The G5 history runs simulated 6,740,000 games with 0 invalid. All scores are non-negative
  integers that appear in nfl_schedule. The simulated tie rate is 0.319% (21,493 ties), inside
  0.1% to 0.4%.

## G3 Totals: PASS
On the same 1519 games, the mean simulated total is 45.64 against an actual 45.84. The sd is
13.89 against 13.81, a ratio of 1.006. The P(total > total_line) calibration SSE is 0.1889 over
6 bins for this method and 0.2167 over 5 bins for the A2 bivariate Normal comparator. The A2
sampler scored 0.1981.

## G4 Season level: FAIL
Test set: seed A, cutoff after week 5, simulated games only, 2020-2025 averaged.

| | league ppg | across-team sd of ppg | across-runs sd of a team's ppg |
|---|---|---|---|
| real | 22.76 | 4.57 | n/a |
| history | 23.03 (pass, within 1.0) | 3.62, ratio 0.791 (FAIL, needs 0.80-1.25) | 2.75 |
| placeholder | 20.00 | 2.98, ratio 0.653 | 1.93 |

The spread of points across teams is 21% narrower than in real seasons, just outside the
pre-registered 0.80 bound. The placeholder is further off on both measures. One possible cause,
**not measured**: the sampler draws scores around the model's expected points, so the spread
across teams inherits the v1 ratings' regression toward the mean. A real season also contains
how strong each team turned out to be. No threshold or constant was changed after seeing this.

## G5 Playoff odds: PASS
Test set: 2020-2025, cutoffs after weeks 5 and 12, n = 2000, k = 0, 384 team forecasts per metric.

| | Brier playoffs | Brier division | log loss playoffs | log loss division |
|---|---|---|---|---|
| placeholder A | 0.13262 | 0.12121 | 0.4058 | 0.3767 |
| placeholder B | 0.13319 | 0.12072 | 0.4051 | 0.3742 |
| history A | 0.13277 | 0.12135 | 0.4071 | 0.3787 |
| history B | 0.13190 | 0.12142 | 0.4030 | 0.3769 |

- Playoffs: the difference (history A minus placeholder A) is +0.00015. The noise is 0.00087,
  so the bound is 0.00174.
- Division: the difference is +0.00014. The noise is 0.00049, so the bound is the 0.001 floor.
- The mean absolute per-team change in p_playoffs is 0.70 points. The largest is IND 2024 after
  week 5, 0.362 to 0.403 (4.05 points). Seed to seed, the largest per-team change is 3.45 points
  for the placeholder and 3.50 for history, so the option changes are Monte Carlo scale.

## G6 Ties: PASS
Across 48,000 simulated seasons (history, both seeds):
- No exception was raised.
- 0 seasons violated the seeding invariants.
- 17,036 seasons contain a simulated tie. In 9,675 of them, deciding each tie by one point
  for either side changes a seed. In 4,596 of them it changes the playoff field. These two
  counts are for alphabetical-coin seeding, so the tie is the only thing that differs.

## 2026 after week 5, computed in memory (nothing written)
n = 20000, the same seed for both options. The largest per-team change in p_playoffs is 1.2
points (PIT 53.4% to 54.6%). With history, a different seed moves a team by up to 0.9 points.
Top teams, placeholder to history:
SF 99.6 to 99.7, JAX 98.9 to 98.8, MIN 97.6 to 97.3, KC 93.2 to 93.6, NE 90.2 to 90.0,
BUF 86.4 to 86.2, SEA 69.7 to 69.8.
