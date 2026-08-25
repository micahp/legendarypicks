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
