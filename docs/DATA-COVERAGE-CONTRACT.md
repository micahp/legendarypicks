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

> **RESOLVED for NHL, 2026-08-02 — and this is what "when it blocks something" looked
> like.** It blocked within hours: `reconcile_totals` asked
> `WHERE league='nhl' AND season=2026`, got **0** over a season whose 1,312 games were
> all present, and NHL sat at `partial` — unofferable — on a misspelled question. The
> output read `ours=0 published=1312`, i.e. *missing data*, which is the wrong
> diagnosis and the expensive one: acting on it means re-running a 48,000-row ingest to
> fix a WHERE clause.
>
> Fixed at the boundary, not in queries: **`backend/season_keys.py`**, called by both
> nhle ingests, plus a one-shot migration of 49,737 historical rows. **Normalise where
> the foreign value is read — a query that translates keys has to be remembered at every
> call site; a boundary has to be remembered once.**
>
> Two things to carry forward:
> 1. **Migrate a league entire, or not at all.** `league_stats.py` resolves the live
>    season with `MAX(season)`. Translating only `20252026 -> 2026` leaves `20242025`
>    as the maximum — a two-year-old season served as current, from a migration that
>    reported success.
> 2. **`normalize_season()` refuses rather than guesses.** There is no general rule to
>    apply (see the table above), so an unmeasured `(source, league)` raises. Passing an
>    untranslated value through is what put two vocabularies in one database.
>
> `MLB`'s empty `team_game_results.season` (all 3,305 rows) is **still open.**

### Provenance — the thing that made the split invisible

The season-key bug is usually filed as a vocabulary mismatch. It is more precisely a
**provenance** bug. `team_game_results` is ESPN; `player_game_logs` is nhle.com; the two
publishers key seasons differently; and **nothing anywhere said so**. Every surface
treated the two tables as one corpus because nothing recorded that they were not.

Note what `team_stats_coverage.source` contained while this was going on:
`reconcile_totals+espn_core_api` — the provenance of the **verdict**, not of the data
the verdict is about. A column that looks like an answer and answers a different
question is worse than an empty one.

Measured 2026-08-02, `backend/provenance.py`:

| league | publishers |
|---|---|
| NFL | `espn_site_api`, `nflverse`, `nflverse_regular_season`, `nflverse_weekly`, `nflverse_snap_counts` |
| NBA | `espn`, `espn_site_api`, `hoopR` |
| MLB | `mlb_statsapi`, `statcast`, `statcast_pitcher` |
| NHL | `espn_site_api`, `nhle.com` |

**Every one of those is a season-key, team-code and game-id vocabulary that has to be
translated at its own boundary, and all of them are reconciled against ESPN's totals.**
NHL is not a special case; it is the one that happened to get caught.

Three rules, now enforced:

1. **Every season-keyed table records `source`.** `team_game_results` did not until
   today. Gate: `COV-source`, **red on purpose** until MLB's 3,305 rows and NFL's 1,114
   are attributed.
2. **A table that cannot say where its rows came from reports `unrecorded`, never a
   guess.** `stamp_team_result_source.py` attributes historical rows *only* from a
   recorded `run_id`; rows without one stay NULL deliberately.
3. **`derived` is not a publisher.** `player_stats` holds 580 NBA and 841 NHL rows
   sourced `derived` — values we computed. Legitimate, and never independent
   corroboration of themselves. Anything reconciling our numbers against an oracle must
   exclude them or it is grading its own work.

The readout prints at the end of every `backfill_team_parity` run — the one moment
someone is definitely looking — and rides on `/api/coverage` as `publishers`.

**`game_type` is the one that does block.** It was populated for NFL 2025 and nothing else —
NULL for NFL 2024 and for every MLB, NBA, NHL, UFC and WC row — so any `AND
game_type='REG'` silently returned zero for all of them. Ingest it NOT NULL, from the
publisher's own phase field, for every league. And **never guard on a column existing and
then filter on its values.**

### The game-type boundary (2026-08-02, NHL)

`backend/game_types.py` is the third boundary module, after `team_codes.normalize()` and
`season_keys.normalize_season()`, and it exists for the third instance of one failure: a
foreign vocabulary written into a shared column without translation. Ours is
`PRE` | `REG` | `POST`, the vocabulary the nflverse NFL ingest already put there.

Two rules it enforces, both of which cost something to give up:

1. **A NULL game type is not a game type.** `normalize_game_type` raises. The plausible
   fallback — treat an unrecognised type as `REG`, since most games are regular-season
   games — would file preseason exhibitions into the denominator of every per-game rate
   we serve, and it would do it silently.
2. **No shared default across publishers.** NHL's `1/2/3` and ESPN's `1/2/3/4` agree by
   coincidence, not by standard. Each `(source, league)` entry is measured on its own.

**How the NHL mapping was measured, since nhle.com publishes no enum.** The game-log
envelope carries a bare `gameTypeId` integer and nothing anywhere names 1, 2 and 3. But
the NHL does publish its phase calendar, at
`api.nhle.com/stats/rest/en/season?cayenneExp=id=20252026`:

| field | 2025-26 |
|---|---|
| `preseasonStartdate` | 2025-09-20 |
| `startDate` | 2025-10-07 |
| `regularSeasonEndDate` | 2026-04-17 |
| `endDate` | 2026-06-15 |
| `totalRegularSeasonGames` | **1312** |
| `totalPlayoffGames` | **82** |

Type 2's games run 2025-10-07..2026-04-16, inside the regular-season window; type 3's run
past `regularSeasonEndDate` toward `endDate`. `verify_nhl_phase()` is that comparison kept
runnable and printed at the end of every ingest, **not** written down here and trusted — a
measurement recorded only in a document stops being a measurement the first time the
publisher changes. That document is also the published answer to "how many regular-season
games are there", which is otherwise exactly the integer that gets copied back off our own
ingest and then used to check that same ingest.

**The stamp is read back, never assumed.** `ingest_nhl_logs.py` requests
`/game-log/{season}/{gameType}` and could have stamped the column from its own path
segment. That is the ingest describing its *request*, not its data — the same mistake as
`team_stats_coverage.source` recording the provenance of the verdict instead of the
provenance of the rows. It reads `gameTypeId` off the envelope, so a publisher that ever
answers a different phase than the one asked for becomes visible instead of mislabelled.

**Gate: `COV-gametype`**, written red before the code. No league-season judged in
`team_stats_coverage` may hold a NULL `game_type`, and nhl 2026 must hold 1312 distinct
`REG` games — the publisher's integer, the same one `COV-nhl` asserts. The 48,017
player-game rows are deliberately **not** asserted: nobody publishes that figure, so
copying it in would be the ingest grading its own output. It stays **red on purpose for
nba 2026** until that ingest stamps the column too. Do not scope it to nhl to make it
green.

**Still open.** NFL 2024's 5,597 NULL rows are not covered by this gate, because NFL 2024
has no `team_stats_coverage` row at all — an unjudged season is invisible to a gate that
iterates judged ones. That is the `unverified` state doing its job, and it is also a
reminder that this gate's reach is exactly the set of seasons we have bothered to judge.

### What the green column was hiding: a phase nobody asked for

Stamping every NHL row `REG` made `COV-gametype` green over a column with exactly one
value in it, and **a uniformly-`REG` column is indistinguishable from a complete one.**
`ingest_nhl_logs.py` requests `/game-log/{season}/{gameType}` and had only ever passed
`2`, so for a season that ended 2026-06-15 we held **none of the 82 playoff games**. No
count looked wrong, because nothing counted the phase we never asked for. The gate now
asserts `POST = 82` — `totalPlayoffGames` from the NHL's own season document.

Three consumers had to learn the phase *before* the data landed, and each of them would
have **misreported** the postseason rather than missed it:

- **`COV-nhl`** compared `team_game_results` — regular season, and no `game_type` column
  at all — against an unphased `player_game_logs` count. Correct only while one phase
  existed; playoff rows would have made it report a season that just got more complete as
  one that broke.
- **`reconcile_totals.check_generic`** is named "regular-season games in
  `player_game_logs`" and compared against the regular-season type's published count while
  counting every row. Where no row carries a phase it now counts everything and **labels
  the answer `PHASE-BLIND`** — not the column-presence mistake, because it asks what the
  *values* hold and says so when they hold nothing.
- **`routers/players.py`** counted a postseason only for NFL, so an NHL player who played
  22 playoff games rendered as having played none — absence as a claim about the player,
  in a season where we can prove we looked. Two things stay NFL-only there and both are
  load-bearing: the legacy fallback reads `game_no` as a *week number* (NHL's `game_no` is
  a game id, so `>= 19` is true of every NHL row ever written), and the `nfl_schedule`
  venue lookup matches on bare team codes — **CHI, DAL and LA name a team in both
  leagues.**

And one number that had been wrong the whole time without being reachable:
`regular_season_games = len(logs)` where `logs` is `LIMIT 25`. NFL plays 17, so the page
size was always larger than the season and the two agreed by luck. Offering an 82-game
league put "2026 · 25 games" on the page of a player who missed nothing. **A page size is
not a measurement** — and it had the right shape, the right magnitude and the right
column, which is the hardest kind of wrong to see.

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

### 7b. The five defect shapes — run this per league (added 2026-08-05)

Steps 1–8 answer *"are the rows there?"*. This answers *"is what's on them true?"*, which
is a different question and was never asked until 2026-08-04. Asking it that night turned
up roughly ten defects across two leagues — and every single one was an instance of one of
**five shapes**. There is no sixth yet. Treat this as a checklist, not a reading: run each
one, write the number down, and a league is not `complete` until all five have an answer.

They matter because **not one of them raises.** Each produces rows of the right shape and
magnitude, in the right column, that nobody spots by looking.

| # | shape | what it looks like | how to measure it |
|---|---|---|---|
| 1 | **An id names the wrong person** | every row has an id; some point at someone else | `audit_league_stats.py` check **`G/published-identity`** |
| 2 | **Two publishers' vocabularies in one column** | `WHERE position='P'` returns only retired players | check **`C/vocabulary[...]`** |
| 3 | **Two rows for one person** | stats on one row, game logs on the other | check **`F/identity-crosswalk`** |
| 4 | **A display copy diverged from its source** | a denormalised name/team drifts from the spine | join the copy back to `players` and count `<>` |
| 5 | **A value is in the logs but not the season table** | "we have no touchdown data" — we do | `published-first` §2b: surfacing vs acquisition gap |

Measured instances, so the sizes are not hypothetical:

1. **223 MLB rows** carried another player's `mlbam_id` — `id=26551 'Eiberson Castellano'`
   against `mlbam_id=703607`, which MLB publishes as Henry Bolte. Cause: Statcast's
   `player_name` is the **pitcher's** name on every pitch row, and the pre-`b03b9c9` batter
   fallback took it while `player_id` came correctly from `batter_id`. NFL (4/24344) and
   NHL (11/840) show only nickname and legal-name variants — `Kenny`/`Kenneth Gainwell` —
   which are the same human. **A red G is not automatically corruption; read the pairs.**
2. **MLB `position`** held ESPN's `SP`/`RP` on active rows and MLB's `P` on the rest, so
   neither query could ever return both. **NFL has the same defect today** (`FB` under `RB`).
   Fix is one level from one publisher per column — see `DATA-SPINE.md`.
3. **MLB 317 duplicate `mlbam_id` groups; NBA 269 athletes** split across two rows via
   `nba_id`/`espn_id`, their stats and their game logs on different people.
4. **242 MLB `player_stats` rows** disagreed with `players.name` after the dedupe repointed
   them but kept the duplicate's spelling. The leaders endpoint's raw-string guard **503'd in
   production**. Neither table was the authority — the spine held `Heriberto Hernandez`, the
   stats row held the published `Heriberto Hernández`. Write both from the publisher.
5. NFL `rush_td`/`rec_td` read "no such column" while already sitting in
   `player_game_logs`; MLB `pa`/`hits`/`rbi` likewise.

**Order matters, and it is not the order above.** Shape 1 before shape 3, always: a dedupe
"merges rows that share an id (= provably the same person)", and if shape 1 is unfixed that
sentence is false. On 2026-08-04, 124 of 317 MLB groups were two *different* people, and the
merge would have repointed 408,610 prop rows and 26,491 game logs onto the wrong players
before deleting the originals. A `player_stats` UNIQUE constraint stopped it by luck.

**Diagnosis generalises; repair does not.** The seven audit checks run for every league off a
per-league declaration — that is why shape 1 was answered for four leagues the day the check
was written. The *fixes* are all league-specific (`repair_mlb_identity_names.py`,
`dedupe_mlb.py`, `dedupe_nfl.py`). So audit every league; repair only the ones the product
needs. As of 2026-08-05 **`atp`, `ufc`, `wc`, `wnba` and `wta` have no MANIFEST entry at all
— they are unmeasured, not passing.**

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

### A second defect, found while fixing the first

`enumerate_games()` filtered on `status.type.state == "post"` and then required each
competitor's score to be non-`None`. **A postponed game is `state="post"` too, and its
score is `0`, not `null`:**

```
401810499 | 2026-01-24 | STATUS_POSTPONED completed=False | {'MIN': '0', 'GS': '0'}
401857824 | 2026-01-25 | STATUS_FINAL     completed=True  | {'MIN': '85', 'GS': '111'}
```

So all four postponed shells passed the filter and would have been written as played
0–0 results — crediting both teams a game they did not play, and handing one of them a
loss — while the makeup was written too, from a different event id. Measured: the
enumeration yielded **1235** where the season has 1231 games.

Presence taken as integrity, for the third time in this document: the score field was
*there*. `state` answers "is this in the past". `completed` answers "was it played",
and it was published in the same object the whole time. The filter now reads
`completed`, and the enumeration yields **1231**.

Note what caught it: not a test, and not the reconcile. The per-team distribution —
every team must land on 82 — is the assertion that made 1235 obviously wrong, because
1235 does not divide into a schedule. **Keep a check whose arithmetic can only close one
way.**

### Fix, in order

1. `backfill_team_parity.py` — remove the explicit `BEGIN`/`ROLLBACK` (or open the
   connection with `isolation_level=None` and keep them), so a write cannot be lost to
   transaction state. Filter on `completed`, not `state`.
2. Make the coverage summary honest per §4, then re-run NBA and NHL and confirm all
   30 teams land on 82 and the NHL pair agrees.
3. Teach `published_real_games()` that the exhibition type id is per-league — NBA files
   All-Star under type 2, NFL under type 3 — and read it from the event's
   `competitions[].type.abbreviation`, which is where the answer already is.
