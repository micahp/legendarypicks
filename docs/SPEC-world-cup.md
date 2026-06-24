# SPEC — World Cup (soccer) support for Legendary Picks

Status: PROPOSED (not started). Author handoff for an implementing agent.
Read first: `ORIENTATION.md` → `AGENTS.md` → this file. Do NOT re-grep the repo to "get the lay"; the
touch-points are enumerated here with file paths.

## 0. Why this is not "just another league"
Every existing league (nba/mlb/nhl/nfl) is a two-outcome, no-draw, period-based US sport. The whole stack
quietly assumes that: `GameCard` decides a winner with `home.score > away.score`; `game_result()` picks a
winner with `max(scores)`; `team_strength()` reads win% and point differential with no concept of a draw;
`livePeriod.type` is one of `inning|period|quarter|round|game`. **Soccer breaks all four assumptions.**
Soccer adds: draws (group stage), halves + stoppage time + extra time + penalty shootouts (knockout),
group-table standings (not win%), three-way match markets, and a fundamentally different box score
(possession, xG, cards) and detail surface (starting XI + formation). Treat this as a new *sport class*,
not a new league key. Mirror how tennis/UFC got dedicated branches in `espn_client.games()` rather than
being forced into the team-sport shape.

Scope of this spec: **men's FIFA World Cup** (ESPN league slug `soccer/fifa.world`). Build the soccer plumbing
generically enough that domestic leagues (EPL `soccer/eng.1`, UCL `soccer/uefa.champions`) are a config add
later, but only wire and test the World Cup now. Women's World Cup is `soccer/fifa.wwc` (future).

---

## 1. ESPN feasibility — what we can and cannot get (verify payloads before coding)
All four are the **same hidden ESPN API** already used in `backend/espn_client.py`. The implementing agent
MUST curl each once and pin the real field names before writing parsers (ESPN drifts; do not trust this doc's
field names blindly — AGENTS.md "verify, don't trust").

| Need | Endpoint | Notes |
|---|---|---|
| Scoreboard / live state | `…/soccer/fifa.world/scoreboard?dates=YYYYMMDD` | `events[].competitions[0].status.type` carries `state` (pre/in/post), `name` (e.g. `STATUS_HALFTIME`, `STATUS_FULL_TIME`, `STATUS_SHOOTOUT`), `shortDetail` (e.g. `45'`, `HT`, `90'+3'`, `FT`, `FT (Pens)`), `period`, `displayClock` (e.g. `67'`). Group is in `competitions[0].notes[]` or `season.type`/`groups`. |
| Group standings (tables) | `apis/v2/sports/soccer/fifa.world/standings` | `children[]` = groups A–H; `standings.entries[].stats` include `gamesPlayed, wins, ties, losses, pointsFor (GF), pointsAgainst (GA), pointDifferential (GD), points, rank`. **`ties` = draws — new concept.** |
| Box score / team stats | `…/soccer/fifa.world/summary?event={id}` → `boxscore.teams[].statistics` | possession %, shots, shots on target, fouls, corners, offsides, yellow/red cards, saves, passes, pass %, sometimes xG. Field key names vary; map by `name`/`label`. |
| **Live play-by-play** | same `summary` → `commentary[]` and `keyEvents[]` | **YES, play-by-play is available.** `keyEvents[]` = goals/cards/subs/VAR with `clock.displayValue` (minute) + `athletesInvolved`. `commentary[]` = full minute-by-minute text. Same `summary?event=` pattern `boxscore()`/`game_result()` already call, so it lives on the request path the same way. It updates on ESPN's ~30–60s cadence (good enough for the 30s scoreboard poll in `scores.tsx`). |
| Lineups | same `summary` → `rosters[]` | formation, `roster[]` starters + subs with `jersey`, `position`, `athlete`. |

Answer to "can we even get live play-by-play from ESPN": **yes** — `summary.commentary` + `summary.keyEvents`.
No new data source needed; it's the endpoint we already use for box scores.

---

## 2. Game stages on the scoreboard — the exact mapping (be precise here)
This is the part to get right. A soccer match moves through stages the current `GameCard`/`livePeriod` cannot
express. Define a soccer-specific period model and a status→label table.

### 2a. Status → UI state + badge (drives `GameCard`)
The UI `status` enum is `SCHEDULED | LIVE | FINAL` (`services/sports.ts:statusFromState`). Soccer maps onto it
but needs a richer **stage label** shown on the card (like MLB's "Top 5th" via `livePeriod.display`).

| ESPN `status.type.name` | ESPN `state` | UI status | Card stage label (`livePeriod.display`) |
|---|---|---|---|
| `STATUS_SCHEDULED` | pre | SCHEDULED | kickoff time |
| `STATUS_FIRST_HALF` | in | LIVE | live minute, e.g. `23'` (from `displayClock`) |
| `STATUS_HALFTIME` | in | LIVE | `HT` |
| `STATUS_SECOND_HALF` | in | LIVE | `67'` (incl. stoppage e.g. `90'+3'`) |
| `STATUS_END_REGULATION` / went to ET | in | LIVE | `FT` then `ET` |
| `STATUS_FIRST_EXTRA` / `STATUS_SECOND_EXTRA` | in | LIVE | `ET 105'` |
| `STATUS_SHOOTOUT` | in | LIVE | `PENS` (+ running shootout tally if available) |
| `STATUS_FULL_TIME` / `STATUS_FINAL` | post | FINAL | `FT`, or `FT (AET)` if decided in ET, or `FT (Pens X–Y)` if shootout |
| `STATUS_ABANDONED` / `STATUS_POSTPONED` / `STATUS_CANCELED` | (varies) | SCHEDULED (greyed) | `ABANDONED` / `PPD` (do not show a winner) |

### 2b. New period model
Extend `LivePeriod.type` (`services/sports.ts`) with `'half'`. Add `livePeriod.stage: 'regular'|'et'|'pens'`
and pass `displayClock` straight through as `display` (ESPN already formats stoppage `90'+3'`). Do not invent a
clock; trust ESPN's `displayClock`.

### 2c. Result / winner — the draw + penalty problem (do NOT use `max(scores)`)
- Group stage: a match can end level → **draw, no winner**. `GameCard` must render both teams un-dimmed and show
  the score (e.g. `1–1`), not pick a "winner". Add `isDraw` to the normalized game.
- Knockout: if level after 90/120, decided by penalties. The goals score can be equal (`1–1`) yet there IS a
  winner. The winner MUST come from ESPN's `competitor.winner === true` flag (and/or shootout score), never from
  comparing `score`. `game_result()` and `GameCard` both currently derive the winner from the numeric score —
  both must switch to the explicit ESPN `winner` flag for soccer.

### 2d. Scoreboard grouping by stage (the "different stages of the game" the product should show)
World Cup is two phases with different scoreboard semantics:
- **Group stage:** games carry a group ("Group A"…"Group H"). On `pages/scores.tsx` the existing `subtitle`
  grouping (it already renders `g.subtitle` as an `<h3>` sub-header) should be set to the group name so the
  board reads "Group A / Group B / …". Also surface the **group table** (see §4 Standings).
- **Knockout:** subtitle = round ("Round of 16", "Quarterfinal", "Semifinal", "Third Place", "Final"). Order
  rounds correctly (see `LEAGUE_PRIORITY` analog — add a knockout-round ordering for sub-groups).
- Set `game.subtitle` from ESPN (`competitions[0].notes[].headline` or the season/group metadata) in the
  soccer branch of `espn_client.games()`.

---

## 3. Backend changes (`backend/`)

### 3a. `espn_client.py`
1. **Register the league.** Add to `LEAGUES`: `"wc": ("soccer/fifa.world", 2)` (2 = regulation halves). Keep the
   key short and stable; the whole stack keys off it.
2. **Soccer branch in `games()`.** Add an `is_soccer = league == "wc"` branch (mirror the tennis/ufc branches).
   For each event/competition normalize to the existing game dict PLUS soccer fields:
   `{game_id, date, state, status, period, clock, status_detail, home, away, subtitle (group/round),
     is_draw (bool), winner_abbrev (None|abbr from competitor.winner flag), stage ('regular'|'et'|'pens'),
     pens (e.g. "4-3"|None)}`. `home/away` keep `{abbrev, name, nickname, score}` where `abbrev` = the country
     3-letter code; `name` = country/team display name. Do not 0–0 a pre-match game (existing rule).
3. **`team_strength()` is win%-shaped — add `group_standings()` for soccer.** Do not bend the existing function.
   New `def group_standings(league)` returning per-group tables:
   `[{group: "Group A", rows: [{rank, abbrev, name, played, wins, draws, losses, gf, ga, gd, points}]}]`
   from the `/standings` `children[]`. (Draws come from the `ties` stat.) Knockout has no table — return `[]`
   or only the groups that exist.
4. **`game_result()` soccer-safe.** For `league == "wc"`: winner = the competitor with `winner === true`
   (penalty/AET aware); `is_draw = (state=='post' and no competitor.winner and scores equal)`; never `max()`.
5. **`boxscore()`** already hits `summary` — fine. Add helpers `lineups(league, game_id)` (from `rosters[]`) and
   `match_events(league, game_id)` (from `keyEvents[]` + `commentary[]`) for the detail page / PBP.

### 3b. `sports_service.py`
1. `/api/{league}/games` already delegates to `espn.games`; soccer flows through once `LEAGUES` has `wc`. The
   post-state DB final-score reconcile loop (`_final_score_from_db`) is fine but make sure it does not clobber a
   penalty result — gate the override on `not is_draw and pens is None`, else trust ESPN.
2. **New `/api/{league}/standings`** → `espn.group_standings(league)` for `wc` (other leagues can 404 or return
   `team_strength`). Cache 15 min (standings move slowly).
3. **`/api/{league}/game/{game_id}/detail`** — extend the soccer path to include `team_stats` (soccer stat keys),
   `match_events` (for PBP), `lineups`, and `final_score` with `pens`/`is_draw`/`winner`. Keep the DB-first
   pattern (`_read_game_detail_from_db`) but soccer can fall back to live `summary` until ingest exists.
4. **`/api/predictions` + `_evaluate`** — soccer is **3-way**. `predicted_winner` must accept `DRAW` (or the team
   abbr). `_evaluate` must grade a `DRAW` pick correct when `game_result().is_draw`, and grade a team pick by the
   penalty/AET-aware winner. Today `_evaluate` leans on `game_result().winner` which is `None` on a draw — that
   would wrongly mark every group-stage pick ungraded. Fix it.
5. **`espn.LEAGUES` gate** in `submit_prediction` already validates membership — `wc` passes once registered.
6. **Player search / props** — soccer players must land in the `players` table (league `wc`) for
   `/api/players/search` to surface them (Props tabs depend on it). Roster ingest via `espn.roster("wc", team)`
   per qualified nation. (Ingest scheduling is out of scope here; document the command.)

### 3c. DB / data model
- `prop_games`, `players`, `player_stats` already carry a `league` column — use `wc`. No schema change required
  for the scoreboard/detail MVP. Props/stats ingest for soccer (goals, shots, cards markets; player season
  stats) is a **follow-up** (note it, don't build it here unless asked).
- Group standings can be served live (no table) for MVP; a `group_standings_snap` table is a later optimization.

---

## 4. Frontend changes — every tab/surface, and where the new tab goes

### 4a. Top nav (`components/Layout.tsx`)
Current tabs: **Scores · Predict · Props · Stats**. Decision: **add one top-nav tab: "Standings"** →
`/standings`, because group tables have no natural home today and they're the signature World Cup surface.
(Alternative considered: fold into `Stats` — rejected; Stats is per-team strength, Standings is grouped tables,
and burying the group tables hurts the World Cup story.) New tab goes **between Scores and Predict** (it's a
viewing surface, like Scores). Gate its content to tournaments that have group tables; show World Cup groups now.

### 4b. Scoreboard (`pages/scores.tsx`)
- `LEAGUES` array (line ~9) and `LEAGUE_PRIORITY` (line ~8): add `'World Cup'`. Map the label to the league key
  exactly like the existing `'Call of Duty' → 'cod'` shim (`'World Cup' → 'wc'`) in BOTH the filter `onChange`
  path and `getAllGamesByDate`.
- `services/sports.ts:getAllGamesByDate` league list (line ~181) `['nba','mlb','nhl','nfl','atp','wta','cod','ufc']`
  → add `'wc'`.
- Sub-grouping: `subtitle` already drives the `<h3>` sub-headers — group games render as "Group A…", knockout as
  the round. Add a knockout-round sort order so Round of 16 → Final reads in order.

### 4c. Game card (`components/Scores/GameCard.tsx`)
- Add `isSoccer = g.league === 'WC'`. Country name display (not "ABBR Nickname"); add `isTeamSport` carve-out.
- Winner dimming: for soccer use the explicit `winner` flag, and for draws dim NEITHER side and show both scores.
- Stage label: render `livePeriod.display` (e.g. `67'`, `HT`, `ET 105'`, `PENS`) and the FINAL badge variant
  `FT (Pens 4–3)` / `FT (AET)` when present.
- Make the card clickable for soccer (`hasDetail` currently only NBA/NHL) → add `'WC'` so it routes to the detail
  page.

### 4d. Type/normalize layer (`services/sports.ts`)
- Extend `LivePeriod.type` with `'half'`; add `stage` + `pens` + `isDraw` + `winnerAbbrev` to `Game`.
- `normalizeLivePeriod`: add `lg === 'wc' → type 'half'`, pass `displayClock`/stage through as `display`.
- `normalizeGame`: carry `is_draw`, `winner`, `pens`, `subtitle (group/round)`.

### 4e. Game detail (`pages/game/[league]/[gameId].tsx`) — the detailed view
This is the second "be very particular" area. Current detail tabs: **Box Score · Play-by-Play · Game Info**.
For soccer:
- **Add a 4th detail tab: "Lineups"** (the `Tab` union + `TabBar` array). Place it **after Box Score**
  (`Box Score · Lineups · Play-by-Play · Game Info`) — lineups are the most-wanted soccer detail. Render formation
  + starting XI + subs per side (from `lineups`).
- **Box Score (soccer):** add a `SoccerBoxScore` component (mirror `NBABoxScore`/`NHLBoxScore`, two-column
  home/away) with rows: Possession %, Shots, Shots on Target, Corners, Fouls, Offsides, Yellow Cards, Red Cards,
  Saves, Passes, Pass %, (xG if present). Wire it in the `tab === 'boxscore'` switch (`isNBA?…:isNHL?…` → add
  `isSoccer`).
- **Score strip (`ScoreStrip`):** handle draw (don't grey either team) and show `FT (AET)` / `FT (Pens 4–3)` in
  place of "FINAL".
- **Play-by-Play:** the existing component groups by `period` and filters "scoring". For soccer, group by half
  (1st/2nd/ET/Pens) using the soccer `match_events`/`commentary`; the "scoring" filter becomes
  goals/cards/subs/VAR. `ScoringPlay.period_disp` should read "1st Half"/"2nd Half"/"Extra Time"/"Penalties".
- **Game Info:** "Season Records" (win/loss) is meaningless for World Cup → for soccer show **group standing**
  (the team's row + position) and referee/venue/attendance. Replace the records block when `isSoccer`.

### 4f. Predict (`pages/predict.tsx`)
- Add World Cup to its league selector. **Critical:** the pick UI is binary (home/away winner). Soccer needs a
  **third option: Draw** for group-stage matches (knockout has no draw — only show Draw for group games, or always
  allow it and let `_evaluate` grade). Submit `predicted_winner = 'DRAW'` or the abbr.

### 4g. Props (`pages/props.tsx`) — the 5-tab prop product
Tabs are `lines · slate · performance · matchups · model`; league pills are `['All','mlb','nba','nfl','nhl']`.
- Add `'wc'` to the `LEAGUES` pill list so all five tabs can filter to World Cup.
- **Searching:** `PlayerSearch` hits `/api/players/search?q=` — soccer players must be in the `players` table
  (see §3c) or search returns nothing for them. This is the main search impact across the app.
- **Performance tab:** it has per-league advanced-stat blocks (mlb/nfl/nba/nhl) and a "coming soon" fallback for
  others. Soccer will hit the fallback initially — that's acceptable for MVP; add a soccer block (goals, shots,
  shots on target, xG, big chances, cards) as a follow-up once soccer `player_stats` ingest exists.
- **Lines/Slate:** league-filtered by the same `league` param — works once soccer props are ingested; until then
  WC shows "No props found" (acceptable, but the pill should still appear).

### 4h. Stats (`pages/stats.tsx`) and the new Standings page
- `stats.tsx` shows team strength (win%/diff/streak) — soccer has none of those. Either hide WC from `stats.tsx`
  or branch it to call `/api/{league}/standings`. Recommended: leave `stats.tsx` to the four US leagues and put
  World Cup tables on the new **`pages/standings.tsx`** (group tables: rank, P, W, D, L, GF, GA, GD, Pts), reading
  `/api/wc/standings`. This is the "what other tab it needs to add and where" answer: a top-nav **Standings** tab
  + a `pages/standings.tsx`, plus a **Lineups** tab inside the game detail page.

### 4i. Search surfaces — full list (the "various searching" impact)
1. `/api/players/search` (Props Lines + Performance `PlayerSearch`) — needs soccer players ingested.
2. Scoreboard league filter dropdown — add World Cup option + key shim.
3. Slate tab league filter — works via `league` param once props exist.
4. Deep-link `?league=` on `scores.tsx` — the `LEAGUES.includes(l)` guard must include the new label.

---

## 5. Acceptance criteria (Definition of Done for the implementing agent)
1. `GET /api/wc/games?date=YYYYMMDD` returns normalized soccer games with correct `state`, stage label data,
   `is_draw`, penalty/AET-aware `winner`, and group/round `subtitle`. Verified against a real ESPN payload.
2. Scoreboard shows World Cup (filter + All), grouped by group/round, with correct live stage labels
   (`HT`, `67'`, `ET`, `PENS`), draws un-dimmed, and `FT (Pens X–Y)`/`FT (AET)` on finals.
3. Game detail renders soccer Box Score, **Lineups tab**, half-grouped Play-by-Play (from ESPN
   `keyEvents`/`commentary`), and a soccer Game Info (group standing, referee, venue).
4. New **Standings** top-nav tab + `/standings` renders the eight group tables (P/W/D/L/GF/GA/GD/Pts).
5. Predict supports a Draw pick for group games and `_evaluate` grades draws and penalty-decided results
   correctly (no false "ungraded").
6. Props shows a World Cup pill across all five tabs; player search returns soccer players (once ingested).
7. `next build` compiles; every changed page RENDERS DATA (not just HTTP 200) — AGENTS.md. No host hardcoded in
   `services/sports.ts` (relative `/api`). Update `ORIENTATION.md` if structure changed.

---

## 6. Gherkin examples (seed set — extend these)
```gherkin
Feature: World Cup scoreboard stages

  Background:
    Given the league filter includes "World Cup"
    And World Cup games exist for the selected date

  Scenario: Group-stage match in the first half
    Given a World Cup group match is in its first half at the 23rd minute
    When I view the scoreboard
    Then the match card shows a "LIVE" badge
    And the stage label reads "23'"
    And the card is grouped under "Group A"

  Scenario: Halftime
    Given a World Cup match is at halftime
    When I view the scoreboard
    Then the stage label reads "HT"

  Scenario: Second-half stoppage time
    Given a World Cup match is in the 90th minute plus 3 of stoppage
    When I view the scoreboard
    Then the stage label reads "90'+3'"

  Scenario: Group-stage draw is not given a winner
    Given a World Cup group match has ended 1-1
    When I view the scoreboard
    Then neither team is dimmed as a loser
    And both teams show a score of 1

  Scenario: Knockout decided by penalties
    Given a World Cup Round of 16 match ended 1-1 after extra time
    And the home team won the shootout 4-3
    When I view the scoreboard
    Then the home team is shown as the winner
    And the status reads "FT (Pens 4-3)"
    And the away team is dimmed as the loser

  Scenario: Knockout grouping order
    Given World Cup knockout matches exist for the date
    When I view the scoreboard
    Then "Round of 16" is listed before "Quarterfinal"

Feature: World Cup game detail

  Scenario: Lineups tab exists for soccer only
    Given I open a World Cup game detail page
    Then I see tabs "Box Score", "Lineups", "Play-by-Play", "Game Info"
    But an NBA game detail page does not show a "Lineups" tab

  Scenario: Soccer box score metrics
    Given I open a finished World Cup match detail
    When I view the Box Score tab
    Then I see rows for "Possession %", "Shots", "Shots on Target", "Corners", "Yellow Cards"

  Scenario: Live play-by-play from ESPN
    Given a World Cup match has a goal recorded at the 67th minute
    When I view the Play-by-Play tab
    Then I see a "67'" event describing the goal grouped under "2nd Half"

Feature: World Cup standings

  Scenario: Group tables render
    When I open the Standings tab
    Then I see eight group tables
    And each row shows P, W, D, L, GF, GA, GD, and Pts

Feature: World Cup predictions

  Scenario: Draw is a valid pick for group games
    Given a scheduled World Cup group match
    When I open Predict for that match
    Then I can pick the home team, the away team, or a Draw

  Scenario: A correct draw pick grades as correct
    Given I predicted a Draw for a group match
    And the match ended 0-0
    When predictions are graded
    Then my pick is marked correct

Feature: Search includes soccer players
  Scenario: Player search finds a World Cup player
    Given soccer rosters have been ingested
    When I search "Mbappe" in the Props player search
    Then a result with league "WC" appears
```
Extend with: abandoned/postponed matches, VAR-overturned goals, own goals in PBP, red-card display on the card,
group tiebreaker ordering, deep-link `?league=World%20Cup`, and timezone correctness of kickoff times.

---

## 7. Phasing / out of scope
- **Phase 1 (this spec):** scoreboard + stages, detail (box/lineups/PBP/info), standings tab, predict draws.
  All can run off live ESPN `summary` (no new ingest).
- **Phase 2 (follow-up, separate spec):** soccer props ingest (anytime scorer, shots, cards markets), soccer
  `player_stats` for the Performance tab, group-standings snapshot table, settlement pipeline coverage for soccer.
- Do not build Phase 2 here unless asked. Keep the World Cup MVP read-only off ESPN, mirroring how the other
  leagues' live data already flows.
```
