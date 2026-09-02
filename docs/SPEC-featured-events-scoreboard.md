# SPEC: Featured Events scoreboard (scores 2.0)

Written 2026-08-19. Supersedes the scoreboard half of
`TASK-scores-schedule-espn-model.md`, which stays the reference for the week-grouped
navigation. Roadmap §6.

## 0. What is already true, so nobody rebuilds it

Shipped in v0.8.2 and v0.8.3 and verified on production:

- Completed days are **DB-primary**. `scoreboard_snapshots`, fed by two timers, plus a
  capture-once rung for a day we have never held.
- **Zero ESPN requests to load a past date.** Measured: 22 handler calls, 355ms, 85 games,
  zero upstream.
- **Date navigation jumps to the next day the league actually has games**, answered from the
  store. Arrow latency 0.33 to 0.71s, and `future_event_starts` now contains only future.
- **COD included**, so a non-ESPN league is reachable on the same paths.

Two primitives exist and must be reused, not rebuilt:
`docs/API-league-schedule-dates-v1.md` and `docs/API-nfl-schedule-weeks-v1.md`.

**So this spec is about the PAGE, not the data path.** The data path is done.

---

## 1. ESPN's card contract, read from ESPN's own payload

`espn.com` returns 403 to this box and archive.org is not fetchable, so I could not read
their HTML. That turned out not to matter: **their site is built on the same scoreboard
payload we already fetch**, so their field set IS their card contract, and it is sitting in
our cache.

Measured 2026-08-19 off a real MLB scoreboard payload:

```
competition : broadcast, broadcasts, geoBroadcasts, notes, headlines, highlights,
              leaders, venue, neutralSite, conferenceCompetition, recent, format
competitor  : records, leaders, probables, linescores, statistics, winner, hits, errors
```

Populated, on the first game of an ordinary Wednesday:

```
headlines : "Pirates and Tigers meet, winner secures 3-game series"
probables : P. Skenes  vs  J. Jobe
records   : PIT 62-66  (33-32 home)      DET 61-65  (32-31)
broadcast : MLB.TV                        venue: PNC Park
leaders   : 4 per team
```

**We keep none of it.** Our normalized game is:

```
game_id, date, state, completed, status, period, clock, status_detail,
season_type, season_slug, competition_type, home{abbrev,name,nickname,score}, away{...}
```

So on every fetch we discard the team record, the broadcast network, the probable pitchers,
the linescore, the leaders, ESPN's own one-line headline, and the venue, at **zero request
cost to keep them**. This is `feedback_we_systematically_underread_publishers` in its worst
form: not a gap in what we asked for, a gap in what we did with the answer.

**That is the single highest-value change in this spec**, and it is a data-path change, so
it precedes the page. See §9 step 0.

### What I still cannot answer, and would take you two minutes

Sleeper's scoreboard is the homepage and I could not get a structural read of it: their
redesign post says only "a dedicated Scores Tab", and the App Store listing documents
features rather than layout. Two questions actually change the design:

1. Is Sleeper's ordering live-first, chronological, or curated?
2. **What does it show when nothing is playing?** That is our most common state and the one
   we have repeatedly gotten wrong. See §6 for what I have specified in the meantime.

## 2. The principle this page is being rebuilt around

**A scoreboard's job is to answer "what is happening" in one screen, without being asked.**

The current page fails that in a specific way: it opens on a date picker and a flat
league-grouped list, so a viewer must already know what they are looking for. The board
treats a Tuesday with 15 MLB games and a Saturday with 71 NCAAF games identically.

And a hard rule earned on 2026-08-19: **nothing goes above the scoreboard on a page called
Scoreboard.** The "Cheap Quality, Live" widget sat there for six weeks showing nine cards of
last night's games at one cent each, captioned "stabilizing", while the real slate sat below
the fold. See §7.

---

## 3. The page

Top to bottom. Every section is optional and disappears entirely when empty; none of them
renders a placeholder.

### 3.1 Featured Events

Between 3 and 6 cards, larger than a list row, ordered by the ranking in §4.

A featured card carries ESPN's own field set (§1), and only what we can source:

```
league badge · state (LIVE 7th · FINAL · 7:05 PM) · broadcast
away team    record    score
home team    record    score
context line
```

The context line, first one that exists:

| state | line | source |
|---|---|---|
| pre | `P. Skenes vs J. Jobe` | `probables` |
| in / post | ESPN's headline: "winner secures 3-game series" | `headlines` |
| any | top performer | `leaders` |
| fallback | our own story headline | `game_story` |

**If none exists the line is absent, not blank.** Note the first three are ESPN's, free, and
better than anything we would compute. My first draft of this spec invented a hierarchy of
props counts and strength ranks; that was guessing at a question the publisher had already
answered.

### 3.2 The rest of the slate

Everything not featured, grouped by league, in the existing card shape. This is the current
board and it does not need to change.

### 3.3 Day and week navigation

- **Day leagues** (MLB, NBA, NHL, MLS, tennis, UFC, COD): the existing `‹ date ›` control,
  which now answers from the store.
- **Week leagues** (NFL, NCAAF): a week strip, not a date picker. NFL and NCAAF are played in
  weeks and a drafter thinks in weeks. `API-nfl-schedule-weeks-v1` already serves ESPN's own
  week calendar and is live on `pages/leagues/[league].tsx`.

**NCAAF opens 2026-08-29.** That is the only dated constraint in this spec.

---

## 4. What gets featured

Computed on the server, returned as a `featured` array, so the client renders and does not
decide. Every input is already in the database; **nothing here costs a publisher request.**

Score each game and take the top N:

| signal | weight | source | why |
|---|---|---|---|
| in progress | +100 | `state = 'in'` | a live game beats any scheduled one |
| close and late | +40 | score margin and period, per league | the reason to look right now |
| starting within 2h | +25 | `start_time` | the next thing to care about |
| both teams strong | +20 | `records`, then `strength_snap` | a good matchup |
| has a story | +10 | `game_story` | we have something to say about it |
| has props | +10 | `props` count | it is a game we cover deeply |
| league priority | +0 to 15 | fixed table | breaks ties toward the sports we serve |

Rules that are not weights:

- **At most 2 featured games per league**, so a 15-game MLB slate cannot take the whole strip.
- **Never feature a game we cannot render**: no team names, no start time, nothing to show.
- **A finished day features the best finished games**, using the same score minus the live
  and starting-soon terms. Yesterday's board should still lead with the game worth seeing.
- **The score is returned in the payload**, not just the ordering. A ranking we cannot inspect
  is one nobody can debug later.

Ties break on start time, then league priority, then `game_id`, so the order is stable
between refreshes. **A board that reshuffles under the reader is worse than a flat list.**

---

## 5. The API

One endpoint, additive, leaving `/api/{league}/games` exactly as it is:

```
GET /api/scores/board?date=YYYY-MM-DD&leagues=all
```

```jsonc
{
  "contract": "scores-board-v1",
  "date": "2026-08-19",
  "generated_at": "2026-08-19T14:32:00Z",
  "source": "scoreboard_snapshots",     // never "espn" for a past date
  "age_seconds": 41,
  "featured": [ { "game_id": "...", "league": "mlb", "score": 145,
                  "reasons": ["in progress", "close and late"] } ],   // ids + ranking only
  "leagues": [ { "league": "mlb", "games": [ /* the existing shape */ ] } ],
  "missing": ["nhl"]                    // in season, asked, nothing held. NOT an empty list.
}
```

`missing` is the honest half. A league we hold nothing for is named, so the page can say "we
have nothing for the NHL today" rather than implying the NHL is not playing.

---

## 6. When there is nothing on

**This is the most common state and the one we keep getting wrong.** At 09:50 on a weekday in
August, every MLB game is `pre` and nothing else is in season.

The page must then lead with **what is next**, not with an empty strip and not with a filler
module:

```
Next up
  MLB · 11:35 AM   Pittsburgh at Detroit
  MLB · 12:10 PM   New York at San Diego
```

Rules:

- Featured collapses to "Next up" when nothing is live, using the same ranking minus the live
  term. No separate code path, no empty state to design.
- If we hold nothing at all for the date, say so and name the date. **Do not show yesterday.**
- **Never render a value we cannot source.** A missing score is a dash, not a zero; a missing
  price is nothing at all, not one cent.

---

## 6b. How it looks, per `.claude/skills/honest-data-ui`

I wrote §3 to §6 before loading that skill. These are the rules it adds, and none of them is
a style preference.

**Hierarchy comes from position and space, never from chrome.** A featured card is larger and
higher; it gets no gradient, glow or shadow. The data is the ornament. These are instruments,
closer to a depth chart or a box score than to a magazine spread.

**The accent color marks absence, not achievement.** This is the board's signature and every
surface inheriting from it keeps it. On a scoreboard that means the saturated color goes to a
game we cannot fully render, a league in `missing`, a score we do not hold. Everything present
stays quiet and neutral. Ink goes to the holes, because the holes are what no competitor shows.

**A dash is not a zero.** A missing score renders as a dash, visibly different from `0`. Zero
is a claim about the game; absence is a claim about us. That is the same distinction that made
the one-cent price a defect rather than a rounding error.

**Scan, do not read.** A viewer must be able to rank the featured games by shape and position
before reading a digit. If two cards can only be told apart by reading them, the layout has
failed. Tabular figures, so scores align in a column.

**Name the condition on any derived number.** §4's context line may use strength rank, and a
rank is conditional: as of when, over what sample. Either the card says so ("#2 in MLB, last
30 days") or it does not show the rank. A rank with no condition is the flattering average in
a different costume.

**Payload budget: the board must not download more than it renders.** State the measured
payload and time before shipping, per `docs/DEV-STANDARDS.md`. Featured games already appear
in `leagues[]`, so `featured` carries **game ids and the ranking, never duplicate card
objects.**

**Avoid the three looks AI design defaults into** regardless of brief: cream with a
high-contrast serif and terracotta; near-black with one acid accent; broadsheet hairlines at
zero radius. Draw from roster sheets, depth charts, box scores and injury reports instead.

---

## 7. What may never go on this page

Earned on 2026-08-19, and the reason this section exists at all.

The "Cheap Quality, Live" widget was mounted above the scoreboard on 2026-07-04 and verified
that same evening, mid-slate, in the one condition where it works. At 09:50 ET on 08-19 it
was showing **nine cards, every one of them the previous night's game, every price 1 cent**,
including a team shown at 1c after winning 6-0, captioned "touched the 19c level set pregame
· stabilizing". The correct slate sat below it.

So:

1. **Nothing sits above the scoreboard on the scoreboard page.** Secondary modules go below
   the slate or on their own page.
2. **A module that can be wrong must be able to say nothing.** Every surface here needs a
   defined empty state that is reachable in normal operation.
3. **Verify in the empty window, not the busy one.** Any acceptance check for this page runs
   at a time when nothing is live. That single rule would have caught the widget, the props
   board serving finished games, and today's dead forward arrow.

---

## 8. Performance, and the gate

Target: **zero ESPN requests to render any date, past, present or future.** Today's board
already meets it; this keeps it met.

The original task called for a **request-count gate** enforcing that. Build the gate, but note
what it can and cannot say: a gate reading `paced_http`'s counter is reading a **per-process**
number while the limit is per host, and 17 modules reach ESPN without going through
`paced_http` at all. See `docs/DESIGN-request-budget.md`.

**So the gate ships in two parts.** Part one, buildable now: assert the board handler issues
zero requests through `paced_http` for a given date, which is a true statement about this
page. Part two, after the budget question is settled: a box-wide count.

Do not let part two block the page. **Do not let part one be mistaken for part two.**

---

## 9. Build order

0. **Stop discarding ESPN's fields at normalization** (§1): records, broadcast, probables,
   linescores, leaders, headlines, venue. Additive to the normalized shape, no new requests,
   and everything after this depends on it.
1. **`/api/scores/board`** with §4's ranking and §5's contract. Pure server work over data we
   already hold, testable offline, no UI risk.
2. **Featured Events strip** on `/scores`, reading `featured`. The rest of the page unchanged.
3. **"Next up" collapse** (§6), which is the same component with the live term removed.
4. **Week strip for NFL and NCAAF** (§3.3), against the existing weeks API. **Before Aug 29.**
5. **Part-one gate** (§8).

Steps 1 to 3 are the page. Step 4 has the deadline. Step 5 is the guard rail.

## 10. Open questions for Micah

1. The two in §1. Especially: what does Sleeper show when nothing is playing?
2. Featured count: 3, 4 or 6? It changes whether the strip is one row or two.
3. Should Featured span leagues, or be one row per league we cover?
4. Does `/scores` become the homepage, as Sleeper's is? That is a bigger change than this
   spec and would reorder §9.
