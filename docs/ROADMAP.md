# Roadmap & bug ledger

Running list. Add to it, don't rewrite it — mark items superseded rather than deleting,
so the reasoning stays readable.

Last updated 2026-07-27.

---

## User evidence — 2026-07-26

First conversation with a potential user, and the first outside signal this roadmap has.

- Pitching **"the app" in general was hard. Pitching NFL was easy.** The framing problem is
  a scope problem.
- **She had no place she went to do draft research.** Not "she prefers a competitor" — no
  incumbent at all. That vacancy is what the board fills.
- **The v0.6.9 availability UX landed on a first-time viewer**: she could scan and see who
  misses games. Accent-marks-absence did its job on someone who'd never had it explained.

**Consequence: R6 moves up.** It was scheduled after v0.7.0, decided before anyone was
asking for the board. She cannot reach it — prod is v0.6.7 and the board is dev-only behind
a trycloudflare URL. Everything else on this list is an improvement to something no user
can open. See R7, R8.

---

## SUPERSEDED 2026-07-27 (later) — see "Build order" below

> **The single-cut plan below was replaced by Micah the same day.** A and D now ship as
> **two separate tagged releases**, and the prod deploy follows both. The scope of A and D
> themselves is unchanged — only the packaging and sequence. Read the next section first;
> everything under this heading is kept for the reasoning, not the plan.

## Build order — set 2026-07-27 (current)

1. **Push `feat/nfl-allday`** once Hermes' alias table lands.
2. **Slice A** — draft notes to the server, keyed by `device_id`. → **tag a release.**
3. **Slice D** — single-player mock draft vs ADP bots. → **tag a release.**
4. **Prod deploy (R6).**
5. **Data subscription**, which **coincides with accounts (slice B)** — the same auth build
   supplies billing identity, the sign-up gate, *and* **multiplayer mock drafts**.

Why the split: A and D are each a real feature, so each earns its own tag under the
feature-releases-only rule, and A reaching prod does not have to wait on D being finished.

**~~Open, not yet decided:~~ — neither of these was ever open. Corrected 2026-07-27.**

- ~~Version numbers.~~ **Already decided, and written in two places**: `SPEC-accounts-and-
  mock-draft.md` §6 ("v0.7.0 = A + D single-player + the NFL schedule API, then a prod
  deploy. v0.8.0 = B + C + multiplayer") and this file's own v0.7.0 section. **A and D both
  ship v0.7.0; B and C are v0.8.0.** The renumbering floated above (D = v0.8.0, accounts =
  v0.9.0) contradicted a decision Micah had already stated repeatedly — do not re-open it.
- ~~Where R4 goes.~~ **R4 is the third item of v0.7.0**, per the same section. Not homeless.

The two-tag split still stands for *packaging*: A can be tagged and deployed without waiting
on D. What it does not do is change what v0.8.0 means.

Sequencing note: this puts the **acquisition surface** (mock draft) in front of users before
the **monetisation** (subscription), which is what `POSITIONING-2026-07-27.md` §6 and §10
argue for — the subscription needs accounts anyway, and accounts are what make multiplayer
possible, so one auth build pays for all three.

---

## v0.7.0 — scope locked 2026-07-27 (SUPERSEDED as one cut — see above)

Cut as one release, then **deploy to prod (R6)**. Three things:

1. **Slice A** — draft notes to the server, keyed by `device_id`
   (`SPEC-accounts-and-mock-draft.md` §6). Closes R8.
2. **Slice D, single-player** — mock draft vs. ADP bots. 12×15 snake, QB/RB/WR/TE/K + FLEX,
   no D/ST, no IDP.
3. **NFL schedule 2026 through the API** — R4. Nothing loaded on 2026-07-27 is visible in
   the UI today.

v0.6.10 (draft board search) already shipped ahead of this and is not part of it.

### Two things this scope does not resolve

- **DECIDED 2026-07-27: the mock draft ships UNGATED in v0.7.0.** Accounts (slice B) ship
  with **multiplayer** mock draft as **v0.8.0**, and the sign-up gate arrives with them.
  This gets a single-player draft in front of people inside the draft window and measures
  whether anyone finishes one before we make it cost something.
- ~~R4 depends on the B2/B3 key-scheme decision~~ — **B2/B3 DECIDED 2026-07-27, see below.**
  nflverse stays canonical and 2025 gets migrated. R4 is unblocked.

### Calendar
Drafts run mid-Aug → **Labor Day, Sept 5–7**; week 1 opens **Sept 9**. v0.7.0 has to be in
prod by roughly **Aug 22** for the mock draft to matter this season.

---

## Now — v0.7.0 (detail)

### R7. Player search on the draft board — **user-blocking**
522 eligible players, 50 per page, and the only controls are a position filter, a sort, and
prev/next. Draft research is name-driven — "what about Rashee Rice" — and today that means
paging. A search input over the board is the smallest change that makes it usable for the
thing she described doing.

### R9. Accounts, with the mock draft as the reason to make one
Spec written 2026-07-27: **`docs/SPEC-accounts-and-mock-draft.md`**. Gate a mock draft behind
sign-up; nudge at the moments someone is already investing effort. Supersedes R8's "label it
and move on" option — R8 becomes slice A of the spec.

**Both decisions made 2026-07-27, nothing is blocked**: v1 is **solo vs. ADP bots** (an empty
lobby converts nobody, and realtime does not fit before Labor Day), drafting a **12×15 snake,
QB/RB/WR/TE/K + FLEX, no D/ST, no IDP** (**we have no D/ST entity at all**, and only 248
players carry a real ADP against 180 picks). Nudges follow the action, they do not block it.

**The calendar decides the scope**: drafts run mid-Aug → Labor Day (Sept 5–7). Anything that
cannot land by ~Aug 22 is a 2027 feature.

### R8. Decide what happens to a user's draft notes — **folded into R9**
`rank` / `watch` / `fade` persist to `localStorage` under `lp_nfl_draft_notes`. Device-local:
gone on a cache clear, invisible between phone and laptop. Doing the research *is* the
retention hook, so this is the wrong storage for it long-term. Two options — label it
honestly as this-device-only for now, or move it behind an account. **Needs Micah's call;**
the account path is much larger than the label.

### R1. Rebuild `/api/nfl/draft-board` around availability
**The board already exists** (`routers/nfl_offseason.py`, contract `nfl-draft-board-v1`,
511 eligible players). It ranks by `fantasy_ppr_g` — points per *game played* — which is an
average conditioned on the player being healthy enough to play, i.e. the exact thing you
were trying to predict. It also ships `season_proj_pts = projection * games_assumed`, so it
already calls itself a projection, and `games_assumed` — the availability variable — is
computed internally and never surfaced.

What availability actually is, per Micah: **injuries, suspensions, and legal absences.** The
board's job is to help someone draft accounting for those *and* for snap share. Not a
statistics exercise — a "will this guy be on the field" exercise.

- Surface availability as the headline, not an intermediate.
- Show both numbers: PPR when played, PPR per team game.
- Season strips with visible gaps for missed games; accent colour reserved for absence.
- Stop labelling it a projection.
- Fold in snap share (`off_pct`) — a healthy player in a timeshare is a different risk from
  an injured starter, and the board must distinguish them.
- Scope: QB/RB/WR/TE. See R5 before assuming IDP/K.

### R2. 2024 in the UI without availability
2024 data can render immediately; it does **not** need the availability calculation to be
useful. Don't block the 2024 display on R1.

---

## Bugs caught, not yet fixed

### B1. Mid-season team change doubles the availability denominator
Joe Flacco reads `13/34` for 2025 because he changed teams and the denominator sums both
teams' full seasons. Denominator must be scoped to team games *while the player was on that
team*, or counted as distinct team-games in the season. Found while prototyping the
availability query — this would have shipped a visibly wrong number.

### B2. `team_game_results` has two incompatible key schemes
2025 rows use **ESPN event ids** (`401772718`); 2024 and 2026 rows use **nflverse ids**
(`2026_01_NE_SEA`). Consequences:
- 2025 rows do not join to `nfl_schedule` at all.
- Loading 2025 from `games.csv` naively would add 544 duplicate rows under the second
  scheme, giving 544 distinct game_ids each with 2 rows — **every 2025 game double-counted,
  breaking the team-stats aggregate** (34 games per team instead of 17). Do not do this
  without deduplicating first.

**RESOLVED 2026-07-27 — neither option was necessary. nflverse publishes the ESPN id.**

`games.csv` carries an `espn` column and it is populated for **285/285 of 2025's games**
(verified against the live file; our `nfl_schedule` already stores it, 285/285 for 2024).
The bridge between the two key schemes did not need to be built or repulled — we were
already ingesting it. See [[feedback_check_if_the_value_is_published]]; this is the fourth
time that check has paid off on this table.

Measured, with `league='nfl'` applied:

| season | `team_game_results` keys | rows | joins `nfl_schedule`? |
|---|---|---|---|
| 2024 | nflverse | 570 | **285/285** |
| 2025 | **ESPN** | 544 | no — `nfl_schedule` has no 2025 rows at all |
| 2026 | nflverse | 544 | yes |

**Only 2025 is broken — 544 rows, one season.** (An earlier read that 2026 was ESPN-keyed
was wrong: those numeric ids belong to other leagues. Always apply `league='nfl'`.)

**Decision: nflverse stays canonical; migrate 2025.** `player_game_logs` is nflverse
(11,232 rows), the draft board is nflverse, `nfl_schedule` is nflverse. ESPN is only the
roster/ADP side. Going ESPN-canonical would move the schedule to the opposite side of the
divide from every player number we compute, to avoid re-keying 544 rows.

Three steps, no repull, nothing lost:
1. Load 2025 into `nfl_schedule` from `games.csv` — zero rows there today, so no duplication
   risk. Brings 2025 rest days, roof/surface, spread/total lines, coaches and starting QBs,
   which we do not currently have, plus the `espn` bridge column.
2. **UPDATE** (never INSERT) the 544 `team_game_results` 2025 rows' `game_id` from the ESPN
   id to the nflverse one through that bridge. B2's "544 duplicate rows" trap is an INSERT
   failure mode and does not apply to an UPDATE.
3. The same statement closes **B3**: `LAR→LA`, `WSH→WAS`, using the `ESPN_ALIASES` map that
   already exists in `ingest_nfl_schedule.py`. Confirmed 2025 is the only season using the
   ESPN codes.

Two things found while measuring, neither blocking:
- 2025 holds **regular season only** (272 games); 2024 holds regular + postseason (285).
  Pre-existing inconsistency.
- **2026 carries no ESPN ids yet** — nflverse publishes them closer to gameday, like the
  betting lines in R3. Harmless here since 2026 is already nflverse-keyed, but it matters if
  live scores ever need a 2026 → ESPN mapping.

### B3. Team abbreviations disagree between tables
ESPN says `LAR`/`WSH`; nflverse says `LA`/`WAS`. `player_game_logs` is nflverse,
2025 `team_game_results` is ESPN. **The Rams and Washington already fail to join between
those tables.** Recorded as `ESPN_ALIASES` in `ingest_nfl_schedule.py`. Same decision as B2.

### B4. Three draft-board tests are red for a fixture gap
`test_nfl_offseason_api` × 3 all fail with `sqlite3.OperationalError: no such table:
nfl_adp` — the fixture DB lacks the table. Not a product bug, but they've been red long
enough that nobody reads them. Fix with R1.

### B7. `players.nfl_gsis_id` mixes two id schemes
**651 active NFL players carry an ESPN-style synthetic key** (`LOV121782`,
`TAT143045`) in a column named for gsis. A real gsis is `00-0041027`. Exactly **0**
of the 651 have game logs — they are the players nflverse has never seen through
our ingests, which is to say the rookies and no-signal players the draft board most
needs to say something about. Jeremiyah Love (ADP 17.5, 98% owned) joined to
nothing until this was found.

The pollution originates **upstream**: nflverse's own depth chart carries the same
synthetic keys for players without a gsis yet (e.g. Drew Allar → `ALL015451`), and
our spine was evidently populated from that feed.

`ingest_nfl_depth_charts.py` works around it by falling back to `espn_id`, which
resolves 914/914 rows. That is a workaround in one script, not a repair — every
other nflverse join still silently misses these players.

**Repair available and measured:** `espn_id` bridges 619 of the 651 to a real gsis
in the 2026 depth chart artifact. 26 more have only a synthetic key upstream too
(genuinely no gsis yet — never played a snap); 6 are absent from the artifact. Name
agreement across the bridge is exact but for 6 generational suffixes (`Murvin Kenion`
vs `Murvin Kenion III`), all the same player. Backfilling mutates the identity
spine, so it wants its own change and its own review rather than riding along with
a board feature.

### B5. `test_league_stats_contract` failing
`test_mlb_never_queries_game_logs_and_always_has_no_comparison`. Pre-existing, uninvestigated.

### B6. The 16-row NFL cleanup is not reproducible
The cleanup of 14 rows in 2024 (`source='nflverse'`) and 2 in 2025 (`source='nflverse_pbp'`)
was a one-off manual SQL operation with no script behind it. Documented in
`NFL-DATA-INVENTORY.md`, not repeatable. Confirm `migrate_nfl_stats_to_prod.py` copies dev
rows wholesale — if so the cleaned rows come along and nothing more is needed. **Check
before the prod deploy, not after.**

---

## Mock draft v1 — the gaps, set 2026-07-27 (pt.10)

Slice D is merged and tagged in v0.6.11. **Micah's verdict: it is a proof of concept, not
shippable.** Full detail and evidence in `/root/CONTEXT-2026-07-27-HANDOFF-10.md`.

### M1. D/ST does not exist — **blocking**
No entity, no ADP, no roster slot. A 15-round roster with no defense is not a fantasy roster.
Smaller than it sounds: every stat D/ST scoring needs is **published** at
`nflverse-data/releases/download/stats_team/stats_team_week_2025.parquet` (570 rows, verified
200) — `def_sacks`, `def_interceptions`, `def_tds`, `def_safeties`, `fumble_recovery_opp`,
`special_teams_tds`, `pt_return_tds`. Points allowed is already in
`team_game_results.score_against`. **No pbp reconstruction** (`nfl_pbp` has 7 usable columns
and none are sack/interception/fumble). What is missing is (a) 32 team-defense entities and
(b) D/ST ADP — `nfl_adp` has zero. ⚠️ **Check what ESPN publishes as the position code before
inventing one** — see B9.

### M2. Availability is computed from a table that cannot express it — **blocking**
`player_game_logs` only holds players who recorded a passing/rushing/receiving stat, so anyone
who played without touching the ball reads as absent. 2025 actives with logs: WR 196/391,
RB 120/192 — but LB 2/385, CB 0/333, DT 1/272, **PK 1/42**. Fix: **`nfl_snap_counts` as its own
table**, all positions, all weeks; availability reads that. **Do not rewrite
`player_game_logs`** — decided against 2026-07-27. `ingest_nfl_snap_counts.py:16,101` already
downloads the file and discards every non-skill presence row.

### M3. Familiar UX — six missing objects
Position/team/bye filters · queue · draft-board grid (teams x rounds) · "your next pick"
counter · Draft button on the row (today the whole `<tr>` is the click target) · clock.
⛔ **Familiar structure does not override SPEC-slice-D §6.2** — amber marks absence and may not
be borrowed for turn/pick/run highlighting. Incumbents colour-code grid cells by position;
ours uses position chips and two-tone fills.

### M4. Resume and share are both dead
`pages/mock-draft.tsx:70-79` fetches the draft then discards the response, and returns early
on `status === 'complete'`. Separately `GET /api/nfl/mock-draft/{id}` is device-scoped
(`nfl_mock_draft.py:355`), so a shared link could never resolve for a recipient. Resume is
~30 lines client-side. Share needs a public read for completed drafts (precedent:
`nfl_mock_draft.py:133`) **or** accounts per R9 — product call. The results screen now shows a
disabled "Get a link / Coming soon" instead of a dead URL.

### M5. Player detail overlay
Click the row for projections, last season's game log, injury status — **and the WR's QB**.
The row shows a team code and nothing else; who throws to him is the actual draft question.

### M6. Camp card becomes the resume state
Once a draft is in progress, the `/leagues/nfl` entry card should read "Resume your mock draft
— Round 4, pick 41" instead of the start pitch. Blocked on M4.

### M7. Room polish
`DraftRoom.tsx:111` hides the scrollbar on a 292-row list inside a fixed-height container on a
page that does not scroll — it looks like the pool has 10 players. Roster panel spends 7 of 15
rows on empty bench slots. `:255` hardcodes `TEAM_GAMES - games_played` instead of the API's
`games_missed` (will break under B1).

---

## Mock draft v1 — scored 2026-07-28 (pt.14)

Branch `feat/dst-and-mock-draft`, 55 ahead / 0 behind `dev`. Nothing merged, nothing pushed.
**State of the work is one command**, not this table:

```bash
bash /root/lp-team-vocab/verify-gates.sh all      # 14 gates; LP_GATE_W/B/F to retarget
```

The gate suite is the scoreboard. Where this document and a gate disagree, the gate wins.

| item | pt.13 | now | how it was checked |
|---|---|---|---|
| M1 D/ST | UI renders it | **UI renders it + has a starting roster slot** (`8234ecb`) | browser: drafting SEA D/ST lands in DEF, not the bench |
| M2 availability from snaps | done | done | A1/A2 |
| M3 six objects | 6/6 committed, **never tested** | 6/6 **and the tests actually ran** — 36/36 | jest was SIGBUS-dead 01:54→08:00 |
| M4 resume/share | scratched | scratched (Micah, 2026-07-28) | — |
| M5 overlay | built | built | B2 |
| M6 camp card | blocked on M4 | out | — |
| M7 polish | B4 green | scrollbar ✓, bench 7→6 ✓, **`TEAM_GAMES` still hardcoded** | see B14 |
| B8/B9/B10 | fixed | fixed | A1b / B1 / A1+A2 |

**The mock draft has now been opened in a browser** — for the first time. It works: pool,
filters, queue, board grid, ledger, roster, results screen, zero console errors.

### B11. D/ST ADP is published; we derived it instead — **open, delegated (job15)**
`nfl_mock_draft.py:314` says *"D/ST — no published ADP exists. Derive ranking from fantasy
totals."* **Measured 2026-07-28: false.** All 32 carry a published ADP in the payload
`ingest_nfl_adp.py` already downloads (DEN 89.94, HOU 91.81, LAR 98.19, SEA 106.50). ESPN keys
D/ST with **negative** ids (`-16000 - proTeamId`) and all 32 `players.espn_id` are empty, so the
join matched **0 of 32** — a silent miss, papered over with a derivation. The derivation also
disagrees with the published order: it ranks SEA #1, ESPN ranks DEN #1 and SEA 4th.
**This retires M1's "(b) D/ST ADP" gap and voids pt.13 finding #6** — the choice between pool
index 150 and 268 was a choice between two fabrications. Spec:
`TASK-job15-dst-published-adp.md`. Gate `REG-adp-dst` is committed **RED** with the expected
numbers written before the code (`b8cc4b1`).

### B12. The camp-tab draft board was never wired to its hook — **FIXED `77de2f1`**
`/leagues/nfl?tab=camp` rendered "Draft board unavailable." `NflDraftRoom` is presentational
and takes `data`/`loading`/`error`/…, but the page rendered `<NflDraftRoom enabled={…} />` and
**`useNflDraftBoard` was never called**. Filed in pt.13 as a cosmetic `TS2322`; it was the bug.
`next.config.js:9` sets `typescript: { ignoreBuildErrors: true }`, so the only signal that
would have caught it is configured off. **Corrects pt.13 §4 item 3:** the `TS2802` errors
cannot break a production build for the same reason — and the identical error already exists
pre-branch at `pages/scores.tsx:305`.

### B13. The draft clock was a deadlock, not a decoration — **FIXED `1a46101`**
The 30s countdown reached 0:00 and stopped; nothing picked. Measured: the draft sat on pick 6
indefinitely, so anyone who stepped away had a dead page. `autopick()` already existed in the
engine documenting this exact caller. Now picks from the queue first, else best-available with
zero jitter, recorded `auto: true`. Two ordering traps found only by watching a real draft:
`userTurn` does not change between consecutive user turns (one timeout cascaded through all 180
picks — a full draft in 40s), and a stale `seconds` on the turn-change render fired twice and
silently skipped the back-to-back snake pick.

### B14. `team_games` is absent from the mock-draft pool payload — **open, small**
`DraftRoom.tsx` falls back to hardcoded `TEAM_GAMES = 17`. The payload has no `team_games`
(`TS2339`) — but it **does** carry `team_weeks`, so this is a rename, not missing data: use
`team_weeks.length`. B4 passes anyway because it greps for `"TEAM_GAMES - "` and the code is
`/{TEAM_GAMES}` — **the gate's pattern is narrower than its claim.** This is M7's third bullet.

### B15. `adp: p.adp ?? 999` fabricates an ADP in the UI — **open, small**
`pages/mock-draft.tsx:107` coerces the API's honest `null` into `999`, which renders as
`999.0` on D/ST rows. The null-renders-as-"—" fix in `74b34fd` is dead code because null never
reaches it. Banned by `honest-data-ui`. Resolves itself once B11 lands a real ADP, but the
coercion should go regardless.

### B16. Two jest suites fail and no gate covers them — **open**
`components/Game/WCContext.test.tsx` — 2 failures in WC live-context polling. Pre-existing (the
import graph is disjoint from MockDraft) and invisible for two reasons at once: jest has been
dead since 01:54, **and** `REG-jest` only runs `--testPathPattern='lib/mockDraft'`.

### The gate gap that outranks all of the above
Eight gates were green while the pool table crashed on first render. Every one was true; none
of them rendered React. `REG-render` — a Playwright smoke gate that loads `/mock-draft` and
`/leagues/nfl?tab=camp` and fails on any console or page error — is the highest-value
un-started item on this list. Both bugs above (B12, B13) were found by hand-driving a browser,
which is exactly the thing no gate does.

---

## Bugs caught 2026-07-27 (pt.10)

### B8. Kicker game data does not exist; Brandon Aubrey renders a false figure
One row across all 42 active kickers, and it exists because Aubrey **ran the ball once on a
fake** (`{"carries": 1, "rush_yds": 6}`). He renders `1/17 — missed 16`, which is wrong. The
`sample === 'none'` guard that would show "Kicker games not tracked" is bypassed because one
row makes him `'thin'`. **Micah's call: do not relabel him — ingest kicking data.** Answers
the K half of R5. Listed under Known gaps in the v0.6.11 changelog.

### B9. `players.position` has the same two-vocabulary split as `players.team`
`PK` (42 rows, **all active**, all with espn_id) is ESPN's placekicker code — confirmed from
the live roster endpoint; the punter is plain `P`. `K` holds 336 rows, **0 active**. So
`position='K' AND active=1` silently returns nothing. Same for `OLB`/`FS`/`NT`/`ILB`/`MLB`/
`SAF`/`OL`. `backend/team_codes.py` (still unwritten) should grow a `positions` sibling.

### B10. Playoff rows in `player_game_logs` are unmarked
Weeks 19-22 sit alongside regular-season rows with no flag. They drop out of `games_played`
only because they do not intersect `team_weeks` — there is no explicit filter, so the
correctness is incidental. Anything counting rows directly gets 20 games for Stafford.

---

## Next

### R3. Snapshot betting lines and ADP daily
Two datasets that only become useful as a series:
- `nfl_schedule` has spread/total/moneylines for only **51 of 272** 2026 games (weeks 1–3
  plus 3 games in week 4) — books post the near slate only, and it fills in over time.
- `nfl_adp` is a single snapshot, so actual draft timing is still an assumption.

Snapshot both daily and draft timing becomes measurable in ~2 weeks, before the Labor Day
peak (Sept 5–7). Week 1 opens **2026-09-09**.

### R4. Expose `nfl_schedule` through the API
The table has **zero API exposure** — `/api/nfl/schedule-week[s]` call `espn.nfl_schedule_weeks`
live and never read it. So nothing loaded on 2026-07-27 is visible in the UI. Needed for
week-1 matchup context, rest days, roof/surface, and the weeks 1–3 lines. Depends on the
B2/B3 decision.

### R5. Decide `--all-positions` for IDP and kickers — **needs Micah's call**
`ingest_nfl_weekly_stats.py --all-positions` has never been run. The DB holds only offensive
skill positions in real volume (WR 4,489 / RB 2,804 / TE 2,317 / QB 1,389 / FB 161); the tail
(P 20, OT 15, S 14, CB 6, LB 4, PK 1, K 1) is linemen who caught a touchdown, not IDP
coverage. The 2025 artifact has **~19,400 player-weeks against our 5,635**, so ~13,800
defensive and kicking rows exist upstream. If IDP/K leagues are in scope this ingest run is
a prerequisite, not a UI change.

### R6. Deploy to prod — **after v0.7.0**, per Micah
Prod is on v0.6.7 serving pre-swap NFL numbers, no 2025 postseason, no 2026 schedule.
Needs `migrate_nfl_stats_to_prod.py` plus the `nfl_schedule` table, which does not exist in
prod. Blocked on B6 and R1.

---

## Ops

### O1. Reduce to two servers — **DONE 2026-07-27**
Four were running; we wanted **prod and dev**. Two of the four turned out to be zombies:
`/root/lp-ufc-fight-stats` had been **deleted from disk** while its servers kept running out
of the deleted directory (`readlink /proc/PID/cwd` → `(deleted)`). `:3095` was serving 500.

| port | pid | what | outcome |
|---|---|---|---|
| 8095 | 3916288 | uvicorn, cwd `/root/lp-ufc-fight-stats/backend` **(deleted)** | killed |
| 3095 | 3907514 | next dev, cwd `/root/lp-ufc-fight-stats` **(deleted)**, 500 | killed |
| 8096 | 3878741 | uvicorn, cwd `/root/legendarypicks/backend`, absolute `LP_DB_PATH` | **kept — dev backend** |
| 3096 | 160173  | next dev, cwd `/root/legendarypicks` | **kept — dev frontend** |

`:8000` (`--host 0.0.0.0`) is prod and was never in scope.

**Lesson:** a port table is not evidence of which checkout a server belongs to. Check
`/proc/PID/cwd` for `(deleted)` before treating a listening port as a real environment.

### O2. Tunnel — **NOT A BUG, closed 2026-07-27**
The premise ("points at the wrong frontend") was wrong. `:3096` is the *correct* frontend:
its proxy target comes from `.env.local` (`API_PROXY_TARGET=http://localhost:8096`), not the
process environment, which is why `/proc/PID/environ` showed nothing. `next.config.js` logs
the resolved target at startup — grep the dev log for `[next.config.js] API proxy target:`
instead of inferring it.

`https://someone-decorative-wearing-produce.trycloudflare.com` (pid 3928058, up since 07-23)
returns 200 with real app content and a working `/api/*` proxy. **Deliberately not
refreshed** — restarting would mint a new URL and break a working one. Micah was most likely
holding the dead `cf3095` URL from 07-14.

Note: a fresh trycloudflare URL returns NXDOMAIN *from this box* but is live externally —
verify with a pinned IP, don't restart cloudflared on that signal alone.

### O3. `:8096` CPU — **still open, and no longer moot**
67% CPU is uvicorn's `--reload` supervisor stat()ing 5,861 files 4×/sec, 5,733 of them in
`venv/`. `watchfiles==0.24.0` installed. Restart script written, **never run**. O1 did *not*
make this moot — `:8096` is the survivor, so this is now the dev backend burning the CPU.
`--reload-exclude` must be an **absolute** path; relative patterns silently exclude nothing.
