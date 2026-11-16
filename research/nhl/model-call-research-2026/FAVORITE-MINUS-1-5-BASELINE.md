# Favourite −1.5 baseline, SBR published prices (2018-19 → 2022-23)

Unconditional settlement of all three sides on the same archived games. No model, no
selection rule: this is the floor any −1.5 strategy has to beat, and it answers whether
switching underdog +1.5 tickets to favourite −1.5 is a fix on its own.

Script: `run_favorite_puckline.py` (input `../sbr-odds-archive-2026-10-19/games_2018_2023.jsonl.gz`).

## Sample

5,129 games with both finals, both ML opens and both puck prices. 4,821 (94.0%) have the
moneyline favourite carrying −1.5; the other 308 have the ML favourite on +1.5 (near pick'em).

## Flat 1u, opening prices

| side | record | cover % | units | ROI | avg price | break-even cover |
| --- | --- | --- | --- | --- | --- | --- |
| favourite ML | 2,902–1,919 | 60.2% | −125.7u | **−2.61%** (se 1.16) | −173 | 61.8% |
| favourite −1.5 | 1,835–2,986 | 38.1% | −146.7u | **−3.04%** (se 1.82) | +142 | 39.5% |
| underdog +1.5 | 2,986–1,835 | 61.9% | −141.1u | **−2.93%** (se 1.12) | −176 | 63.9% |

Closing prices agree within a few tenths: −1.80% / −3.11% / −2.90%.

Paired on identical games, −1.5 minus ML = **−0.0044 u/bet**, 95% CI [−0.032, +0.023]
(close: −0.0131, CI [−0.040, +0.014]). The two sides are economically the same bet;
−1.5 does not add or remove edge.

## By favourite price band (open)

| favourite ML | side | bets | record | ROI | 95% CI |
| --- | --- | --- | --- | --- | --- |
| −101/−140 | ML | 1,856 | 1,007–849 | −2.81% | [−6.87, +1.26] |
| −101/−140 | −1.5 | 1,856 | 631–1,225 | **+1.03%** | [−5.40, +7.46] |
| −141/−200 | ML | 1,971 | 1,203–768 | −2.18% | [−5.64, +1.27] |
| −141/−200 | −1.5 | 1,971 | 744–1,227 | −4.71% | [−10.14, +0.73] |
| −201+ | ML | 994 | 692–302 | −3.08% | [−7.08, +0.92] |
| −201+ | −1.5 | 994 | 460–534 | −7.34% | [−13.63, −1.05] |

## Per season, −1.5

2018-19 −3.6% · 2019-20 −6.5% · 2020-21 −3.8% · 2021-22 +1.0% · 2022-23 −4.4%.
One positive season out of five, same as the ML hierarchy.

## Reads

1. The −1.5 payout (+142 average) does compensate for the 38% cover rate — break-even is
   39.5% and the side lands 1.4 points short. It is not a pricing error, it is the vig.
2. Blunt switch +1.5 → −1.5 changes nothing: −2.93% vs −3.04%.
3. Only unpriced-looking slice is cheap favourites (−101/−140) on −1.5 at ~+198. +1.03% on
   1,856 bets with a CI spanning ~13 points is not evidence.
4. Big favourites at −201 or shorter are the worst −1.5 bets (−7.34%, CI entirely negative):
   the market prices 2+ goal wins correctly and the price collapses to about even money.

Requires selection that beats the market on *margin*, not on winner. Nothing here shows the
model has that; B7 v1's P(home by 2+) is already behind the closing line.
