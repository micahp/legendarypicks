# TASK — Tennis scoreboard cards: show per-set game scores

## Goal
On the Scores page, tennis match cards (ATP / WTA) currently show only a single
sets-won number (and often nothing, because it's null). Change them to display the
**set-by-set game scores** — one score per set, like a real tennis scoreboard:

```
M. Stoiana     7  4  7
N. Brancaccio  5  6  5
```

(That match = Set 1 7-5, Set 2 4-6, Set 3 7-5.)

## The data (already available from ESPN — confirmed)
ESPN's tennis scoreboard returns per-set games under each competitor's `linescores`
array. For the match above: `competitorA.linescores = [7,4,7]`,
`competitorB.linescores = [5,6,5]`. The current `espn_client.games()` tennis branch
only reads the competitor `score` (sets won, frequently `None`) and never reads
`linescores`.

Raw shape (tennis events nest under `event.groupings[].competitions[].competitors[]`):
```
competitor.linescores = [ {"value": 7.0}, {"value": 4.0}, {"value": 7.0} ]
competitor.athlete.shortName = "M. Stoiana"
```

## Changes
1. **Backend — `backend/espn_client.py`, `games()` tennis branch:**
   Parse each competitor's `linescores` into a list of per-set games and add it to the
   normalized `home`/`away` dicts, e.g. `"sets": [7, 4, 7]`. Keep the existing fields.
   Integers (drop the `.0`).

2. **Frontend — `components/GameCard.tsx` (+ wherever tennis cards render):**
   For `atp`/`wta`, render the per-set columns from `home.sets` / `away.sets`
   (one column per set, monospace/tabular, winner of each set can be subtly bolded).
   Fall back gracefully to the old display if `sets` is empty (e.g. pre-match).

## Definition of done
- A FINAL tennis match card on the Scores page shows per-set scores (e.g. `7 4 7` /
  `5 6 5`), not a single number or blank.
- In-progress and pre-match cards still render sensibly (no crash on empty `sets`).
- Verify in the real UI: dev frontend on port 3095 (Cloudflare tunnel), backend on
  port 8095. Use a Grand Slam date with finals, e.g. `/scores?date=2026-01-26&league=ATP`.

## Constraints
- Dev only: backend `LP_DB_PATH=backend/data/picks.dev.db` on :8095, frontend :3095.
  Do NOT touch prod (`picks.db`, port 8000) or deploy.
- Work on a branch off `analytics-backbone`. No Claude/AI attribution on commits.
- This is additive — don't break the other sports' cards (NBA/MLB/NHL/NFL/soccer/COD).
