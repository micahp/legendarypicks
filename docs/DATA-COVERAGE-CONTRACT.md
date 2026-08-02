# Data coverage contract

**Status:** adopted 2026-08-02, revised same day against NCAAF / MLS / EPL.
Read this before adding a league, turning on a season, or building any surface that shows
what a player did or did not do.

Companion to `.claude/skills/published-first/SKILL.md` §6 (how to get the publisher's
expected total) and `.claude/skills/honest-data-ui/SKILL.md` §5 (the accent marks
absence). This doc is the part in between: **what our own data is allowed to claim, and
what has to be true before a season is switched on.**

---

## 1. The problem, stated once

A missing row in `player_game_logs` has two possible causes:

1. **The player did not play.** Information about the player — the most valuable thing on
   the page, and the whole availability thesis.
2. **We did not ingest it.** Information about us, worth nothing to a user.

**Today the UI cannot tell them apart and renders the second as the first.**
`PlayerGameLog.tsx` types a week as `played: boolean`; anything not played draws the amber
absence accent. An un-ingested week becomes a confident, saturated, on-brand claim that a
healthy player missed a game.

Measured 2026-08-02 against `picks.dev.db`:

- **NFL 2024 holds 612 players against 2025's 2,024** — WR/RB/TE/QB and almost nothing
  else, never re-ingested after the all-positions fix.
- **Every NFL 2024 row has a NULL `game_type`.** `routers/nfl_offseason.py` checks that
  the *column exists*, then filters `AND game_type='REG'`. The column exists. The values
  are NULL. Zero rows match, `games_played` returns 0, and every player in the season
  reads **"missed 17"** in amber.

The guard is the bug in miniature: **presence of a column was taken as integrity of its
values.** Nothing raised. Nothing logged. It renders.

---

## 2. The rule

> **Absence renders as a claim about the player only where we can prove we looked.
> Everywhere else it renders as a claim about us.**

Three states, never two:

| state | meaning | treatment |
|---|---|---|
| `played` | we have the row | normal, neutral |
| `missed` | the team played, the player did not, **and the season is verified complete** | the amber absence accent |
| `unknown` | no row, and we cannot prove we should have one | quiet neutral, visibly not a zero and visibly not an accent |

`unknown` is **quieter** than `missed`, not louder. Ink goes to the holes because the holes
are information; our own gaps are not information about the player, and dressing them up as
warnings trains users to discount the accent that carries the product's thesis.

**But the third state is a safety net, not the mechanism.** It stops a partial season from
lying. It does not make a partial season worth shipping. The mechanism is §4.

---

## 3. How ESPN does it

Worth copying in one place and refusing in another. Measured 2026-08-02 from
`site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/<id>/gamelog` — the feed
their own player page renders from.

**Copy this: the season selector is a published whitelist.**

```json
"filters": [{ "name": "season", "value": "2025",
              "options": [{"value":"2025"},{"value":"2024"},{"value":"2023"}] }]
```

Three options for a player drafted in 2023. It matches
`core.api/.../athletes/<id>/statisticslog`, which returns entries for exactly those three
seasons. **ESPN never offers a season it cannot fill.** There is no greyed-out 2022, no
empty state to design, no bug to hit — the season is not in the list. The dropdown is
derived from a manifest of what exists, and everything downstream inherits that.

**Refuse this: their game log is appearances-only.** Puka Nacua's 2025 regular season
renders **16 rows**. The Rams played 17. The missed game is not a row marked DNP — it is
simply absent, and the season totals (129 rec, 1,715 yds) sit under the 16-row table with
no games-played count in the summary. That is exactly the flattering-average problem in
`honest-data-ui` §1, shipped by the market leader. Our log renders one row per week the
team played. **That difference is the product.**

So: ESPN's *gate* is the model. ESPN's *absence handling* is the thing we exist to beat.

---

## 4. The enablement registry

**The unit of work is one `(league, season)` pair, and it is a switch, not a gradient.**
A year of game data for a league lands on a dozen surfaces at once. Turning it on means all
of them are accounted for; until then it is not offered anywhere.

`team_stats_coverage` is the registry. **It already exists — do not build a second one**
(published-first rung 1):

```
team_stats_coverage(
  run_id, league, season, season_start, season_end, status,
  expected_teams, fetched_teams, expected_games, fetched_games,
  paired_games, paired_stat_games, failure_count, completed_at, source
)
```

Populated once, `2026-07-14`, for `nfl 2025` / `nba 2026` / `nhl 2026`, all
`status='complete'`, then never refreshed. No MLB row — which is why
`team_stats_contract.py` special-cases MLB by parsing `substr(game_date,1,4)` instead of
reading the manifest. **Nothing in the frontend reads this table at all.**

**And the row it does hold is false.** Measured 2026-08-02, `backfill_team_parity.py`
writes the summary at `run_league()` like this:

```python
status = "complete" if fetched_teams == expected else "partial"   # teams only
...
fetched_teams, games_written, games_written, games_written, games_written,
0,                                                                # failure_count
```

Four columns — `expected_games`, `fetched_games`, `paired_games`, `paired_stat_games` —
are the **same variable**, so they can never disagree; `expected_games` is the count of
what landed, not an expectation of what should have. `failure_count` is the **literal
`0`**, written by a function that had just inserted four failure rows into
`team_stats_ingestion_failures` during that same run. And `status` is a claim about
**teams**: 30 of 30 appeared, so `complete`, while four games were lost.

Before this table gates anything, it has to be capable of saying no:

- `expected_games` comes from the publisher (`published_count`), never from the loop.
- `failure_count` is `SELECT COUNT(*) FROM team_stats_ingestion_failures WHERE run_id=?`.
- `status='complete'` requires **every** count to equal its published total *and*
  `failure_count = 0` *and* a reachable oracle.

See §8 for the NBA case that proves each of these three.

Three changes make it the gate:

1. **`reconcile_totals.py` writes it.** It already computes these numbers, and gets
   `expected_games` from ESPN in **one** request where the 2026-07-14 run traversed 32 team
   schedules for the same integer.
2. **Add player-level and integrity columns.** Game coverage is not player coverage — NFL
   2024 has 100% of games and 30% of players: `expected_players`, `fetched_players`,
   `null_key_rows` (rows with a NULL `game_type` / `team` / `game_id` — the integrity check
   the column-presence guard missed).
3. **`status` becomes load-bearing.** `complete` | `partial` | `unverified`. **No row means
   `unverified`, never good.** A season reaches `complete` only when every count equals its
   published total *and* the oracle was actually reachable; `NO-ORACLE` writes
   `unverified`.

**Only `complete` is offered.** The season picker is built from the registry, the way
ESPN's is built from `statisticslog`. `partial` and `unverified` seasons are not listed,
not linked, and never the default. The three states in §2 exist for the window between an
ingest landing and its season being verified, and for the row that goes wrong after
verification — not as a way to ship a half-season.

---

## 5. What one `(league, season)` touches

The surfaces that must be accounted for before flipping a season to `complete`. Anything
league-scoped inherits automatically; the NFL-specific ones only apply to NFL.

**League-scoped API** — every one of these takes `{league}` and will answer for a season it
has no business answering for:

| route | file |
|---|---|
| `/api/{league}/games`, `/schedule-dates`, `/standings`, `/strength`, `/leaders` | `routers/games.py`, `routers/players.py` |
| `/api/momentum/{league}/crosses`, `/board`, `/player/{id}`, `/team/{abbrev}` | `routers/momentum.py` |
| `/api/game/{league}/{game_id}/props`, `/story`, `/edge` | `routers/game_extras.py` |
| `/api/player/{id}`, `/stats`, `/matchups`, `/news` | `routers/players.py` |
| `/api/props/stats`, `/props/player/{id}/history`, `/performance` | `routers/props.py` |

**NFL-specific API:** `/api/nfl/schedule/{season}`, `/schedule-weeks`, `/schedule-week`,
`/api/nfl/mock-draft/pool`, `/api/nfl/draft/player/{id}`, `/api/nfl/draft/player/{id}/game-log`
(`routers/nfl_schedule_api.py`, `routers/nfl_mock_draft.py`, `routers/nfl_offseason.py`).

**Surfaces:**

| surface | what a new season changes |
|---|---|
| `Leagues/PlayerGameLog.tsx` | row states; the `N of M team games` header line |
| `Leagues/PlayerDetailOverlay.tsx` | availability summary — suppressed, not shown low |
| `Leagues/StatsTab.tsx`, `pages/stats.tsx`, `Leagues/StatRankCard.tsx` | season picker + rank denominators |
| `Leagues/StandingsTab.tsx`, `ScheduleTab.tsx`, `NflScheduleTab.tsx` | season bounds |
| `Leagues/NflUsageTrend.tsx` | a trend across an un-ingested week must **break the line**, not interpolate |
| `Leagues/NflDraftRoom.tsx`, `NflOffseasonMovers.tsx`, `NflCampHero.tsx` | `games_played` / `games_missed` read `—`, **never 0** |
| `MockDraft/PoolList.tsx`, `columns.tsx`, `PlayersTab.tsx`, `ResultsScreen.tsx`, `RostersTab.tsx` | pool construction and projected points |
| `Leagues/PredictTab.tsx`, `components/Props/*` | prop history denominators |

**Rules that outlive the specific components:**

- **Never default to a season that is not `complete`.**
- **A rate whose denominator is unverified does not render.** `12 of 17` where the 17 is
  unproven is fake precision with extra steps.
- **State `n` and the source season** wherever a derived average appears (`honest-data-ui`
  §4).
- **The coverage line is part of the surface, not a tooltip.**

---

## 6. Read the league's shape from the publisher

**Do not generalise from the NFL.** Every assumption below held for NFL/NBA/NHL/MLB and
breaks on at least one of NCAAF, MLS and EPL. All figures measured 2026-08-02.

| assumption | breaks on |
|---|---|
| regular season is **type 2** | **EPL/MLS have one type, id `1`.** `soccer/leagues/eng.1/seasons/2025` returns a single type named *"2025-26 English Premier League"*. A hardcoded `types/2` returns nothing. |
| the league's `teams` collection is the scope | **NCAAF 2025 has 807 teams.** FBS is a published *group*: `types/2/groups/80/teams` = 146; FCS `groups/81` = 131. Checking against 807 invents a 660-team gap. |
| a fixed games-per-team constant | **NCAAF: 911 regular-season events over an uneven schedule** — no per-team constant exists. EPL: 380 = 20 × 19 × 2. |
| the team set is stable year to year | **EPL relegation replaces 3 of 20 every season.** Team identity is season-scoped, not league-scoped. |
| the athlete universe is ~20k | **NCAAF 2025: 102,406 athletes.** An `expected_players` gate is meaningless unless scoped to the group we actually ingest. |
| we compute the season's display label | **ESPN publishes it.** `seasons/2025` returns `year: 2025` *and* `displayName: "2025-26 English Premier League"`. |

The single rule that covers all six:

> **`GET seasons/<year>` returns the season's `types[]` with ids, names and date ranges,
> and `displayName`. Read them. Never hardcode a season-type id, a team count, a games
> constant, or a season label.**

This is published-first rung 5 — *a definition is always published, never infer it* — and
`reconcile_totals.py` violated it on the day it was written, with
`REGULAR, POSTSEASON = 2, 3` at module scope. Fixed; the constants now come from the
season document.

**On the season key — corrected 2026-08-02, this doc had it wrong.** There is **no
league-wide convention**. Measured from `types[].startDate/endDate`:

| league | `seasons/2026` covers | keys by |
|---|---|---|
| NBA | `2025-10-21 -> 2026-04-13` | the year it **ends** |
| NHL | `2025-10-07 -> 2026-04-18` | the year it **ends** |
| NFL | `2026-09-09 -> 2027-01-13` | the year it **starts** |
| MLB | `2026-03-25 -> 2026-09-29` | one calendar year |
| EPL | `seasons/2025` = *"2025-26 English Premier League"* | the year it **starts** |

So "use ESPN's start-year key" is not a rule that can be followed — for NBA and NHL it
names the wrong season and every count lands on the wrong year. **The rule is: read
`startDate`/`endDate` from the season document and confirm the key means what you think
before comparing anything to it.** ESPN publishes the human label too, so there is still
no vocabulary to standardise — there is a value to copy. Our own tables disagree
(one NHL season is `20252026` in `player_game_logs`, `2026` in `team_game_results` and
`team_stats_coverage`; MLB's `team_game_results.season` is empty for all 3,305 rows). That
is real and it will silently mis-join, but it is **not a prerequisite for adding a league**
— a new league simply lands on ESPN's key from day one. Sequence it when it blocks
something; do not front-load a migration.

**`game_type` is the one that does block.** It is populated for NFL 2025 and nothing else —
NULL for NFL 2024 and for every MLB, NBA, NHL, UFC and WC row — so any `AND
game_type='REG'` silently returns zero for all of them. Ingest it NOT NULL, from the
season's published `types[]`, for every league. And **never guard on a column existing and
then filter on its values.**

---

## 7. Adding a league

Ordered. Steps 1–3 are cheap and kill most surprises; do them before writing an ingest.

1. **Find the ESPN path and confirm the shape.** `football/leagues/college-football`,
   `soccer/leagues/usa.1`, `soccer/leagues/eng.1`. Then
   `GET seasons/<year>` and read `types[]` and `displayName` — **write the type ids you
   found into the ingest as data, not as an assumption.**
2. **Establish the scope.** Is it the whole league, or a published group?
   (`types/<t>/groups?limit=1` — NCAAF returns 2: FBS 80, FCS 81.) Record the group id;
   every expected-count for that league is scoped to it.
3. **Get the three expected totals** with `?limit=1`: events, teams, athletes. Sanity-check
   them against the competition's real shape before trusting them (911 NCAAF games, 380 EPL
   matches, 146 FBS teams). **If a number surprises you, that is a question about the
   definition, not a defect** — see `published-first` §6.
4. **Ingest** with ESPN's start-year season key, ESPN team codes normalised at the boundary,
   and `game_type` NOT NULL drawn from the published `types[]`.
5. **Add the league to `ESPN_PATH` in `backend/reconcile_totals.py`** with its scope group
   and its type ids, and write its checks.
6. **Run the reconcile and land a `team_stats_coverage` row.** A league with no row is
   `unverified`: not offered, not defaulted, anywhere.
7. **Walk §5.** Every league-scoped route answers for the new league the moment it has
   rows — check each one before the season is marked `complete`, not after.
8. **Screenshot two players**: one with a genuine missed game, one in a season we have not
   fully ingested. **If those two look the same, the work is not done.**

### Known shape notes for the next three

- **NCAAF** — scope to FBS (`groups/80`, 146 teams). 911 regular-season events, uneven
  per-team schedules, 102,406 athletes league-wide. `expected_players` must be
  group-scoped or it is noise. Postseason is bowls, not a bracket.
- **MLS** (`soccer/leagues/usa.1`, 31 seasons published) — one season type. Calendar-year
  season, so the start-year key reads naturally. Draws exist: any win-rate or
  `_valid_result_pair` logic written for NFL ties is not the same thing.
- **EPL** (`soccer/leagues/eng.1`, 26 seasons published) — one season type, id 1.
  380 matches, 20 teams, **3 relegated and 3 promoted each year**, so a team's league
  membership is a season-scoped fact. Season spans two calendar years; ESPN keys it `2025`
  and labels it `"2025-26 English Premier League"` — use both, invent neither.

---

## 8. Open, not decided here

- **The NFL 2024 backfill.** Deferred on purpose: the registry and the third state must
  exist before we fix a season, or we fix this one and learn nothing that protects the
  next.
- ~~**NBA 1,227 vs 1,239.**~~ **MEASURED AND CLOSED 2026-08-02 — see §9.** The play-in
  lead was wrong.
- **MLB's empty `team_game_results.season`** and the special case it forces in
  `team_stats_contract.py`.
- **The NHL/NBA season-key mismatch** in our own tables. Real, currently harmless, not a
  blocker for a new league.

---

## 9. Worked example — the NBA 12-game gap, measured

Kept in full because every wrong turn in it is a mistake this doc exists to prevent, and
because the arithmetic closes to the game. Measured 2026-08-02 against
`picks.dev.db`, ESPN `basketball/leagues/nba/seasons/2026`.

### The lead was wrong

§8 guessed the 12 games were NBA's fifth season type, `Play-In Season` (id 5), leaking
into the regular-season count. It is not. Pulling both collections' event ids — from the
`$ref` URLs, no per-event fetch needed — gives:

```
espn type2 (Regular Season): 1239   type5 (Play-In): 6   type3 (Postseason): 85
play-in ids inside type2: 0         postseason ids inside type2: 0
```

The types are disjoint, and the published date ranges say so out loud: type 2 ends
`2026-04-13`, type 5 runs `2026-04-13 -> 2026-04-18`. **The lead was an inference, and
one request falsified it.** Two more facts fell out of the same document:

- **ESPN's NBA season key is the year the season *ends*.** `seasons/2026` spans
  `2025-10-21 -> 2026-04-13` — the 2025-26 season. Same for NHL (`seasons/2026` =
  `2025-10-07 -> 2026-04-18`); NFL and MLB key by the year the season *starts*. §6's line
  "ESPN already keys by start year" was **wrong**, and it is corrected there. There is no
  league-wide convention: read `types[].startDate/endDate` and match it to your own key.
- Our NBA key (`2026`) therefore already **agrees** with ESPN. The `check_generic()`
  docstring warning that NBA checks compare the wrong season is wrong too. NHL is the one
  that genuinely disagrees, and only between our own tables (`20252026` in
  `player_game_logs`, `2026` in `team_game_results`).

### What the 12 actually are

Diffing 1,239 published ids against our 1,227 `team_game_results` game ids: 12 theirs and
not ours, **0 ours and not theirs**. Fetching just those 12 classifies all of them.

| n | what | verdict |
|---|---|---|
| 4 | `type=ALLSTAR`, 2026-02-15/16 — the 3-team World / Team Stars / Team Stripes round robin plus the final | **definitional.** ESPN files NBA All-Star under type 2; it files the NFL Pro Bowl under type 3, which `published_real_games()` already handles. Same problem, different type id. |
| 4 | `STATUS_POSTPONED` — MIA@CHI 1/9, GSW@MIN 1/24, DEN@MEM 1/25, DAL@MIL 1/26 | **definitional.** A postponed fixture stays in the collection and its makeup is published as a *new event id*, so ESPN's count carries both. |
| 4 | `STATUS_FINAL`, played, absent from our table — DAL@CHI 1/11, GSW@MIN 1/25 (`401857824`, the makeup), DET@DEN 1/28, MIN@DAL 1/29 | **a real gap.** |

So the honest reconciliation is:

```
1239 published = 1230 regular-season fixtures
               +    1 NBA Cup final (played, does not count toward 82)
               +    4 All-Star exhibitions
               +    4 postponed shells superseded by makeups
```

**Only 4 games were ever missing, not 12.** Our own data confirms it independently:
per-team game counts are 82 for 22 teams, 83 for NY and SA (the Cup finalists — correct),
and short for exactly the six teams in those four games — DAL and MIN by two, CHI, DEN,
DET and GS by one. Adding the four brings **every team to exactly 82**.

### Why they were missing — and why nothing said so

Not a source problem. ESPN's team-schedule feed publishes all four today with
`state=post`, `completed=true` and both scores — they pass every filter in
`enumerate_games()`. The rows were never written:

```
run_id                        game_id    reason
nba-parity-20260714T212239Z   401810401  write: cannot start a transaction within a transaction
nba-parity-20260714T212239Z   401810532  write: cannot start a transaction within a transaction
nba-parity-20260714T212239Z   401810523  write: cannot start a transaction within a transaction
nba-parity-20260714T212239Z   401857824  write: cannot start a transaction within a transaction
nhl-parity-20260714T212239Z   401803191  write: cannot start a transaction within a transaction
```

`run_league()` issues `con.execute("BEGIN")` on a connection in sqlite3's default implicit
transaction mode; when a prior statement has already opened one, `BEGIN` raises and the
game is skipped. Sporadic — 4 of 1,231 — which is why it looked like nothing. (The NHL row
is the same bug, and explains NHL's 1,311 vs 1,312.)

**The failure was recorded, with an exact reason, and the run still reported
`status=complete, failure_count=0`.** That is §4's defect, demonstrated: the coverage row
is not a check, it is a restatement.

Three lessons, in the order they bite:

1. **A lead is an inference.** "Play-in must be it" was plausible, cheap to test, and
   false. Test it before writing it into a plan.
2. **A gap is usually several things.** 12 = 4 + 4 + 4, three different causes, only one
   of them a defect. Reconciling to the game is what separates them; stopping at the
   headline number would have produced a fix for a problem we did not have.
3. **The run knew.** No inference was needed at any point — the reason string was sitting
   in `team_stats_ingestion_failures` for nineteen days, next to a row claiming zero
   failures. Read what the process already wrote before deriving anything.

### Fix, in order

1. `backfill_team_parity.py` — remove the explicit `BEGIN`/`ROLLBACK` (or open the
   connection with `isolation_level=None` and keep them), so a write cannot be lost to
   transaction state.
2. Make the coverage summary honest per §4, then re-run NBA and NHL and confirm all
   30 teams land on 82 and the NHL pair agrees.
3. Teach `published_real_games()` that the exhibition type id is per-league — NBA files
   All-Star under type 2, NFL under type 3 — and read it from the event's
   `competitions[].type.abbreviation`, which is where the answer already is.
