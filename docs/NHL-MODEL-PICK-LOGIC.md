# NHL Model Pick Logic

**Status:** Implemented  
**Date:** 2026-10-15  
**Scope:** `modelPick()` in `components/Leagues/NhlModelTab.tsx`

---

## Two decisions

The model pick logic makes two decisions:

1. **Moneyline vs. Total** — should we pick a team to win, or the over/under?
2. **Which side** — if moneyline, which team? If total, over or under?

---

## Decision 1: Moneyline or Total?

The deciding factor is the **spread edge** — the absolute difference between the Vegas puck line and the model's projected goal differential.

```
spread_edge = |Vegas line − model line|
```

| Spread edge | Pick type | Rationale |
|---|---|---|
| **> 1.0 goals** | **Moneyline** | A >1.0 goal disagreement means the model sees a real edge. Bet on the team the model likes more than Vegas. |
| **≤ 1.0 goals** | **Total (O/U)** | The spread is too close to call — the model and Vegas roughly agree. The safety net is the total. |

**Why this threshold?** A 1.0 goal edge means the team could cover the spread and still lose the game. Below 1.0, the model doesn't have enough confidence to pick a winner. Above 1.0, the edge is large enough to survive the spread.

---

## Decision 2a: Which team (when spread edge > 1.0)?

The pick goes to the team the **spread edge favors**:

- If the model and Vegas both favor the same team → edge favors that team (the model just likes them less/more)
- If the model and Vegas disagree → edge favors the team the **model** likes

The ML edge is then: `model win probability − no-vig market probability` for that team.

---

## Decision 2b: Over or Under (when spread edge ≤ 1.0)?

**Open question.** The current implementation picks whichever of Over/Under has the larger probability edge at the available total line (5.5 or 6.5).

| Model total | Current behavior | Desired behavior |
|---|---|---|
| ≥ 6.0 | Over 5.5 | Over 5.5 ✓ |
| < 6.0 | Under 6.5 (by edge) | **Unknown** — conditions for Under not yet defined |

**What we know:**
- The safety net is Over 5.5 when the model predicts ~6 goals
- There is a case where the Under is the right pick, but the conditions are unclear

**What's needed:**
- Define the Under conditions (e.g., model total < X? market total < Y?)
- Consider: does the Over/Under pick also need a minimum edge threshold?

---

## Examples

| Game | Vegas line | Model line | Spread edge | Pick | Why |
|---|---|---|---|---|---|
| BUF @ TOR | TOR −1.5 | BUF −0.4 | **1.9** | BUF ML | Spread edge > 1.0, favors BUF |
| CGY @ VGK | VGK −1.5 | VGK −1.2 | **0.3** | Over 5.5 | Spread edge ≤ 1.0, safety net |
| SEA @ TBL | TBL −1.5 | TBL −1.1 | **0.4** | Over 5.5 | Spread edge ≤ 1.0, safety net |

---

## Open questions

1. **Under what conditions should we pick Under instead of Over?** (model total threshold? market total? edge?)
2. **Is 1.0 goals the right spread edge threshold?** (could be 0.5, 1.5, etc.)
3. **Should the O/U pick also require a minimum edge?** (to avoid picking O/U when the model has no opinion)
