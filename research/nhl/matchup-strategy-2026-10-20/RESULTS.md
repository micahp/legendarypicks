# NHL matchup strategy — historical profitability (Phase 1-3, revision 2)

Branch `research/nhl-matchup-strategy-v1`. Read-only research: no deployment, no production
forecast, no model change.

This revision replaces the measurement harness from `f3d53766` after review found look-ahead,
a standings bug and incorrect settlement in it. The original numbers are kept at the bottom as a
superseded diagnostic. **The strategy still loses, but by half as much: −2.6% over 5,126 picks,
not −4.4%. Verdict: NOT_ADOPTED for trading.**

## Headline

| | picks | W–L | units | ROI |
| --- | --- | --- | --- | --- |
| moneyline | 2,154 | 1,389–765 | **−52.61** | **−2.4%** |
| spread +1.5 | 2,972 | 1,964–1,008 | **−80.03** | **−2.7%** |
| **all** | **5,126** | **3,353–1,773** | **−132.64** | **−2.6%** |

Opening prices; walk-forward model; book-correct settlement. Closing ML is −2.3% — the loss is not
a stale-price artefact. No regime rescues it (see below). The one positive cell that survives the
corrections is +1.7% on 162 ML picks, about a fifth of one standard error.

## What the v1 harness got wrong

| # | Defect | Effect |
| --- | --- | --- |
| 1 | Moneyline settled from `*_goals_model_target`, which excludes the shootout-deciding goal | 2,141 shootout games could grade a winning ML as a loss. Worth **+101.7u** on its own. |
| 2 | 2026-fitted B7 v1 coefficients applied to 2018-19 games | Leakage; worth **−2.5u** once fixed, i.e. it was not flattering the strategy. |
| 3 | Standings accumulated across seasons; shootout games scored off a tied target | Regime labels were meaningless; gives the away team the win on every shootout. |
| 4 | One `puck_price` copied into open and close | The "closing spread" sensitivity compared a price to itself. |
| 5 | Home side's over/under quote used for both sides | 1,737 of 5,132 rows carry different prices per side. |
| 6 | Unmatched and unforecastable rows skipped without a counter | 8 rows lost, no reconciliation. |

Settlement is now split the way books settle: **moneyline includes overtime and the shootout**
(`official_home_winner`); **puck line and totals end at overtime** (`*_goals_model_target`). The
data confirms the split: every one of the 21,081 non-shootout games has target = official score,
and every one of the 2,141 shootout games has a tied target with the extra goal in the official
score.

## Ablation: which correction moved the number

5,126 graded picks in every arm. `legacy` = v1's settlement, `book` = corrected settlement.

| model | settlement | ML units | spread units | all units | ROI |
| --- | --- | --- | --- | --- | --- |
| frozen through 2025-26 | legacy | −147.27 | −79.78 | −227.05 | −4.4% |
| frozen through 2025-26 | book | −45.53 | −79.78 | −125.31 | −2.4% |
| walk-forward | legacy | −149.56 | −80.03 | −229.59 | −4.5% |
| **walk-forward** | **book** | **−52.61** | **−80.03** | **−132.64** | **−2.6%** |

The first row reproduces the published v1 result (−226.6u / −4.4%); the small difference is the
two rows recovered by fixing name matching. **The shootout settlement bug, not the leakage, is
what made the strategy look 2 points worse than it is.** Removing the leakage makes the result
marginally worse, so the look-ahead was not hiding a profitable edge.

Model folds (each refit only on prior seasons, same architecture as the frozen arm):

| eval season | train | games | intercept | coef (home, xGF, xGA, Elo) | tie-home |
| --- | --- | --- | --- | --- | --- |
| 2018-19 | 2008–2017 | 12,611 | 0.7304 | 0.1008 / 0.1951 / 0.1816 / 0.2913 | 0.4922 |
| 2019-20 | 2008–2018 | 13,969 | 0.7167 | 0.1008 / 0.2034 / 0.2044 / 0.2868 | 0.4937 |
| 2020-21 | 2008–2019 | 15,181 | 0.7154 | 0.0978 / 0.2117 / 0.2062 / 0.2849 | 0.4902 |
| 2021-22 | 2008–2020 | 16,133 | 0.7234 | 0.0979 / 0.2054 / 0.2017 / 0.2956 | 0.4897 |
| 2022-23 | 2008–2021 | 17,529 | 0.7033 | 0.0970 / 0.2325 / 0.2168 / 0.3045 | 0.4909 |

## Population reconciliation

Every SBR row is accounted for exactly once.

| bucket | rows |
| --- | --- |
| SBR rows | 5,132 |
| team name unmapped | 0 |
| no canonical match | 0 |
| home/away orientation mismatch | 1 |
| no pregame features (incomplete window) | 5 |
| no walk-forward forecast | 0 |
| no pick: odds missing | 0 |
| **graded** | **5,126** |

The orientation row is 2020-01-17 DET/PIT: the canonical file lists Detroit at home, SBR and the
official record have Pittsburgh at home. The five feature gaps are Seattle's first five franchise
games (2021-10-12 → 10-19), which have no rolling-10 window. Two SBR name variants ("Seattle",
"Arizonas") were previously dropped as unmapped and are now matched.

## By matchup regime — corrected

Three definitions, all classified from pregame season-to-date state with cuts frozen on
2008-09…2017-18. Standings are now built from **all 23,222 canonical games**, not just the ones
with a complete xG window, so a team's record counts every game it played.

- **points** — v1's points-percentage terciles (0.536 / 0.579), kept for comparability.
- **goals** — composite of points percentage and goal differential per game.
- **goals_xg** — the same composite plus rolling-10 5v5 xG differential per game.

`mixed` is gone: every different-strength pairing is now its own bucket.

**points** (n / units / ROI):

| regime | ML | spread +1.5 |
| --- | --- | --- |
| early (<10 GP) | 340 / +9.83 / +2.9% | 489 / −8.06 / −1.7% |
| strong-mid | 213 / **+22.19 / +10.4%** | 341 / +2.86 / +0.8% |
| strong-strong | 295 / −12.26 / −4.2% | 677 / −21.06 / −3.1% |
| strong-weak | 903 / −48.50 / −5.4% | 688 / −38.15 / −5.6% |
| mid-mid | 17 / −2.38 / −14.0% | 61 / −4.47 / −7.3% |
| mid-weak | 180 / −5.51 / −3.1% | 269 / −9.95 / −3.7% |
| weak-weak | 206 / −15.99 / −7.8% | 447 / −1.19 / −0.3% |

**The one large positive cell does not survive inspection.** strong-mid ML is +10.4% on 213 picks,
but it is two seasons: 2020-21 +13.0u and 2021-22 +17.4u, against 2018-19 −3.1u, 2019-20 −4.3u and
2022-23 −0.8u. Season-clustered 90% CI: **[−7.3%, +26.5%]**. It also moves with the definition —
+10.4% under points, +1.4% under goals, **−11.3% under goals+xG** — which is what a composition
artefact looks like, not an edge.

The spread side of the same bucket is small and consistent-ish (+0.8% / +2.4% / +3.3% across the
three definitions), but every one of those intervals spans zero as well
([−5.2, +6.6], [−2.0, +7.1], [−2.9, +10.9]). The same goes for the goals+xG strong-strong ML cell
that looked positive in revision 2: +1.6% on 164 picks, clustered interval [−5.1%, +5.2%].

## Early-season moneyline — the other positive

340 picks, +9.83u, +2.9%, clustered 90% CI **[−3.2%, +11.0%]**. By season:

| season | n | W–L | units | ROI |
| --- | --- | --- | --- | --- |
| 2018-19 | 74 | 44–30 | −5.46 | −7.4% |
| 2019-20 | 50 | 32–18 | +0.92 | +1.8% |
| 2020-21 | 64 | 49–15 | +13.09 | +20.5% |
| 2021-22 | 65 | 44–21 | +3.08 | +4.7% |
| 2022-23 | 87 | 56–31 | −1.80 | −2.1% |

One season (2020-21, the 56-game division-only year) carries the whole result. Not a signal to
trade; a reason not to claim the bucket is empty either.

## Rule version: this is leeway-2, not goal-diff-1

The harness replays `leeway-2` exactly, verified against `backend/nhl_model_store.py`:
`S = |puck| − favourite_margin` (the same value `_underdog_points_edge()` prints), gate at 1.0,
ML only when the model's favourite matches Vegas', totals at 5.5/6.5. Two consequences:

- The October ledger rows that supplied the brief's positive impression were written under an
  earlier `rule_version` (`goal-diff-1`, and `leeway-1` before the S definition was corrected).
  This backtest is evidence about **leeway-2**; it is not a retro-validation of those rows.
- Production rule 2 falls through to a total when no ML price is posted. The replay returns no
  pick in that case. In this archive that path never fires (0 of 5,126 rows lacked an ML quote),
  so it changes nothing here, but it is a real difference for live cards.

## By season

| season | ML units (ROI) | spread units (ROI) |
| --- | --- | --- |
| 2018-19 | −37.94 (−7.4%) | −28.73 (−3.4%) |
| 2019-20 | −13.57 (−3.4%) | **+14.00 (+2.1%)** |
| 2020-21 | −0.28 (−0.1%) | −4.19 (−0.8%) |
| 2021-22 | +9.56 (+1.4%) | −53.26 (−7.3%) |
| 2022-23 | −10.38 (−6.2%) | −7.85 (−4.6%) |

Two positive market-seasons out of ten, neither larger than noise.

## Why totals never fire — structurally, not for lack of quotes

The cascade only considers a total when the spread branch fails (`S = 1.5 − favourite_margin
≤ 1.0`) **and** the model's favourite differs from Vegas'. For |puck| = 1.5 those conditions
contradict: `S ≤ 1.0` implies `favourite_margin ≥ 0.5`, which puts the model's favourite on the
same side as Vegas, so rule 2 fires instead.

Counted over the replay: spread branch 2,972, ML branch 2,154, total branch **0** — with zero
missing total quotes. It is not a historical-coverage artefact; the branch is unreachable in the
current rule for any game with a 1.5 puck line. The production cascade's live totals only appear
because live cards can lack the spread or ML quote, which is an absence of a price, not a signal.

## What this means

The hierarchy is a losing strategy at posted prices: −2.6% over 5,126 picks across five seasons.
That is not just a point estimate — the season-clustered 90% interval is **[−4.1%, −0.9%]**, so
the negative survives the same clustering objection that killed v2. Both markets are negative, and
no regime cell is positive with an interval that excludes zero.

**Verdict: `leeway-2` is NOT_ADOPTED for trading.** It should not be used to place bets on its own,
and future model work should be judged against the −2.6% baseline rather than against Brier.

Two things stay open, neither of them a reason to keep this rule:

1. The strong-mid ML cell (+10.4% on 213 picks) and early-season ML (+2.9% on 340) are the two
   positives worth remembering. Both are season-driven and both have intervals spanning zero.
   Chasing them by tuning the strength cuts on these same games would be fitting noise; if either
   is tested again it needs a pre-registered definition and fresh games.
2. The original hypothesis — standings + actual GF/GA + xG as the selector itself, choosing ML,
   puck line, or no trade independently of this cascade — has still not been tested end to end.
   That is the next experiment, not another pass at this one.

## Superseded: v1 numbers (`f3d53766`)

Kept for the record. These came from a harness with the six defects above.

| market | n | W | L | units | ROI |
| --- | --- | --- | --- | --- | --- |
| moneyline | 2,266 | 1,397 | 869 | −146.84 | −6.5% |
| spread +1.5 | 2,858 | 1,892 | 966 | −79.78 | −2.8% |
| all | 5,124 | 3,289 | 1,835 | −226.62 | −4.4% |

The v1 regime table (strong-strong ML +0.2% on 206 picks) is likewise superseded: its labels came
from standings that never reset and its settlement misgraded every shootout.

## Reproduce

```
cd research/nhl/matchup-strategy-2026-10-20
uv run --with scikit-learn --with numpy python test_settlement.py
uv run --with scikit-learn --with numpy python backtest_matchup_strategy.py
```

Ablations: add `--frozen` (v1 coefficients), `--legacy-settlement` (v1 settlement), or both.
`--dump-rows` also writes `rows_<model>_<settlement>.jsonl` for cell-level analysis. Outputs
`results_corrected.json` for the corrected arm and `results_<model>_<settlement>.json` for the
others; each stores the reconciliation, the rule-branch counts, every table and the
season-clustered intervals.

Inputs: canonical games and pregame rolling features (audit directory, untracked),
`research/nhl/prospective-2026-27/frozen_models_2026-27_v1.json`, and
`/root/lp-data/nhl-sbr/games_2018_2023.jsonl`.
