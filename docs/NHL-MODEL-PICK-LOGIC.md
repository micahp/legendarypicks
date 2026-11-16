# NHL Model Pick Logic

**Status:** Implemented 2026-10-15. Open questions at the end.
**Scope:** `modelPick()` in `components/Leagues/NhlModelTab.tsx`, for the model selected on the card.

---

## Definitions

- **Vegas line:** the home puck line, always ±1.5 in the feed we use.
- **Model line:** the model's projected goal margin for the home team.
- **Spread edge S:** `|Vegas line − model line|` in goals. It is an absolute number of points, not a probability.
- **Model favorite:** the team with the higher projected margin.
- **Edge team:** the team the model's line gives more points than Vegas does. The card prints the spread edge as "pts (X)" for this team. It is usually the Vegas underdog, because the model's favorites are less than a goal ahead of Vegas's line.

## Rule

The goal is leeway: a win is safer than a cover, and a cover is only worth taking when the edge is clear.

1. **Edge team is the Vegas underdog (+1.5) and S shows over 1.0 on the card:** bet it **to cover +1.5**. They might cover.
2. **Otherwise, if Vegas has the model's favorite favored by 1.5:** bet it **to win** (moneyline). A 1.0 edge is too risky to cover, so WPG @ CHI (S shows 1.0) is WPG ML.
3. **Otherwise:** pick a total. The line is **5.5** when the model's projected total is 6.0 or below, and **6.5** above that. The side is **Over** when the projection is above the line and **Under** when it is below. The 6.0 cut is the median total in 2023, 2024 and 2025 (6.0 each season). Over 5.5 hit 54 to 57% of those games, and Over 6.5 hit 40 to 44%. This is a data-based heuristic, not a calibrated probability.
4. **Every game gets a pick.** There is no minimum edge and no suppression.
5. **Edge** on the card is the model's probability for that bet minus its no-vig market probability. It is shown only when that bet's price is posted. Over 5.5 has a price only when the posted total is 5.5.
6. **S is compared as the card prints it**, to one decimal place.

Probabilities used:
- Moneyline: `home_win_probability` (or its complement for away).
- Cover: `p_home_plus_1_5` or `p_away_plus_1_5` for the underdog.
- Over 5.5: `p_over_5.5`.

## Not used

- The biggest edge across all props. This was tried and replaced by the spread gate above.
- A 3% minimum edge. It would leave games without a pick.
- A model-consensus check across B3, B5 and B7. The card uses the selected model.

## Examples (2026-10-15 slate, B7)

| Game | Vegas line | Model line | S | Model favorite | Pick |
|---|---|---|---|---|---|
| BUF @ TOR | TOR −1.5 | BUF −0.4 | 1.9 | BUF (Vegas underdog) | BUF +1.5 |
| NYR @ NJD | NJD −1.5 | NJD −0.4 | 1.1 | NYR (Vegas underdog, edge over 1.0) | NYR +1.5 |
| WPG @ CHI | WPG −1.5 | WPG −0.5 | 1.0 | WPG (Vegas favorite) | WPG ML |
| SEA @ TBL | TBL −1.5 | TBL −1.1 | 0.4 | TBL (Vegas favorite, model agrees) | TBL ML |
| CGY @ VGK | VGK −1.5 | VGK −1.2 | 0.3 | VGK (Vegas favorite, model agrees) | VGK ML |

## Open questions

**Should record, points, and xG change a pick?** Not yet. The card has the data: standings give wins, losses, OT losses and points, and `feature_snapshot.xg_features` gives each team's rolling 10-game 5v5 xGF and xGA. Neither enters the rule above. Proposed: use team xG for the Under question below, and show record and points only as context.

**Is the 6.0 cut right once the totals are calibrated?**

The fallback sends any projection of 6.0 or below to the 5.5 line, and anything above to 6.5. The model's projections sit below 2025-26 scoring on the slate we checked (average 5.9 against 6.16), so the cut may send too many totals to Under. Possible refinements, none decided:

- model total below a cutoff (for example 6.0)
- posted total above or below the model total by a set amount
- a calibrated totals model, once there are enough graded games to check it

Decide this after the totals are checked against graded results.
