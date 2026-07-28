---
name: published-first
description: MUST load before writing any code that derives, aggregates, reconstructs, infers, back-fills or estimates a value — season totals, per-game rates, schedules, bye weeks, standings, rankings, splits, "games played", "weeks missed", team records, ADP tiers, or any join key. Encodes one rule with a measured cost behind it: check whether the value is already published before you compute it, and check whether the key you are joining on is the same word on both sides. Triggers on "let's compute", "derive", "roll up", "aggregate", "reconstruct", "backfill", "infer", "we can calculate that from", any GROUP BY over a raw event table, and any new ingest script.
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

## 6. Before you call it done

- Name the published source you checked, or say plainly that none exists.
- If you derived: show the comparison against the published value, with counts.
  "Byte-identical for 243 of 243 shared rows" is a result. "Verified" is not.
- If a number in a spec or handoff disagrees with what you measured, **the
  measurement wins** and the document gets corrected in the same commit.
