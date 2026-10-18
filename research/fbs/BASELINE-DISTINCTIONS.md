# FBS baseline distinctions — read before quoting any number

Three kinds of number appear in our tables and in the published ladders, and they are
**not** comparable. Conflating them is the easiest way to make a model look better or worse
than it is.

## 1. Our own baselines (G0–G3) — market-blind, results-only

These are ours, defined in `AUDIT-FBS-BASELINE-20261017.md`. **G2 is NOT Glicko-2.**

| ID | What it is | Uses |
|---|---|---|
| **G0** | Constant P(home) = 0.50 | nothing. Brier exactly 0.2500 on any non-empty sample. Reference, not a model |
| **G1** | Historical home/neutral win base rate, Beta(1,1) smoothed, from earlier games only | completed results |
| **G2** | **Chronological Elo** — start 1500, logistic 400, home advantage 55, K=20, 25% offseason regression | completed results + scores |
| **G3** | Opponent-adjusted **score-margin** ratings (ridge 15, prior-season half-life one season), normal margin CDF | completed results + scores |

G2 and G3 are ours. **Glicko-2 is somebody else's model** and appears only in the published
ladder below, at 0.1890. Do not write "G2" when you mean Glicko-2.

Our measured numbers, walk-forward 2023–2025, 2,398 games, one-outcome Brier:

| | Brier |
|---|---:|
| G0 | 0.2500 |
| G1 | 0.2427 |
| G2 chronological Elo | 0.2133 |
| G3 margin-adjusted | 0.2155 |

## 2. Published market-blind ratings — comparable in kind to G2

These use game results only, so a results-only model of ours may legitimately be ranked
against them. Population sizes differ; treat the comparison as context, not a scoreboard.

| Model | Brier |
|---|---:|
| Colley | 0.2070 |
| **Basic Elo** | **0.1976** ← the only fair peer for our G2 |
| Glicko-2 | 0.1890 |
| Massey | 0.1847 |
| Margin Elo | 0.1820 |
| Simple ACR | 0.1773 |

## 3. Market-derived numbers — NOT models to beat

Two published figures are contaminated or are the market itself:

- **"Spread-implied betting line" 0.1714** is the **market's own forecast**, with the spread
  converted to a probability. It is a ceiling, not a competitor. A results-only model reaching
  0.1714 would be beating the market, which is extraordinary.
- **Blitzcast's 0.1813** is a model that **includes spread and market probability among its
  input features**. It scores near the market because it largely encodes the market. It is not
  a market-independent rating baseline and must never be compared to our G2 as an equal.

## The rule

- Compare G2 to **Basic Elo 0.1976**. That is the peer.
- Never compare G2 to 0.1714 or to 0.1813 as if they were the same class of object.
- Never present a market-input model as evidence that results-only modelling can reach the
  market.
- Any table that mixes these three classes must label the class in the row, not in a footnote.
