# CONTEXT HANDOFF — 2026-08-04 (part 2, evening)

Supersedes `/root/legendarypicks/docs/CONTEXT-2026-08-04-HANDOFF.md` for everything below. That file's
headline items are now **resolved**: prod scores/standings are 200, the NHL
three-player-types work is on `dev`, and the MLB rebuild archives 778 rows rather
than 2,653.

Branch `dev`, HEAD `a804c9f`. **v0.7.3 and v0.7.4 are both tagged and pushed.**

### Final state of the evening (read this before the detail below)

* **v0.7.3** (`fe29eac`) — NFL touchdowns, the roster spine, the position
  vocabulary gate, the per-host budget. Notes in `CHANGELOG.md`.
* **v0.7.4** (`11d38c7`) — `4040ce6`, `paced_http.py`: one paced/budgeted/cached
  client instead of six copies. Also carries the fix for a regression `1c9e77c`
  introduced, where a serving-path 403 blocked **155s** on the retry ladder
  before falling through to the stale payload. Retries are now opt-in
  (`set_retry_waits`), so a page load fails fast to stale and only batch jobs
  wait a refusal out.
* **`a804c9f`** — `release.sh` now refuses to ship deprecated code that is still
  reachable. **It blocks the next release until `nba_service.py` is dealt with**:
  a deprecated FastAPI app, no guard, binding port 8000 — the port
  `sports_service` uses. Guard it, delete it, or drop the marker if it is wrong.
  Neither v0.7.3 nor v0.7.4 ran this check; it was written after both.
* **Uncommitted: five `backend/test_*.py` files** (reasonix's). Four are fixture
  repairs; one corrects a literal, `target_share` 16.1 → 16.2, which I verified
  independently: Gibbs 2025 is `0.16153` over 17/17 REG games. All sound, still
  awaiting Micah's call on whether they ride as a tag or a plain commit.
* **Those failures were mine, not pre-existing.** `c424c5f` added
  `rush_td`/`rec_td`/`attempts` and the fixtures never created the columns.

Still true and still the biggest lever: **nothing from today is deployed.**
dev 29 passed / 6 red, prod 12 / 22.

---

## 1. The one-line state

| | |
|---|---|
| dev gates | **28 passed / 7 red** (was 12/22 this morning) |
| prod gates | **12 passed / 22 red** — nothing from today is deployed |
| spine | all four leagues **100%** `espn_id` + `team` + `position` on active players |
| prod frontend image | built **2026-08-03 20:50 UTC** — one day stale |

**The single biggest lever is a deploy.** Every fix below is dev-only.

---

## 2. Prod is running yesterday's frontend — the live-pill bug

Micah asked why the live section shows "a bunch of game pills". It is not a data
bug. The deployed bundle `scores-31552fd662d532be.js` still contains

```js
m.map(e=>(... className:"inline-flex ... truncate max-w-[70px]" ...))
```

— one chip per remaining live game — and does **not** contain the string
`more live game`. The collapse landed in `86c8f8e` at 08:38 today; the image was
built 2026-08-03 20:50. **The fix exists and is not deployed.**

The data is correct: 4 ATP + 4 WTA matches were genuinely live (National Bank
Open), `state:"in"` maps to `LIVE` properly, and nothing is falsely marked.

**Next action: rebuild and deploy the frontend.** That alone fixes it.

---

## 3. roster_sync had never once been able to run

`migrate_roster_snapshots.py` existed and had **never been applied to either
database** — the first run died on `missing table roster_snapshots`. That, not
the matching logic, is why `team` was blank league-wide.

Applied to dev. **Prod still needs it** (`--db data/picks.db --apply`).

Then two failure modes still blocked whole leagues, each over ONE player:

* NHL — Connor Ungar (EDM), `duplicate_source_roster_id`, blocked all 32 teams
* MLB — Max Muncy (ATH), `name_match_conflicting_espn_id`, blocked all 30

Fixed in `627a213` with a tolerance floor. Systemic breakage still blocks, on the
two signals that actually indicate it: a team that produced no usable entry, and
an unresolvable share above 2% (real rosters sit at 0.00–0.08%). Under the floor
the odd player is queued for review — inside the apply transaction, so a review
row cannot outlive a rollback — and reported as `unresolved`, never `failures`.

Result, and this closes the `DATA-SPINE.md` MLB/NHL gap:

```
nhl  complete  32/32  matched 973  inserted 78  espn_id +2
mlb  complete  30/30  matched 691  inserted 93  espn_id +153
```

---

## 4. ESPN rate limiting — what is actually true

This tripped twice today. The rule that matters:

**The ceiling is a request COUNT per host, roughly 100 — not a rate.** Measured
at identical 1s spacing:

| host | requests @ 1s | result |
|---|---|---|
| `site.web.api.espn.com` | 128 | clean |
| `sports.core.api.espn.com` | ~119 | 403 |

Both were ~60 requests/minute, so a per-minute rate ceiling explains neither.

**The old note in memory ("slower pacing does not converge — 143 @ 1s, 21 @ 2s,
0 @ 5s") was measured on `sports.core` and must not be carried to other hosts.**
I made exactly that mistake: quoted it at `site.web.api`, concluded throttling
would not help, and was wrong. Micah pushed back and the measurement went his
way. The 1s/2s/5s shape is also anti-monotonic, which is not a pacing curve — it
is successive runs against a host already tripped and cooling.

Proven, not asserted: `fetch_position_vocabulary.py` needs ~140 requests against
`sports.core` — the host that refused. Cold, with the disk cache emptied first,
it now completes all four leagues and writes output **byte-identical** to the run
that had to be resumed by hand.

### What is now in `espn_client.py` (`1c9e77c` + `9484908`)

All three are **opt-in and default off**, because a serving path must not pause
and must not answer from an hours-old payload:

1. `set_min_interval(seconds)` — spacing. Batch callers set 1.0.
2. `set_disk_cache(dir, ttl)` — persistence. `_CACHE` is per-process, so its TTLs
   had **never survived a single run**; every invocation re-paid every request
   for bytes it already had.
3. `_charge_host()` — a per-host budget of 100, then a 60s cooldown. Cache hits
   never charge it, so a resumed run costs nothing.

Plus a retry ladder (5s/30s/120s) on 403/429/5xx. A 403 is temporary: both hosts
refused and were serving again inside ten minutes.

Measured effect on roster_sync: **run 1 = 128 requests / 128s, zero 403s. Run 2 =
0 requests / 2s.**

### The dev→prod question

`docker-compose.yml` bind-mounts `./backend/data:/app/data`, so
`backend/data/espn-cache` is visible inside the prod container. **A dev run and a
prod run on the same night share the cache — the second costs zero requests.**

### There is no bulk roster endpoint

Checked, so nobody re-checks: `statistics/byathlete` carries no team and no
position (1,038 rows vs 1,279 active athletes — it is a stats report); the
`core` athlete lists are `$ref` stubs costing one request each;
`teams?enable=roster` returns 32 teams with no roster attached. **32 requests per
league is the published shape.** Pace it and cache it.

---

## 5. The position vocabulary gate was measuring string length

`C/vocabulary[position]` decided "two ingests are fighting" from code length —
one char coarse, two chars granular, both present = FAIL. That is a proxy for a
semantic property and it is **wrong in three of four leagues**: hockey's
`C/D/G/LW/RW` is one vocabulary; football's `S/G/C/P` sit in the same vocabulary
as `WR/LB/CB`.

ESPN publishes the hierarchy — `/leagues/{league}/positions` gives every position
an `abbreviation`, a `leaf` flag and a `parent`. `fetch_position_vocabulary.py`
reads it once into a **committed** artifact (`data/position-vocabulary.json`, 130
positions across 4 leagues) so the audit runs offline and the list is reviewable
in a diff. With no artifact the gate reports UNVERIFIED rather than falling back
to the guess it replaced.

Real test: a position AND one of its own published descendants both in use.

```
nhl  FAIL -> PASS   C/D/G/LW/RW is one vocabulary; the gate was wrong
mlb  ---- -> FAIL   CF/LF/RF under OF — invisible to a length rule
nba       FAIL      PF under F      (real)
nfl       FAIL      FB under RB     (real)
```

Net reds unchanged at 7; **composition is honest now.** MLB gained the check at
all — `position` had been excluded with the note "MLB positions are 100% NULL",
which stopped being true the moment roster_sync applied for MLB.

---

## 6. The 7 remaining dev reds, and what each needs

| gate | needs |
|---|---|
| `mlb C/vocabulary[position]` | normalize CF/LF/RF → OF (or the reverse) at the ingest |
| `nba C/vocabulary[position]` | one row: PF under F |
| `nfl C/vocabulary[position]` | FB under RB |
| `nhl B/position-content[D]` | **see §7 — the data is published** |
| `mlb B/position-content` | a MANIFEST entry; nobody has declared what MLB positions must record |
| `nba B/position-content` | same |
| `nhl E/qualifier[season]` | genuinely no published qualifier — arguably correct as UNVERIFIED |

---

## 7. NEXT UP: the NHL 5th surfacing gap

`nhl B/position-content[D]` says 500 sampled defenceman logs never record
`blockedShots` or `hits`. **Both are published per game**, verified today on game
`2025030416`:

```
api-web.nhle.com/v1/gamecenter/{gameId}/boxscore
  forwards/defense keys: assists blockedShots faceoffWinningPctg giveaways
                         goals hits pim plusMinus points powerPlayGoals
                         shifts sog takeaways toi
  goalies keys:          saves shotsAgainst goalsAgainst starter toi ...
```

`ingest_nhl_logs.py` reads `player/{id}/game-log`, which publishes none of them —
its `STAT_KEYS` whitelist is 10 keys. The existing code comment already named the
right endpoint and nobody acted on it.

Two wins in one change: it also **removes the flagged derivation** — that file
computes `saves` as `shotsAgainst - goalsAgainst` and explicitly marks it INTERIM,
noting a game can have more than one goalie, which is exactly where a derivation
earns its mistakes. The boxscore publishes `saves` directly.

Cost: one request per game (~1,400 for a season) rather than one per player.
With the 100-per-host budget and the disk cache this is a paced, resumable job.

**This is the fifth surfacing gap today.** Pattern holds: NFL touchdowns, MLB
PA/H/R/RBI, NBA 2026, MLB team/position, now NHL blocks/hits.

---

## 8. Deploy checklist for prod (nothing below is done)

1. `migrate_roster_snapshots.py --db data/picks.db --apply`
2. `migrate_nfl_td_columns.py --db data/picks.db --apply`
3. `roster_sync.py` — costs 0 requests if run the same night as dev (§4)
4. `ingest_nfl_season_stats.py --year 2025`, `ingest_nhl_season_stats.py`,
   `ingest_mlb_counting_stats.py`, `ingest_nba_season_stats.py`
5. Rebuild + deploy the **frontend** — this is what fixes the live pills (§2)
6. Re-run `audit_league_stats.py --db data/picks.db`; expect 28/7, not 12/22

Untouched from the earlier handoff: the MLB identity rebuild is rehearsed green
on a copy of prod with the restore round-trip proven (2,328 → 2,750, matching
prod exactly) but **has never been applied to prod**.

---

## 9. Two corrections I owe the record

* I cited the `sports.core` pacing numbers at `site.web.api` and concluded
  throttling would not help. It does. Cross-host inference, and Micah was right.
* I ran a 128-request per-team fan-out hours after writing down "when pacing does
  not converge, count the requests" — and tripped the wall. The rule was
  available; I did not apply it to the script I was about to run.
