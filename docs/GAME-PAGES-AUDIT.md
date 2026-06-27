# Game Pages — what populates, by league + game state (audit 2026-06-27)

Honest state of `/game/[league]/[gameId]` before bumping the version. TL;DR: only **NBA**
has a real full game page (and only when games exist); **MLB** now has a **props-only** page;
**WC is a dead click**; NHL is flaky; everything else has no page.

## Which leagues have a game page
GameCard makes a card clickable when `hasDetail` = **NBA · NHL · WC · MLB**. What you actually get:

| League | Clickable? | Page content | Backend |
|---|---|---|---|
| **NBA** | yes | ✅ Full — box score + scoring timeline + score strip | `/api/{lg}/game/{id}/detail` (DB, or snapshots from ESPN on demand) |
| **NHL** | yes | ⚠️ Endpoint supports it but returned **empty** in testing (off-season; snapshot didn't populate) | same endpoint |
| **MLB** | yes | ✅ **Props-only** (Phase 3) — player props → expandable charts + player links. **No box score / score strip.** | `/api/game/{lg}/{id}/props`; detail endpoint **400s for MLB** |
| **WC** | yes | ❌ **Dead click** — detail endpoint rejects it ("only NBA and NHL") → empty "coming soon" page | unsupported |
| NFL / UFC / tennis / CoD | no | — (not clickable) | — |

## Behavior by game state (upcoming / live / final)

### NBA / NHL (the detail pages)
- **Final (post):** full box score + scoring timeline + final score (when ESPN has the data).
- **Live (in):** snapshot of the current state — partial box score + current score.
- **Upcoming (pre):** box-score snapshot fails pre-game → falls back to ESPN scoreboard → **minimal
  context only** (team names + 0–0), no box score.

### MLB (the props page)
- Shows the **Player Props** section for any game state that has **linked props**
  (`prop_games.espn_event_id`). Verified today (2026-06-27, MLB):
  - **Upcoming (pre):** 12 games, **9 have props** → charts (player history vs the line). 3 don't yet.
  - **Live (in):** 3 games, **all 3 have props**.
  - **Final (post):** none today; past finals carry settled props.
- **No score strip / live score** on the MLB game page (detail unsupported for MLB).
- A game with **no linked props** → empty "coming soon", even if it's a real game.

## Prop-linkage caveat
Props link to ESPN games via `prop_games.espn_event_id` (`link_prop_games.py`). Not every game
links: Bovada posts props closer to game time, and ~24% of `prop_games` have no `espn_event_id`
(link misses, e.g. KC@CWS). Those games open an empty props page.

## Known issues / recommendations
1. **WC dead click** — remove WC from `GameCard.hasDetail` until it has a real page (1-line fix).
2. **NHL detail unreliable** — empty in test (off-season). Verify in-season or treat as not-ready;
   consider gating its clickability too.
3. **MLB = props-only** — acceptable as the in-season betting view; a real box score = future
   backend work (extend the detail endpoint to MLB).
4. **Upcoming MLB w/o props** → empty page; consider a "no props yet" state or hiding the click.

## Seasonal reality (why you mostly saw nothing)
Late June: **only MLB is in season.** NBA/NHL seasons ended (no current games), WC isn't running.
So the only clickable games with content *right now* are MLB (props). NBA's full page is real but
only had games to show during the finals — which is exactly the one you saw.
