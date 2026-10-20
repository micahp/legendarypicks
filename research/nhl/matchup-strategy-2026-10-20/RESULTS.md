# NHL matchup strategy — historical profitability (Phase 1-3)

Branch `research/nhl-matchup-strategy-v1`, based on `origin/dev` at `e35ac195`.
Read-only research: no deployment, no production forecast, no model change.

## What was tested

The actual `model_pick()` hierarchy (leeway-2 semantics) replayed on the frozen **B7 v1
(Elo + rolling xG)** forecast, against SBR opening prices, 2018-19 → 2022-23, with matchup
regimes layered on top:

1. Vegas underdog (+1.5) with S = |puck| − favourite_margin > 1.0 → that side +1.5
2. else the Vegas favourite ML when the model's favourite is the same team
3. else a total (never reached in this replay — see below)

Chronology: Elo is replayed game by game and the xG inputs are the pregame rolling columns, so
no pick uses information from after its own start. Regimes use each team's points percentage as
of before the game, cut at the league terciles (0.536 / 0.579). Fixed constants, not fitted to
results.

## Population

- SBR rows: 5,132. Matched to canonical: **5,124**. Unmatched: 3 (team-code or date gaps).
- Picks generated: **5,124** — 2,266 moneyline, 2,858 spread, **0 totals**.
- Totals never fire in replay because rule 2 matches the Vegas favourite almost always; live
  cards show totals only when the quote is missing for the ML/spread candidate. The historical
  archive has fuller price coverage than the live feed, so this replay is not the live mix.

## Result at opening prices

| market | n | W | L | units | ROI |
| --- | --- | --- | --- | --- | --- |
| moneyline | 2,266 | 1,397 | 869 | **−146.84** | **−6.5%** |
| spread +1.5 | 2,858 | 1,892 | 966 | **−79.78** | **−2.8%** |
| all | 5,124 | 3,289 | 1,835 | **−226.62** | **−4.4%** |

Closing prices change nothing material: ML −6.3%, spread −2.8%.

## By matchup regime

| regime | market | n | units | ROI |
| --- | --- | --- | --- | --- |
| strong-strong | ML | 206 | +0.36 | +0.2% |
| strong-strong | spread | 268 | −20.49 | −7.6% |
| mid-mid | ML | 277 | −8.08 | −2.9% |
| mid-mid | spread | 346 | −6.93 | −2.0% |
| mixed | ML | 1,579 | −125.04 | −7.9% |
| mixed | spread | 1,966 | −18.71 | −1.0% |
| weak-weak | ML | 203 | −14.56 | −7.2% |
| weak-weak | spread | 274 | −32.56 | −11.9% |

One cell is non-negative and it is 206 picks at +0.2% — indistinguishable from zero. Everything
else loses, including every weak-weak bucket.

## By season

| season | ML units (ROI) | spread units (ROI) |
| --- | --- | --- |
| 2018-19 | −56.21 (−10.3%) | −21.89 (−2.7%) |
| 2019-20 | −37.34 (−9.1%) | **+10.23 (+1.5%)** |
| 2020-21 | −16.07 (−3.7%) | −15.68 (−3.1%) |
| 2021-22 | −24.51 (−3.5%) | −47.75 (−6.9%) |
| 2022-23 | −12.71 (−7.5%) | −4.70 (−2.8%) |

One positive season out of ten market-seasons.

## What this means

The hierarchy, as specified, is a losing strategy over five seasons and 5,124 picks. Matchup
classification does not rescue it: the only non-negative cell is inside the noise band, and the
weak-weak spread bucket — the one a selectivity rule would be designed to avoid — is the worst
cell on the board.

The structure of the loss is what you would expect from betting favourites and underdogs at
posted prices with no demonstrated edge over the closing line: the model's moneyline Brier is
0.2388 against a market 0.2363 on the same games. A rule can only be profitable if it selects
the subset where that gap inverts; no regime does.

## What was not tested

- Totals as a live-equivalent arm (no historical quotes missing, so rule 3 never triggered).
- Any selectivity policy fitted on early seasons and evaluated later — with every regime cell
  negative, there is nothing to select toward yet.
- Puck-line prices at the exact captured time (the archive has one line per game, no intraday
  timestamp).

## Reproduce

```
python3 research/nhl/matchup-strategy-2026-10-20/backtest_matchup_strategy.py
```

Inputs: canonical games and pregame rolling features (audit directory, untracked),
`research/nhl/prospective-2026-27/frozen_models_2026-27_v1.json`, and
`/root/lp-data/nhl-sbr/games_2018_2023.jsonl`.
