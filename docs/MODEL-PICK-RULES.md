# Model Pick Rules

**Status:** Generic rule, 2026-10-21. NHL implements it (`backend/nhl_model_store.py`, `model_pick`).
Other leagues adopt it by filling in their row in the parameter table below.

A **Model Pick** is the one bet the model makes for a game. It is a model output, not a wagering
recommendation, and it needs no separate lean or wager policy.

## The contract

1. The model projects the game.
2. The model makes **one** pick per game, per model version.
3. The pick is frozen at lock time, before the game starts, with the lines it was made against.
4. The frozen pick is graded after the game is final.

The pick shown before the game is the pick graded after it. A later line move, a rerun or a
changed projection never changes a locked pick. Each model version has its own picks, locks and
record.

## The rule

The goal is leeway: a win is safer than a cover, and a cover is only worth taking when the edge
is clear.

**Definitions**

- **Vegas line:** the posted spread for the home team at lock time.
- **Model line:** the model's projected home margin, in the same units.
- **Spread edge S:** `|Vegas line - model line|`, in points (goals, runs).
- **Edge team:** the team the model line gives more points than Vegas does.
- **Vegas favourite / underdog:** from the sign of the Vegas line.
- **Model favourite:** the team the model projects to win.

**Hierarchy.** Take the first rule that applies.

1. **Cover.** The edge team is the Vegas underdog and S is above the league's cover threshold:
   pick the underdog **to cover** at the Vegas line.
2. **Win.** Otherwise, if the Vegas favourite is also the model favourite: pick the favourite
   **to win** (moneyline).
3. **Total.** Otherwise pick the total from the league's two total lines. A projection at or
   below the midpoint between them uses the lower line, and one above it uses the higher line.
   Pick Over when the projection is above that line and Under when it is below. Near the
   midpoint this is the conservative side: Over the lower line (NHL: 5.8 projected is Over 5.5)
   or Under the higher line (6.3 projected is Under 6.5). A projection outside both lines takes
   the plain side (5.2 is Under 5.5, 6.8 is Over 6.5).

**Always**

- Every game gets a pick. There is no minimum edge and no suppression.
- Price, odds and edge percentages are shown for context when posted. They never change the
  selection.
- S is compared as the card prints it (one decimal place).
- A forecast missing a field that the deciding rule needs gives no pick. That is shown as
  missing, and a pick is never inferred from a market price.

## Grading

- Cover: win, loss or push against the frozen line.
- Win: win or loss on the final score. A tie (where the sport allows one) is `tie`.
- Total: win, loss or push against the frozen total line.
- Not final: pending. A missing pick is never counted as a loss.
- The record counts only graded, locked picks for that model version. Previews and unlocked
  projections never count.

Straight-up accuracy and Brier score are model evaluation metrics, reported separately. They
are not the Model Pick record.

## League parameters

| League | Cover threshold (S above) | Total lines | Status |
|---|---|---|---|
| NHL | 1.0 goal (the puck line is always 1.5) | 5.5 and 6.5, split at a projected 6.0 (the 2023 to 2025 median total) | Live (`leeway-2`) |
| NFL | Own order, see below | **Open:** NFL totals vary (about 37 to 54), so fixed lines do not carry over. Needs the pair of lines around the posted total. | Decided except totals, not built |

### NFL order (Micah, 2026-10-21)

NFL uses its own order built around the touchdown. V is the points Vegas favours its favourite by.
M is our model's projected margin for that same team (negative when the model has the underdog
winning). Still one pick per game: take the first rule that applies.

1. **Favourite to cover.** M >= 7 and M >= V: the favourite at -V. (Vegas KC -7, model KC by 9: KC -7.)
2. **Favourite to win.** V >= 7 or M >= 7: the favourite moneyline. (Vegas KC -7, model KC by 4: KC ML.)
3. **Underdog to cover.** V - M >= 3: the underdog at +V. (Vegas KC -4, model opponent by 1: opponent +4.
   Vegas KC -6, model KC by 2: opponent +6.)
4. **Favourite to win.** M > 0 (our model agrees on the favourite): the favourite moneyline.
   (Vegas KC -3, model KC by 1.5: KC ML.)
5. **Team strength decides the rest.** These are the games rules 1 to 4 leave: the model has the
   underdog winning by an edge under 3, a pick'em, or a dead-even projection. Each team is
   strong, mid or weak from season-to-date standings, taken before the game.
   - Strong vs weak: the strong team moneyline.
   - Same tier (strong-strong, mid-mid, weak-weak): the total. Lines still open.

   (Vegas KC -1, model opponent by 1: KC strong and the opponent weak gives KC ML. Both mid
   gives the total.)

Results so far: the NHL replay of `leeway-2` lost 2.6% at posted prices (`docs/LEARNINGS-nhl.md`).
That is why a Model Pick is not a wager.

## Related

- `docs/NHL-MODEL-PICK-LOGIC.md`: the NHL rule in full, with worked examples.
- `docs/NFL-MODEL-PICKS-THREE-MARKETS.md`: superseded. It describes three separate picks per
  game, which this rule replaces with one.
