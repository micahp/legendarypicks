---
name: published-first
description: MUST load before writing any code that derives, aggregates, reconstructs, infers, back-fills or estimates a value — season totals, per-game rates, schedules, bye weeks, standings, rankings, splits, "games played", "weeks missed", team records, ADP tiers, or any join key — AND before trusting any table you just ingested. Encodes one rule with a measured cost behind it: check whether the value is already published before you compute it, check whether the key you are joining on is the same word on both sides, and check your row count against the publisher's count. Triggers on "let's compute", "derive", "roll up", "aggregate", "reconstruct", "backfill", "infer", "we can calculate that from", any GROUP BY over a raw event table, any new ingest script, and on "is this data complete", "did the ingest work", "these numbers look off", "how many should there be".
---

# Published first

Load this before computing a number. It is the data-provenance sibling of
[ponytail](https://github.com/DietrichGebert/ponytail), which asks *"does this
code need to exist?"* — this one asks **"does this value need to be computed?"**

---

## 1. The governing principle

> A derived number is a liability. A copied number is a fact.

Every derivation is a **reimplementation of someone else's definition**, and it
inherits none of their testing. The publisher has already decided what counts as
a game played, whether a bye is an absence, which snaps are special teams. When
you rebuild that from raw events you are not saving a dependency — you are
forking a spec you have never read, and your version will disagree in ways that
look plausible.

**The failures never announce themselves.** They produce numbers of the right
shape and magnitude, in the right column, that nobody can spot by looking.

---

## 2. The ladder — walk it before you write the query

1. **Is the value already a column in our database?** → read it.
2. **Is it published by a source we already ingest?** → ingest that field. One
   more column beats one more derivation, permanently.
3. **Is it published by anyone authoritative?** → write the ingest. An ingest is
   a copy with a checksum; a derivation is a program with bugs.
4. **Is it one join away from a published value?** → join.
5. **Is it a definition, not a computation?** (a schedule, a roster, a bye week,
   a team code) → it is *always* published somewhere. Never infer it.
6. **Only then compute** — and make it falsifiable against a published value
   before you ship it.

Rung 5 is the one that keeps getting skipped, because a schedule feels like
something you can work out from data you already have.

---

## 2b. A gap is a question until it is measured — never write it down as a fact

The ladder only works if you actually walk it. The way it gets skipped is not
laziness, it is **a question getting recorded as a statement.**

Someone asks *"does anyone publish earned runs?"*, doesn't find it in the one
place they looked, and writes into a document:

> **ERA** — no. Nothing publishes earned runs into our logs.

That sentence is now evidence. The next person reads it, believes it, and plans
around it. The question is never asked again, because it looks answered.

Audited 2026-08-04. Every headline data gap in this repo was of exactly this
kind — a statement about which endpoint someone happened to ask, written down as
a property of the world.

**Separate two kinds of gap before claiming either**, because conflating them
overstates the finding and the overstatement is what gets repeated:

*Acquisition gaps* — the value is in no table we hold. These were real:

| written as | actually |
|---|---|
| "no goalie source at all" | `api.nhle.com/.../goalie/summary`, league-wide, one request. Absent from logs AND aggregates — genuinely nowhere |
| "no ERA anywhere in this database" | `statsapi.mlb.com`, one request. No earned-run key existed in any table |
| MLB team/position "needs an `espn_id` crosswalk" | MLB publishes both itself; the column was 100% blank |

*Surfacing gaps* — the value was already in the building, just not in the table
the product reads. Equally user-visible, **not** the same claim:

| written as | actually |
|---|---|
| NFL "no such column: rush_td, rec_td" | already in `player_game_logs` as `rush_td`, `rec_td`, `att`; only the season row lacked them |
| MLB "no PA / hits / RBI" | already in the logs as `PA`, `H`, `RBI` |
| NBA leaderboard three years stale | 23,749 2026 log rows already held |

Both are worth fixing and both trace to the same cause — a question recorded as
a statement. But **"we have no touchdown data" and "our season table has no
touchdown column" are different sentences**, and only the second one was true.
Say which you mean.

For a surfacing gap the fix is still to read the publisher's own total rather
than roll up our logs — see §3, where a rollup this repo derived from nflverse
events shipped eight defects, every one a bug in the reimplementation. But the
justification is *"a published total is a fact and a summed one is a program"*,
not *"we could not get this data"*.

**The rule.** Before recording any value as unavailable, unreachable,
underivable or unpublished:

1. **Enumerate every publisher the league already has** — not the one that came
   to mind. Read what each actually returns for that field.
2. **Write down what you asked**, not just what you concluded: the endpoint, the
   parameters, the date. `"absent from statsapi /stats?group=pitching on
   2026-08-04"` is falsifiable. `"nobody publishes ERA"` is not, and it is the
   sentence that costs a year.
3. **A gap with no endpoint named next to it is unverified**, no matter which
   document it is written in or how long it has been there. Treat it as an open
   question and re-ask.

Corollary for *fixing* a gap: check whether the value is published before
building the derivation, and check again before believing an old note that says
it isn't. Documents rot in exactly one direction — toward "we can't."

---

## 3. Three times this repo paid for skipping it

**The nflverse rollup.** We reimplemented a season rollup that nflverse publishes
as `stats_player_week_YEAR.parquet`. An audit found eight defects. Every one was
a bug in the reimplementation, not in the data — filters that were *reasoned*
about rather than measured. The correct fix was not to fix the eight; it was to
delete the derivation. **Derive filters by measurement against the published
file, never by reasoning about what ought to count.**

**`team_weeks`, three passes.** The mock draft needed "which weeks did this
player's team play." Pass 1 wrote `list(range(1, 18))` — not a schedule at all,
just seventeen numbers. It rendered as a confident 17-cell strip with the byes in
the wrong place, and because the accent colour marks absence, it **painted fake
missed games in amber on players who never missed one.** Passes 2 and 3 rebuilt
it from player game logs and eventually got it right. All three passes were
spent reconstructing a schedule that nflverse publishes — and that `nfl_schedule`
already held for 2026, while 2025 had simply never been ingested. The published
2025 schedule agrees with the final derivation exactly. Three passes to arrive at
a value we could have copied.

**The join key itself.** `players` says `LAR`/`WSH` (ESPN); `player_game_logs`
and the schedule said `LA`/`WAS` (nflverse). Nobody derived that — everybody
*assumed* it. The lookup for 178 active players silently returned nothing for
months, which the mock draft then papered over with the fabricated schedule
above. **A wrong key does not raise. It misses.**

---

## 4. How to actually check, in about a minute

```bash
# Is it already a column?
sqlite3 backend/data/picks.dev.db ".tables"
sqlite3 backend/data/picks.dev.db "PRAGMA table_info(<table>)"

# Does an ingest already pull it, or pull the file it lives in?
ls backend/ingest_*.py && grep -rn "<the concept>" backend/ingest_*.py

# Does the upstream publish it? (nflverse publishes far more than we ingest)
#   games.csv, stats_player_week_*.parquet, rosters, snap counts, depth charts
```

Then the question that settles it: **what would the publisher call this?** If the
concept has a name in someone else's schema — `bye_week`, `games_played`,
`team_weeks`, `game_type` — it is published, and you are about to fork it.

---

## 5. If you genuinely must derive

- **Validate against a published value before shipping.** Not a unit test with a
  fixture you wrote — the real published number. A test whose input you invented
  cannot fail the way production will. (A 200-draft simulation once passed
  against a synthetic pool with even 60-per-position depth; the real pool had 15
  kickers. It could not have failed the constraint it existed to test.)
- **Measure join coverage and print it.** `matched N of M` in the ingest output.
  A silent miss is the default failure mode, and coverage is the only thing that
  surfaces it.
- **Normalise at the boundary, once.** Convert vocabularies at ingest, not at
  each read site. An alias map consulted by readers is a second source of truth
  that every future query has to remember — this repo has three copies of the
  same `LA → LAR` map and that is two too many.
- **State `n` wherever the derived value is displayed** — see
  `.claude/skills/honest-data-ui/SKILL.md`.

---

## 6. The publisher also publishes *how many* — reconcile against it

Everything above is about a value. This is about a **count**, and it is the same idea
one level up: before you trust a table, ask the publisher how many rows it should have.

A partial ingest is invisible. It has no error, no gap in the UI, no failing test — it
looks exactly like a complete one, because the rows that landed are all correct. The
only thing that distinguishes them is a number you have to go and get.

**You do not need to traverse the API to get it.** ESPN's core API returns the
cardinality of any collection in the envelope of a `limit=1` request — one HTTP call,
no key, no paging:

```bash
B=https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/2025
curl -s "$B/types/2/events?limit=1"        | jq .count   # 272  regular-season games
curl -s "$B/types/3/events?limit=1"        | jq .count   #  14  postseason + Pro Bowl
curl -s "$B/teams?limit=1"                 | jq .count   #  32
curl -s "$B/athletes/4431452/eventlog?limit=1" | jq .events.count   # 17 for one player
```

Same shape for the other leagues — swap the path segment: `basketball/leagues/nba`,
`baseball/leagues/mlb`, `hockey/leagues/nhl`. (Note `sports.core.api.espn.com` answers
this box fine; **`www.espn.com` 403s it** — the bot wall is on the website, not the API.)

`backend/reconcile_totals.py` runs these as a suite and exits non-zero on disagreement:

```bash
LP_DB_PATH=backend/data/picks.dev.db python3 backend/reconcile_totals.py --league nfl --season 2025
```

**Run it after every ingest, and before believing any season you did not personally
load.** Measured 2026-08-02: 2025 passes every check; **2024 fails four.** Its 5,597 game
logs cover all 285 games but only 612 players against 2025's 2,024 — WR/RB/TE/QB and
almost nothing else, because 2024 was never re-ingested after the all-positions fix. And
every 2024 row has a **NULL `game_type`**, so any query saying `WHERE game_type='REG'`
returns zero rows for that season and reports it as an empty result, not an error.

### Two things that will bite you, both found writing that script

**The oracle answers its own question, not yours.** ESPN files the Pro Bowl under season
type 3, so its postseason count is 14 where the playoff bracket is 13. The `eventlog`
endpoint is regular-season only, so a Patriot with 17 there played 21 games in a year
they reached the Super Bowl. The first run of this script reported both as defects and
named seven healthy players as short. **A disagreement with the publisher is a question,
not a verdict — reconcile the definitions before you file the bug.** Encode the
definition once you have measured it, the way `published_real_games()` filters
`competitions[0].type.abbreviation == "ALLSTAR"`.

**A missing oracle is a FAIL, not a skip.** If the count can't be fetched, the check has
produced no evidence, and "no evidence" must never render green or shrink a denominator
until the remainder passes. See the `NO-ORACLE` status and the `(partial)` line.

---

## 7. Before you call it done

- Name the published source you checked, or say plainly that none exists.
- If you derived: show the comparison against the published value, with counts.
  "Byte-identical for 243 of 243 shared rows" is a result. "Verified" is not.
- If a number in a spec or handoff disagrees with what you measured, **the
  measurement wins** and the document gets corrected in the same commit.
