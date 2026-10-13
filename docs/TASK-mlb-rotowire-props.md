# TASK: MLB props from the RotoWire relay, and the two-day hole

Written 2026-08-25. Every number below was measured, not recalled. Sources are named so
you can re-measure rather than trust me.

**Work in a NEW worktree branched from `feat/sport-first-navigation` at `ff38374`, on a new
branch.** Not from `dev`, and not by continuing to commit on `feat/sport-first-navigation`. Two reasons: your existing branch already
modifies `backend/settlement/market_mapping.py` and `backend/link_prop_games.py`, which this
task also touches, and that branch is being audited right now so its commits must stop
moving. Building on top of it keeps both true.

---

## 1. The problem, measured

Production has a two-day hole in MLB props. Nothing links, because nothing was collected.

```
2026-08-21   14 games   1,166 props   1,113 graded     <- last good day
2026-08-22    0 games       0 props                    <- hole
2026-08-23    0 games       0 props                    <- hole
2026-08-24   10 games     988 props     281 graded     <- 3 of 10 final, those 3 graded
```

**It is not a linking defect, and it is worth knowing why before you start.** Every MLB
`prop_games` row that has ever lacked an `espn_event_id` is three rows total, on 2026-06-22
and 2026-08-13, none in this window. 2026-08-20 is 7 of 7 linked. There is nothing on 08-22
or 08-23 to link.

**Cause:** MLB props are 100% Bovada (5,592 of 5,592 rows since 08-18) and the Bovada
timers sat in `SubState=elapsed` with no next elapse from 2026-08-21 11:08 until they were
un-parked on 08-24. See `docs/CONTEXT-2026-08-24.md` §2. The recurrence is already fixed:
those timers are `OnCalendar` now. **This task is about recovering the two days, not about
the timer.**

**Bovada cannot be backfilled.** Those were live offers and they are gone. The only
recoverable source is our own relay archive.

---

## 2. What we already hold

`backend/data/rotowire-archive/rotowire-2026-08-2{2,3}.json.gz`, captured daily, never
ingested for MLB:

```
rotowire-2026-08-22.json.gz   1,610 MLB Game props
rotowire-2026-08-23.json.gz   1,845 MLB Game props
```

Including 138 props for the specific fixture that exposed this, MIN @ SD on 08-23
(ESPN event `401816653`): Buxton runs, Bogaerts, Bailey Ober hits allowed, Walker Buehler
hits allowed, and so on.

`backend/ingest_rotowire_props.py` already has a `--from-archive YYYY-MM-DD` flag that reads
these files and makes **zero** publisher requests. It cannot be used for MLB because
`LEAGUES` contains only `nfl` and `mls`.

---

## 3. Build

### 3a. An `mlb` entry in `LEAGUES`

MLB fits neither existing `kind`, and this is the part to get right rather than fast.

- `kind: "code"` builds its vocabulary by reading the `nfl_schedule` table directly
  (`build_vocabulary`, around line 542). That branch is NFL-specific despite its generic
  name.
- MLB `prop_games` **store display names** (`Minnesota Twins`, `Athletics`), not codes. The
  archive publishes **codes** (`MIN`, `SD`).

**The vocabulary is already published and already on disk. Do not fetch it and do not
hand-write it.** `scoreboard_snapshots` carries both halves for MLB:

```sql
SELECT DISTINCT json_extract(payload,'$.home.abbrev'), json_extract(payload,'$.home.name')
FROM scoreboard_snapshots WHERE league='mlb';
-- ATL|Atlanta Braves   TB|Tampa Bay Rays   PIT|Pittsburgh Pirates ...
```

Resolve the archive's code to the display name that MLB rows already carry. The existing
comment in `game_id_for` states the rule and it is the right one: match on the resolved
identity, store whatever that league's rows already carry. Writing a code into a table of
display names is how a second vocabulary gets started.

`Athletics` has no city prefix and `SD` / `SDG` style variants exist across publishers.
Check the resolved set against the 30 clubs before trusting it, and **fail closed on an
unresolved club rather than minting a fixture beside one we already have.**

### 3b. `MLB_GAME_MARKETS`

**CORRECTION, 2026-08-25, found by codex and verified.** The paragraphs below originally
named `MARKET_STAT` in `backend/settlement/market_mapping.py`. **That is the wrong map for
MLB.** `settle_game.py:81` delegates MLB to `settlement/mlb_settle.py`, which grades against
the **MLB Stats API** boxscore using its own `_MLB_MARKET_MAP`, whose stat keys are that
publisher's camelCase (`strikeOuts`, `baseOnBalls`, `totalBases`, `earnedRuns`), not ESPN's
labels. `market_mapping.py` is still involved, but only for `normalize_market` and
`MARKET_ALIASES`.

**So `backend/settlement/mlb_settle.py` IS in scope**, and section 5 is amended to say so.
Read the canonical keys off `_MLB_MARKET_MAP` (line 23), not off `MARKET_STAT`.

Stopping to ask rather than editing a forbidden file was the right call.

Same shape as `NFL_GAME_MARKETS`: keyed on the publisher's `marketID`, carrying the
`marketName` we verified it under, so a renamed id is refused rather than silently
re-pointed.

The eighteen ids present on 08-23, with counts:

```
215 Singles 79      216 Doubles 50?      218 Home Runs 8      219 Total Bases 236
220 Runs 50         221 RBI 214          222 Walks 208        226 Hits+Runs+RBI 260
227 Wins            229 Earned Runs 25   230 Pitcher Strikeouts 24
231 Hits Allowed 23 232 Walks Allowed 8  234 Outs 24
236 Fantasy Score   237 Fantasy Score 442 (two ids, same name -- check both)
238 Hits 244
```

**These map cleanly to existing `MARKET_STAT` keys.** Start here:

```
219 Total Bases       -> total_bases        (batting, totalBases)
226 Hits+Runs+RBI     -> hits_runs_rbis     (compound, sums H+R+RBI)
229 Earned Runs       -> earned_runs        (pitching, earnedRuns)
230 Pitcher Strikeouts-> strikeouts         (pitching, strikeOuts)
231 Hits Allowed      -> hits_allowed       (pitching, hits)
232 Walks Allowed     -> walks              (pitching, baseOnBalls)
234 Outs              -> outs               (pitching, outs)
```

**THE TRAP, and it would not raise.** `_MLB_MARKET_MAP["walks"]` is
`("pitching", "baseOnBalls")`. RotoWire publishes **222 "Walks" (208 props, batters)** and
**232 "Walks Allowed" (8 props, pitchers)** as different markets. Mapping 222 to `walks`
grades a hitter against a pitcher's stat line and produces a plausible number for the wrong
person. **232 is the one that belongs there. 222 needs its own canonical key and its own
`_MLB_MARKET_MAP` entry, `("batting", "baseOnBalls")`, or it stays unmapped and gets
reported.**

**The second trap: a count line is not an anytime market.** `home_run_any`, `run_any`,
`rbi_any`, `hit_any`, `double_any` answer "did they get one". RotoWire's `Home Runs`,
`Runs`, `RBI`, `Hits`, `Doubles` are numeric lines. Same word, different question. Either
add count-market keys with their own `MARKET_STAT` entries, or leave them unmapped. **Do
not point a count market at an `_any` key.**

`Singles`, `Wins` and `Fantasy Score` have no mapping and no obvious one. `Fantasy Score` is
the largest single bucket; it is a scoring formula, so it would need `ppr_scoring.py` rather
than a boxscore key. **Report all three as unmapped. Do not guess.** An unmapped market that
is counted and printed is the correct outcome, and that reporting already exists.

### 3c. Backfill and settle

Dry run first, DEV before production, and back up before each write.

```
python ingest_rotowire_props.py mlb --from-archive 2026-08-22 --dry-run
python ingest_rotowire_props.py mlb --from-archive 2026-08-23 --dry-run
```

Then link (`link_prop_games.py`) so the fixtures carry `espn_event_id`, then settle. The
acceptance test is the two fixtures that exposed this:

```
/api/game/mlb/401816628/props   TOR @ NYY, 2026-08-22   currently players=0
/api/game/mlb/401816653/props   MIN @ SD,  2026-08-23   currently players=0
```

Both must return players, and the graded ones must carry `actual_value`, so the Props tab
and the "What decided it" panel have something to show.

---

## 4. Explicitly NOT in scope

- **Do not schedule MLB on the relay runner.** `run_props_ingest.py:48` hardcodes `nfl` and
  `mls`. Adding a third line makes MLB an ongoing second source and a third relay request
  per cycle, since `fetch()` is one request per subprocess invocation. That is a real
  product decision about running two publishers per league and it has not been made. **This
  task is the archive backfill only.**
- **Do not touch host config.** No systemd units, no timers, no cron, nothing under `/etc`.
  A worktree does not isolate those.
- **Do not touch the Bovada path** in any way. It is working.
- **Do not repair the 08-24 grading.** It is correct: 7 of 10 games were still in progress
  when measured, and exactly the 3 finals were graded.
- **Do not run `spine_merge`** or repair duplicate groups. Separately deferred by Micah.

## 5. Files you may touch

```
backend/ingest_rotowire_props.py         LEAGUES entry, MLB_GAME_MARKETS, vocabulary branch
backend/settlement/market_mapping.py     new canonical keys ONLY, no changes to existing rows
backend/settlement/mlb_settle.py         _MLB_MARKET_MAP additions ONLY (added to scope 08-25)
backend/test_settlement_mlb*.py          regression tests
backend/test_ingest_rotowire_props.py    regression tests
backend/test_settlement_*.py             regression tests
docs/TASK-mlb-rotowire-props.md          a results section at the bottom
```

Anything else, say why first.

## 6. Verification, and what "done" means

- **A regression test proving the 222 / 232 distinction**, that a batter's walks do not
  grade against `pitching.BB`. This is the whole point; without it the task has not landed.
- **A test that an unmapped market is reported and not ingested**, using `Fantasy Score`.
- Suite green on **both** databases, not just the copy.
- The two acceptance fixtures above return graded props.
- **Say plainly in the results section that these two days are RotoWire-sourced** while the
  days either side are Bovada. That is a visible difference in the product and it should be
  written down, not discovered later.

---

## 7. Results (2026-08-25 UTC)

Implemented and backfilled from a new `feat/mlb-rotowire-backfill` worktree based exactly
on `ff38374`. No scheduler, host configuration, Bovada ingest, 08-24 repair, or
`spine_merge` work was performed.

The archive dry runs made zero publisher requests and produced the same plan against DEV
and production:

```
2026-08-22   14 games   5,196 rows   282 resolved players   6 queued players / 84 rows
2026-08-23   15 games   5,906 rows   297 resolved players   6 queued players / 142 rows
```

Unmapped rows were reported and not ingested: 08-22 had 265 Fantasy Score and 39 Singles;
08-23 had 442 Fantasy Score (176 on id 236 and 266 on id 237) and 79 Singles. The archives
held no prop rows for Doubles id 216 or Wins id 227. The 222 Walks rows ingest as
`batter_walks` and grade from `batting.baseOnBalls`; 232 Walks Allowed ingest as `walks`
and grade from `pitching.baseOnBalls`. Numeric Home Runs, Runs, RBI, Hits, and Doubles use
count-market keys, never `_any` keys.

SQLite online backups, both verified with `PRAGMA quick_check`, were taken before the live
writes:

```
/root/lp-db-backups/picks.dev.pre-mlb-rotowire-20260825T030441Z.db
/root/lp-db-backups/picks.prod.pre-mlb-rotowire-20260825T030441Z.db
```

Final database measurements:

```
             08-22                         08-23
DEV          5,196 props / 4,850 numeric   5,906 props / 5,508 numeric
production   5,196 props / 4,868 numeric   5,906 props / 5,508 numeric
```

Twenty-eight of the 29 fixtures linked to an ESPN event. ATL @ MIL on 08-23 failed closed:
the relay archive says `23:10Z`, while the durable scoreboard says `23:00Z`, and the linker
correctly refuses a known start-time disagreement. Its 482 resolvable rows still settled
through the MLB Stats API path. Both databases remained `PRAGMA quick_check=ok`.

The required API fixtures passed through both the live DEV service (`127.0.0.1:8096`) and
the live production service (`127.0.0.1:8100`):

```
401816628 TOR @ NYY   20 players   83 settled lines   every returned result has actual
401816653 MIN @ SD    20 players   86 settled lines   every returned result has actual
```

Verification: the focused RotoWire/MLB settlement suite passed 34 tests; the full scoped
settlement suite passed 57 tests; and the complete backend suite, using worktree-local
copies of both real database schemas, passed 1,859 tests with 4 skips and 6 expected
failures.

**Source provenance:** 2026-08-22 and 2026-08-23 are RotoWire-sourced archive backfills.
The neighboring 2026-08-21 and 2026-08-24 MLB prop slates are Bovada-sourced. This is an
intentional visible provider difference, not an ongoing second MLB ingest.

---

# ADDENDUM, 2026-08-25: Leagues Cup, same file, same shape

Added while you were working MLB. It belongs here because the fix lives in the same
`LEAGUES` map and has the same shape, so do it in the same worktree and branch.

## 1. The correction that makes this possible

An earlier claim of mine, which reached `DESIGN-sport-first-navigation.md` and the roadmap,
said **"RotoWire publishes soccer as one bucket, zero MLS."** That was measured on the
2026-08-24 archive alone, which was a light day, and written down as a property of the
publisher. **It is wrong.** Scanning all seven archived days:

```
08-19   42 clubs   MLS: 26 clubs                 LigaMX: -
08-21   54 clubs   MLS: 10 clubs                 LigaMX: Tigres UANL, Santos Laguna
08-22   71 clubs   MLS: 16 clubs                 LigaMX: Santos Laguna
08-23   39 clubs   MLS: New England Revolution   LigaMX: Club Necaxa, Pumas UNAM
08-24   12 clubs   MLS: -                        LigaMX: -
```

Liga MX clubs quoted on the same days as MLS clubs **is** Leagues Cup. Across the archive
RotoWire has quoted América, Atlante, Juárez, Pumas UNAM, Santos Laguna and Tigres UANL.

**So the props we want for Leagues Cup, in the seven markets that matter, are already
landing in our archive every day and we discard them.**

## 2. Why we hold zero Leagues Cup props

`LEAGUES["mls"]` is `kind: "club"` and resolves club names against MLS. A Leagues Cup fixture
is MLS versus Liga MX, so one side never resolves, the fixture is counted `unknown_team`, and
the whole thing is dropped. That is precisely the failure the v0.8.7 changelog records:

> Soccer is deliberately not scheduled. The MLS leg failed loud on its first run: a non-empty
> board produced zero props because 236 rows sit under the soccer label without being MLS
> fixtures.

Those 236 rows are the European fixtures **and** the Leagues Cup ones. **The ingest is
refusing correctly.** It simply has no `lcup` league to file them under.

## 3. Build

Add an **`lcup`** entry to `LEAGUES` whose club vocabulary is **MLS plus Liga MX**, so a
fixture with one club from each resolves and files under `lcup`.

**Filing Leagues Cup under `mls` is a known defect, not a shortcut.**
`backend/bovada_scraper/config.py` already states why, and the Bovada parser already gets
this right at `parsers.py:218`:

> If either is a foreign club (AME/GDL/PUE/TOL... Liga MX in a Leagues Cup fixture, NFO in a
> friendly), the fixture is a TOURNAMENT and must file under `lcup` -- its own competition
> key -- so the players stay resolvable against whichever league actually rosters them.
> Filing Leagues Cup under `mls` is the shadow-player defect: it creates players nobody's MLS
> spine can ever resolve.

So the discriminator is already written down and already implemented once, for a different
publisher. **Match that behaviour; do not invent a second rule.**

Read the Liga MX club vocabulary off a published source rather than hand-typing it. Our own
`prop_games` and `scoreboard_snapshots` already carry `lcup` fixtures with both sides'
published names, which is the cheapest source and costs no request.

Two traps, both the same shape as the MLB ones:

- **A club that resolves to neither league must FAIL CLOSED**, not fall back to `mls`. The
  soccer bucket also carries EPL, Serie A, La Liga and Segunda, and those must keep being
  refused and reported, exactly as they are today.
- **Do not widen the `mls` vocabulary to include Liga MX.** That would make Leagues Cup
  fixtures resolve as MLS and reintroduce the shadow-player defect the comment above
  describes. `lcup` needs its own entry.

## 4. Scope

Same locks as the MLB task. Same file list, plus whatever `lcup` needs in
`backend/test_ingest_rotowire_props.py`. **Still not scheduling anything**, so no changes to
`run_props_ingest.py` and no host config.

## 5. Done means

- A regression test proving an **MLS vs Liga MX fixture files under `lcup`**, and that a
  European fixture in the same payload is still refused and reported.
- A regression test proving an MLS vs MLS fixture still files under `mls`.
- A backfill from the archive days above, showing Leagues Cup props that we can currently
  see in the payload and cannot reach in the product.
- Say plainly how many Leagues Cup props exist per archive day, so the coverage claim is a
  measured number rather than "it works now".

## 6. Results (2026-08-25 UTC)

Implemented the competition route without widening MLS. `lcup` reads a complete 30-club
MLS vocabulary and 18-club Liga MX vocabulary from durable `scoreboard_snapshots`, keeps
the memberships separate, and accepts only a fixture with one club from each. MLS-vs-MLS
still files under `mls`; Liga MX-vs-Liga MX and clubs outside both vocabularies fail closed.
The stored abbreviation `ATL` is ambiguous between Atlanta United and Atlante, so raw
`ATL` is deliberately unresolved while both published display names remain distinct.

The addendum's conclusion that same-day MLS and Liga MX quotes were Leagues Cup did not
survive fixture-level measurement. All seven archives contain **zero MLS-vs-Liga MX
fixtures**. The Liga MX quotes are domestic fixtures, including Atlante-Tigres UANL and
Necaxa-Pumas UNAM; they are not Leagues Cup games. Counts below are supported-market source
prop objects before book/side expansion:

```
archive day   Leagues Cup   resolved MLS   resolved Liga MX   other/unknown
2026-08-19              0            123                  0              60
2026-08-20              0              0                  0              23
2026-08-21              0              6                 16              87
2026-08-22              0             34                  0             179
2026-08-23              0             13                 11             208
2026-08-24              0              0                  0             104
2026-08-25              0              0                  0              30
```

Therefore the measured Leagues Cup backfill is **0 props / 0 expanded database rows on
every archive day**. No database backfill was applied. Treating the domestic rows as
Leagues Cup would reproduce the competition-shadowing defect this task was intended to
prevent. The domestic columns require a stored club spelling; `other/unknown` therefore
also retains `Santos Laguna`, because the durable snapshot says `Santos` and no stored
crosswalk proves those names identical.

The task also claimed existing `lcup` rows in both `prop_games` and
`scoreboard_snapshots`. Every inspected current/candidate database has zero `lcup`
`prop_games`; the durable vocabulary is in `scoreboard_snapshots`. DEV has the complete
30 MLS + 18 Liga MX population. Production has only 4 of 18 Liga MX clubs, so the candidate
refuses there with `TeamVocabularyError` instead of using a partial membership oracle.

MLS-side tournament players reuse the MLS canonical player spine and stable RotoWire
binding. Liga MX players remain unresolved because there is no Liga MX player spine; the
ingest does not match the historical Liga MX shadow rows stored under `mls`.

Verification: `backend/test_ingest_rotowire_props.py` passed 35 tests; the combined
RotoWire/MLB settlement set passed 37; and the broader settlement set passed 25. The DEV
clone remained `PRAGMA quick_check=ok`. Representative archive CLI dry runs exited zero,
reported every refused expanded row, and wrote nothing. No scheduler, `run_props_ingest.py`,
host configuration, live database, service, or timer was changed.
