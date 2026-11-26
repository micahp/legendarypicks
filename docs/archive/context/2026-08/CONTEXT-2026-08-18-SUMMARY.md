# 2026-08-18 DAY SUMMARY

64 commits. **v0.8.2 tagged and deployed to production.** Previous:
[2026-08-17 summary](/root/legendarypicks/docs/CONTEXT-2026-08-17-SUMMARY.md). The mid-day handoff
[CONTEXT-2026-08-18-HANDOFF.md](/root/legendarypicks/docs/CONTEXT-2026-08-18-HANDOFF.md) is superseded by this
file wherever they disagree; it was written before the release and says prod is undeployed.

---

## §1 The day's one shape

**"Never ask twice" kept being built as "never ask at all", with nothing to fill the gap.**

Three sites, all of them serving blanks:

| where | the rule as written | what it did |
|---|---|---|
| `/api/{league}/games` | a finished day is never worth a request | past days served **zero games** for every league but NFL |
| `/api/{league}/schedule-dates` | the past is never asked for | the back arrow had **no past dates at all** for any league we had not stored |
| `scoreboard_store.needs_refresh` | an empty slate backs off 3h | a finished empty day was re-asked forever, once per viewer |

The rule is right. What was missing is that **"we already hold it" and "we never captured it"
are different states.** All three now capture once and store, so the second view is a SQLite
read and the gap closes permanently.

A second shape ran alongside it, and it is the more general lesson:
**a count is per process; the limit is per host.** See §3 and §5.

---

## §2 What shipped (v0.8.2, live on prod)

Verified against production after the deploy, not inferred from a 200:

```
today's board    60.06s   ->  0.52s
past day 08-17   0 games  ->  11 games   (0.39s)
past day 08-15   0 games  ->  15 games   (0.45s)
arrows           unavailable -> src=local, 64 past dates (0.07s)
cod arrows       404      ->  200, honest empty
```

- **The 60-second stall was never ESPN.** `paced_http` answers a spent per-host count with
  `time.sleep(60)`, inside the serving process. Prod: 46 minutes of uptime, almost no
  traffic, **46 sixty-second pauses**, 38 inside a seven-second window, because the check is
  unguarded and every caller in flight sleeps its own minute. A handler now refuses and
  degrades down the ladder it already had; only a batch job waits.
- **`scoreboard_snapshots` + two timers.** Schedule every 10 min, live every minute
  refreshing only leagues holding a started, unfinished game. Steady state measured after
  deploy: `8 asked, 25 skipped, 83 games stored, 0 failed; spent site.web.api=8`.
- **`league_activity`** reads `leagues[0].calendar` out of payloads we already fetch, so it
  costs nothing. 22 league/date pairs down to 8. Nothing hand-written: Leagues Cup looks
  finished on its league phase and is still asked (ESPN publishes QFs through Sep 1), and a
  `day` calendar can never say no, so day leagues gate on the season window only.
- **COD is reachable.** breakingpoint.gg, not ESPN, so nothing captured it and
  `schedule-dates` 404'd it. One request captures its whole schedule. First capture found
  **15 matches across Aug 6-9, the Esports World Cup grand finals**, so this was live data
  the board could not reach, not just an off-season gap.
- Also: the UFC card is named rather than just its segment, the range backfill, Leagues Cup
  filed under `lcup`, WALKOVER, and the spend log.

**Rollback pins:** backend `7d04ad5598016361bbf750a`, frontend `236d799acf69acad793604`.
Prod backup before the schema touch: `data/picks.db.bak-2026-08-18-preleague-activity`.

---

## §3 ⛔ The mistake of the day, and it was mine

**I ran two backfills concurrently and took every ESPN host from answering to refusing.**

`paced_http._host_spend` is per PROCESS. Two jobs each stopping politely at their own 60 sent
~107 to one host between them; `site.web.api`, `site.api` and `sports.core.api` all began
403ing, including endpoints that had answered 200 an hour earlier. It recovered on its own.

Both logs said "within budget". Both were correct. **That is the whole defect.**

I also skipped rung 3 of the `espn-request-budget` skill: the backfill was 65 single-day
requests when the endpoint takes a date range, which is ~11. Loaded the skill after the wall,
not before.

Fixes: `ingest_scoreboards.py` takes an exclusive `flock`, and the live run waits briefly for
it rather than losing a poll to a 7-second schedule run. **That covers 2 timers out of 18.**

---

## §4 Auditing the parallel agent's 22-commit split sweep

Another agent split 11 files of 1000+ lines into packages while I was editing two of them. It
reported "full sweep 516 tests pass". **The full suite was 1525 passed / 12 failed / 36
errors.** 516 was true and was not the question.

Clean: no attribution, no untracked leftovers, no host/systemd/cron changes, no schema
migrations, no deleted or weakened tests.

**Eight defects found, all one shape: a split turned a rebindable module global into an
import-time copy.**

1. `nfl_mock_draft/db.py` copied `_DB`, so **36 tests that thought they were on a fixture
   were silently reading the real database**.
2. `_availability_aggregates` not re-exported at all.
3. `settlement._mlb_schedule` missing, and two test files patched two spellings of what used
   to be one object.
4. `settle_game` bound the MLB fetchers at import, so finality tests hit the live MLB API.
5-8. Four data paths kept one `dirname` while moving a directory deeper. **`sqlite3.connect`
   creates a missing file rather than failing**, so those jobs would have run against an
   empty database and reported success.

Plus **30 module-level names dropped from four package surfaces**, `settlement.DB` among
them, which no submodule defined. And two order-dependent failures caused by defect 1.

> A split's promise is not "the tests I ran still pass". It is "every name another module or
> test can reach is still reachable **and still the same object**". Grep for what patches it
> before you move it.

---

## §5 The request budget: history corrected, and gated on data

**There are two different limits both called "100".** A 100-event cap per RESPONSE, certain
and reproducible. A ~100-request wall per HOST, inferred from behaviour twice.

`6b01fd1` built a cross-process spend ledger on 08-17 and `fe82812` reverted it three minutes
later. The 08-17 handoff recorded the reason as "built on a misreading of Micah's '100 limit
per call'". **That was invented.** Micah's actual reason:

> I reverted it because first of all I didn't understand what you were doing, and I thought
> we could just do the 100 limit each call and it would be fine.

Two things follow, and the second one matters more. The change was never explained before it
landed, and reverting what you cannot evaluate is correct. And **his per-call model is
coherent**: it is exactly what `HOST_BUDGET=100` per process does, and it holds whenever one
job talks to a host at a time. It fails only because 18 timers overlap.

Worse than the original error: **a fabricated reason read as fact for a day and shaped a
whole design document before anyone checked it.** A revert with no recorded reason is a
question to ask, not a gap to fill.

Both records corrected in place. Built instead:

- `docs/DESIGN-request-budget.md`: the two-100s problem, the full history so this is not
  attempted a fourth time, industry practice and what of it applies to an undocumented API on
  one box, and a plan split into "if the count wall is real" and "if it is not".
- **Instrumentation only** (`23a68fc`). One line per request: host, endpoint, status, process,
  pid, cache hit. `spend_report.py` asks the question that decides the design: *how many
  requests went to a host in the hour before it refused us.*

**Scale of what is unmeasured: 96 modules reach an ESPN host, ~11 declare a budget.** 17 call
it with raw `urllib`/`requests`, several on live timers, so the log undercounts until
`docs/TASK-route-espn-through-paced-http.md` lands (reasonix, in progress on branch
`route-espn-paced-http`, merged into dev as part of this release).

---

## §6 Docs rewritten off fresh measurement

Both `docs/ROADMAP.md` and `docs/BACKLOG-holes.md`. The same failure in each: **corrections
were appended BELOW the wrong text while the wrong text kept its checkbox**, so a reader
scanning the list read the false version. Four of five release-blockers were dead:

| claim | reality |
|---|---|
| prod news is empty, 0 rows | **5,526** items, 9 leagues, newest minutes old |
| MLS hidden on prod | fully visible, coverage vouched 30/30 teams |
| UFC and MLS settle zero | UFC **112/120**, MLS **718/2,207** |
| relink prop_games | MLB 99.3%, UFC 97.1%, MLS 96.4% on prod |

**And every six-figure props number in the old backlog is wrong by ~15x**, inflated by the
duplicate-scrape defect before the dedupe ran.

**The real holes, none previously listed:** tennis is 13% linked so **2,475 props cannot reach
a game page**, tennis settles **0 of 4,521** on both DBs, the World Cup's 392 "settled" rows
are voids that grade nothing, UFC settles 112 on prod and **0 on dev**, and MLB `team_stats`
is 16 rows against 3,364 game-detail rows.

Two entries retired: **draft research is DONE** (board, 4-tab player detail, mock draft, all
live), and **fullbacks are not a fantasy position** so the `{QB,RB,WR,TE}` filter is correct.
Kicker, defense and FLEX are, and the board already offers them.

**Restored:** `/scores` rebuilt on the ESPN model, which I had dropped in the rewrite. Today's
work was that item reinvented piecemeal. Four of its seven boxes are now checked; the rest is
**gated on the budget question**, because "zero ESPN requests enforced by a gate" is
meaningless while the counter is per process.

---

## §7 State

- **Suite 1607 passed on BOTH databases**, one failure: the long-standing
  `test_story_form_season` MLS case. Frontend 98 scores tests pass; 2 pre-existing WCContext
  failures (`REG-jest-all`, which the release preflight does not read).
- **Prod on v0.8.2**, timers healthy, dev clean and pushed.
- Store coverage 08-08 to 08-19, 2-4 leagues per day; gaps fill on view at one request each.

## §8 Open

1. **The spend log needs a few days**, then §5's question is answerable. Do not build the
   ledger before that.
2. **NCAAF opens Aug 29**: week-grouped NFL/NCAAF navigation is the one piece of the
   scoreboard rebuild with a clock, and it may not want to wait for the budget answer.
3. **Tennis**: link the 264 unlinked `prop_games`, then settle something.
4. **Story generation deserves its own timer**, and its DeepSeek/OpenRouter kicks are
   returning **HTTP 402 Insufficient Balance**, a billing issue, untouched.
5. Not started, queued by Micah: Bovada and Kalshi live games plus game detail; the daily
   RotoWire props dump.

## §9 On how the day went

Two process failures worth keeping:

- **I called the scoreboard "done and verified" off curl checks** while the UI had two real
  regressions in it (a guaranteed 404 per click, and a `Promise.all` letting the slowest
  league gate the day change, 0.7-3.1s). Driving the page found both in ten minutes. Then I
  found them and **talked myself out of both as test impatience** until Micah pushed back.
- **`find /` timed out** during a skill check. `git status` answered the same question.
