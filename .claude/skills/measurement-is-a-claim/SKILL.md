---
name: measurement-is-a-claim
description: MUST load before writing down any number, count, zero, percentage or coverage statement as a fact about a publisher, a league, a source or the data — and before saying "X does not have Y", "only Z publishes this", "there are none", "N% of the board", or "it stops at". Encodes the repeated failure where the measurement described the INSTRUMENT — the query, the sample, the day, the endpoint, the league list — and got written down as a property of the world, then read as settled by everyone after. Triggers on any count, any zero, any "no rows", any "not available", any coverage table, any claim in a comment or docstring about what a source publishes, and any moment you are about to generalise from one payload.
---

# A measurement is a claim about the instrument

Load this before any sentence of the form *"X doesn't have Y."*

It exists because on 2026-08-26 a single session wrote down **eight** false facts about
publishers, every one of them a correct measurement of the wrong thing, and each one
would have read as settled to the next person.

## 1. The shape

You run something. It returns a number. You write the number down as a fact about the
world. But the number is always a fact about **what you asked**, and the gap between
those two is where every one of these lives.

| written down | what was actually measured |
|---|---|
| "`sot` has 0 MLS log rows" | a lookup through the *ligamx* map, which has no `sot` entry — 0 by construction. The key is on 21,177 rows |
| "607 projections have no game link" | team-abbreviation matching. The games were linked; the abbreviations were absent |
| "RotoWire's soccer stops at MLS" | our own `LEAGUES` dict, which asks for four leagues |
| "no source outside PrizePicks prices goalie saves" | one day's relay. Saves appear on all 8 archived days, 142 props |
| "tackles/clearances/crosses are FotMob-only" | which provider we had looked at |
| "59% of the board dashes" | a 500-row API page. Over the whole board it is 66.6% |
| "87% of Liga MX props are chartable" | SQL. The endpoint refuses on the market map *before* rows matter |
| "the relay republishes almost none of it" | 22 props on one fixture, one day |

The seventh is the sharpest: **the SQL was right and irrelevant**, because the code path
that runs answers earlier and differently.

## 2. The rules

**Name the instrument in the sentence.** Not "Liga MX has no tackles" but "the *summary
endpoint* publishes no tackles for Liga MX." If the sentence cannot name what was asked,
it is not yet a finding. A claim without its instrument is the thing that ossifies.

**A zero is a property of your query until you have tried to falsify the query.** Before
writing a zero down, ask it a second way. `sot` returned 0 through one map and 21,177
through a direct key check. If two ways disagree, *that disagreement is the finding.*

**One sample is not a series.** Daily soccer volume in the RotoWire relay ran 183, 23,
112, 229, 246, 113, 32, 41 across eight days. Any single day supports a confident,
wrong sentence. `backend/data/rotowire-archive` exists precisely so this question is
answered from a series — and it was already on disk every time.

**Measure through the path that runs.** The chart refuses on `_MARKET_STAT_KEY` before
it ever queries logs, so a coverage number computed in SQL cannot describe what the page
shows. Replay the endpoint's own requests. If the user is looking at a page, the page is
the instrument.

**Write the reason, not just the fix.** `first_goal_scorer` was mapped to `None` with
"it is an ORDER market and no per-game stat answers it." The mapping was defensible; the
reason was false, and a false reason reads as settled and stops the next person looking.
That one cost 1,249 board rows.

**A note that has gone stale is worse than no note.** `LEAGUE-STAT-GAPS.md` recorded GK
saves as "published, unmapped" long after the ingest started writing them. The gap had
moved to the read side, where nothing was tracking it, while the doc pointed at a
problem that was already fixed.

## 3. Before you write the number down

- Can I name the endpoint, the query, the day, and the league list it came from?
- Did I ask a second way, and did the two agree?
- Is this one sample, when a series is on disk?
- Is this the path that actually runs, or a path that resembles it?
- If this turns out to be wrong later, what will have made it *look* settled?

## 4. Related

`answer-is-already-here` — the data is on the box. This skill is about what happens
*after* you find it. `falsify-before-merge` — a green suite is the same failure wearing a
test's clothes. `published-first` — do not derive what a publisher already sends.
