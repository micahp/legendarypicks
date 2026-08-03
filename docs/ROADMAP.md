# Roadmap & bug ledger

Running list. Add to it, don't rewrite it — mark items superseded rather than deleting,
so the reasoning stays readable.

Last updated 2026-07-29.

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

### B8. The player page renders the wrong game-log columns for K and D/ST — **user-reported**
Reported 2026-08-03 as "missing kicker/DEF game logs" and "Brandon Aubrey has 2 games".
**Not a data gap — the data is present and correct and the page renders the wrong columns.**

`pages/player/[id].tsx:191` `NFL_GAMELOG_BANDS` hardcodes four bands — Passing, Rushing,
Receiving, Fantasy. **No Kicking, no Defense.** Line 245 keeps only bands holding a
non-zero value, then `if (!bands.length) return null`. Measured on dev:

| player | returning | displaying |
|---|---|---|
| Aubrey (882, PK) | 17 games, `fg_made 4, fg_att 6, fg_long 41, pat 2/2` | 17 rows of `WK OPP CAR YDS TD FPTS PPR` — **rushing**; 16 rows all dashes, **one** populated (wk 15, 1 carry) |
| Borregales (2217, PK) | 17 games | **no table at all** — zero carries, so no band matches |
| NO D/ST (30116, DEF) | `recent_games: []` | **no Game Log section** — `player_game_logs` has zero DEF rows, ever |

The single populated row is the reported "2 games".

The backend already publishes the right contract — `/api/nfl/draft/player/{id}/game-log`
returns `tabs=[Kicking]` with `fg_made/fg_att/fg_long/pat_made/pat_att` for 882/2217 and
`tabs=[Defense]` with `sacks/interceptions/fumble_rec/safeties/points_allowed` for 30116.
The player page maintains a second, worse copy of the same idea. Two constraints on the
fix: the page renders **three phase tables** (post/regular/pre) that a wholesale swap to
`PlayerGameLog` would delete, and D/ST needs `/api/player/{id}` to read `nfl_dst_stats`
before any band change can matter.

Also surfaced: **`K` is a live second kicker vocabulary.** `players` holds 336 `K` vs 87
`PK`; 10 `K`-labelled players have 2025 logs (Carlson 17, Prater 17, McManus 15) and the
endpoint returns `tabs: []`, `fields: []`, `stats: {}` for every one. Only 3 names appear
under both labels, so it is a split, not duplication.

**Why the suite stayed green: `REG-render` drives the mock-draft overlay, not
`/player/[id]`.** The gate's surface never included the broken page — the same lesson as
[a green gate is a claim about its surface]. Fix ships with a player-page browser gate
asserting each position sees its own stats *and* that at least one row is non-empty (a
row-count-only assertion passes both failures above).

Delegated: `TASK-reasonix-nfl-gamelog-coverage.md`.

**Not in that task, flagged separately: kicker fantasy points are wrong.** Aubrey's wk-15
row reads `fpts 0.6 / fpts_ppr 0.6` for a game with 4 FG and 2 PAT (~16 kicking points) —
the scoring counts his one carry and ignores every kick, while `pk_pts_per_game` (10.6) is
computed correctly elsewhere. The log and the pool disagree about the same player.

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

### M1. D/ST does not exist — **blocking** ✅ **RESOLVED 2026-07-31**
D/ST entity + roster slot: **DONE** (`8234ecb` — SEA D/ST drafts into DEF slot).

D/ST ADP: **ESPN PUBLISHES IT** — all 32 teams carry PPR ranks (234–519) and ownership % (0.5%–98.9%)
in `kona_player_info` view. ESPN keys D/ST with negative IDs (`-16000 - proTeamId`).
Our `ingest_nfl_adp.py` joined on `espn_id` (empty for D/ST) → silent 0/32 match → derived ADP.
**Fix: ingest ESPN's published D/ST PPR ranks instead of deriving.**

*Supersedes ROADMAP B11 and pt.13 finding #6.*

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

## Tasks for Reasonix (v0.7.0 scope — Aug 22 deadline)

### T1. Fix D/ST ADP ingestion — use ESPN published PPR ranks
**Worktree:** `/root/lp-v0613-recut` (branch `recut/v0.6.13`)
**File:** `backend/ingest_nfl_adp.py`
**Problem:** Current code joins on `espn_id` which is empty for D/ST → 0/32 match → derives ADP from fantasy totals.
**Fix:** Join on ESPN's negative D/ST IDs (`-16000 - proTeamId`) to get published PPR ranks.
**Source:** `kona_player_info` view with `limit: 20000` — all 32 D/ST have `draftRanksByRankType.PPR.rank` and `ownership.percentOwned`.
**Gates:**
- `REG-adp-dst` (already RED in repo with expected numbers)
- 32/32 D/ST rows with `adp_ppr` column populated
- Pool endpoint returns D/ST with real ESPN ADP (DEN 234, SEA 239, etc.)

### T2. Expand mock draft pool to full ESPN player universe (11,515 players)
**Worktree:** `/root/lp-v0613-recut` (branch `recut/v0.6.13`)
**Files:** `backend/ingest_nfl_adp.py`, `backend/routers/nfl_mock_draft.py`
**Problem:** Current pool is ~300 players (only drafted/owned). ESPN `kona_player_info` returns 11,515 players including free agents.
**Fix:** 
1. Update `ingest_nfl_adp.py` to fetch with `limit: 20000` (no filter)
2. Store ALL players in `nfl_adp` table (including `percentOwned=0`)
3. Pool endpoint returns full universe; UI filters handle "available" vs "drafted"
**Gates:**
- `nfl_adp` table has ~11,515 rows for 2026
- Pool endpoint `GET /api/nfl/mock-draft/pool?season=2026` returns 11,515 players
- Position breakdown: QB 470, RB 1122, WR 1791, TE 882, K 209, D/ST 32
- Free agents (percentOwned=0) render as "—" in ADP column per honest-data-ui

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

---

## 2026-07-28 (09:1x) — user report from mobile, and why the roadmap "isn't done"

Micah, on a phone, reported: *the original roadmap from yesterday is still not done · player
rankings need relevant stats per position filter · on the draft room I can't click a player
and its overlay doesn't show up.*

### U0. The roadmap **is** largely done — he cannot see it. Branch/tunnel mismatch.

Measured, not inferred:

| tree | branch | vs `dev` | serves | `PlayerDetailOverlay.tsx` |
|---|---|---|---|---|
| `/root/legendarypicks` | `feat/slice-D-mock-draft` | 0 ahead / **9 behind** | `:3096` → `someone-decorative-wearing-produce` | **absent** |
| `/root/lp-team-vocab` | `feat/dst-and-mock-draft` | **55 ahead** / 0 behind | `:3098` → `altered-era-sold-explain` | present |

`feat/slice-D-mock-draft` is the branch the M1–M7 roadmap was *written* on and it has
received no work since. Every fix from pt.11–pt.14 — D/ST roster slot, the clock deadlock,
the camp-tab draft board, the overlay itself — lives only on `feat/dst-and-mock-draft`,
which is **unpushed and unmerged**. The tunnel Micah has been checking cannot show any of it.

**This is a delivery defect, not a build defect.** Per `deliverable-must-be-visible`: local
commits behind a URL nobody is looking at are not shipped. Fix is one of — merge to `dev`
and let `:3096` serve it, or hand him `altered-era-sold-explain`.

### U1. Position-relevant columns — this is **job14**, spec'd and NOT started
`TASK-job14-position-aware-surfaces.md` (untracked). `NflDraftRoom`'s table renders one
universal column set — PPR/g, PPR/team-game, games, ADP — for every value of the position
filter. A QB row and a K row are identical in shape. ESPN's published gamelog contract, which
job14 measured, shares **zero columns** between a QB and a K. Confirms the spec against a real
user; promote it above B14/B15.

### U2. `/mock-draft` has no player overlay at all — new, distinct from the camp tab
`components/MockDraft/DraftRoom.tsx`: **0 references** to `PlayerDetailOverlay`, and no row
`onClick`. The only clicks on a pool row are the draft and queue buttons. The overlay was
built for `NflDraftRoom` (camp tab, 2 references) and never carried across.

So U2 reproduces on **both** branches, for different reasons: on `:3096` the component does
not exist; on `:3098` it exists but was never wired into the mock draft room. Even after U0
is resolved, U2 stays broken. Owned by me (frontend); Hermes is backend-only.

### Dispatch state
`job15` (D/ST published ADP) worktree is **up**: `/root/lp-job15-dst-published-adp`, branch
`feat/job15-dst-published-adp` off `642259a`, backend `:8093` (`/health` 200), frontend
`:3093` (`/mock-draft` 200), `node_modules` symlink intact at 538 packages. Awaiting Micah's
relay — `messages_send` cannot prompt the agent.

### U1/U2 resolved · B17 opened · audit dispatched — same session

- **U2 fixed (`c92e5df`).** `MockDraft/DraftRoom.tsx` now opens `PlayerDetailOverlay` on a
  row tap. The overlay needed no change: `/api/nfl/draft/player/{id}` resolves the same id
  space the mock draft pool emits (7979 Gibbs 200, 30116 SEA D/ST 200). The row's Draft and
  +Q buttons already called `stopPropagation`, so the row handler was the intended design
  and was simply never added. Verified in chromium at 414×896 — real values, 0 console errors.
- **U1 fixed (`4b21d09`).** Columns and sort pills now come from the position filter.
  The board payload already carried `pk_pts_*`/`dst_pts_*` per position, so this was purely
  a rendering gap. Dead columns per filter, before → after: PK 5→0, DEF 5→1 (ADP, real
  absence), QB 1→0. Sort pills narrowed the same way — sorting 32 kickers by Target share
  reordered nothing — while never hiding the sort actually in effect.
  Verified across five filters in chromium, 0 console errors.
- **B17 opened, folded into job15 (`8220707`).** `/api/nfl/draft/player/30116` returns
  `games_played=0 sample=none` while `/api/nfl/draft-board?position=DEF` returns
  `17 full` for the same SEA D/ST — alongside `dst_pts_per_game=9.6`. `player_detail` has
  no D/ST branch and derives presence from `player_game_logs`, which contains no `DEF` rows
  at all (`SELECT DISTINCT position` over the join returns 25 positions, none of them DEF).
  U2 made this user-visible on all 32 defenses, so it is now urgent rather than latent.
- **job15 §3 was self-contradicting** — it ordered the `dst_rank` block deleted and its
  `games_played`/`weeks_played` fields kept; they are one loop (`nfl_mock_draft.py:332-351`).
  Amended in §6a before Hermes started. **The other TASK specs, job9–job14, have not been
  checked for the same defect and several were executed as written.**
- **Codex audit dispatched.** `AUDIT-BRIEF-FOR-CODEX-2026-07-28.md` (`b8002f9`) — the merge,
  the DB, and the six confirmed false-green failures, with runnable repros. Measured DB
  facts included: D/ST `espn_id` set on **0 of 32** rows, `nfl_adp` carries **0** DEF rows.

Gates after all of the above: 13 PASS, `REG-adp-dst` RED on purpose. No regression.

---

## 2026-07-29 — v0.6.13 re-cut and cross-league v1 data plan (CURRENT)

This section records the decisions and work from the two Codex sessions:

- `019fadbf-a05d-72d1-89c0-2de6d1718414` — whole-application readiness,
  other-league review, and backend-data implementation;
- `019fae3b-aa03-7fb0-b99d-9eb41c0253d3` — DEV landing, verification boundary,
  and decision to continue league by league.

Companion evidence:

- `/root/CODEX-V0.6.13-WHOLE-APP-READINESS-AUDIT-2026-07-29.md`
- `/root/CODEX-V0.6.13-OTHER-LEAGUE-DATA-PATH-REVIEW-2026-07-29.md`
- `/root/CODEX-V0.6.13-RECUT-PLAN-2026-07-29.md`
- `docs/V0613-PLAYER-IDENTITY-AND-LEAGUE-STATS.md`

### Decisions locked

1. **Re-cut v0.6.13; do not create v0.6.14 to hide an unworthy tag.**
   The current tag remains provisional and production remains NO-GO until the
   whole-application clone and browser gates pass.
2. **Acceptance is whole-application, not NFL-only.** Production is still on
   v0.6.7, so the re-cut must keep every exposed major surface alive across the
   accumulated release—not merely prove the mock-draft path.
3. **Build and verify the v1 contract, not obsolete v0 fixture assumptions.**
   Each new slice gets purpose-built v1 tests written with the feature, relevant
   regression tests, and production-shaped API/clone evidence where needed.
   An unrelated v0 test failure is not a blocker unless it reproduces against a
   required v1 behavior. Do not spend the schedule modernizing superseded tests.
4. **Proceed league by league in this order: NBA → NHL → NFL.** MLB's production
   identity repair is a separate data-migration gate and does not block building
   the other league slices. DEV already has zero duplicate MLBAM groups.
5. **Code landing, DEV data migration, and production promotion are separate
   states.** A green commit on `dev` does not authorize a live database write,
   tag move, push, service restart, or production deployment.

### Shared v1 backend foundation — **LANDED ON LOCAL `dev`**

Commit `4394bb8` (`fix(data): canonicalize league stats and roster identity`) was
fast-forwarded onto local `dev` on 2026-07-29. Local `dev` is one commit ahead of
`origin/dev`; it has not been pushed. No managed service or live database was
changed.

The landed contract is:

- `players.id` is the durable person identity.
- A source-native ID must resolve to that person before logs or stats are
  written; missing or ambiguous identities queue instead of creating a
  speculative player.
- `player_stats` is a published display table with one row per
  `(player_id, league, season, stat_type)`, not a multi-source raw lake.
- Leader names and links come from the canonical `players` row.
- The shared game-log reader applies `game_type` only to NFL and preserves
  MLB, NBA, NHL, UFC, and World Cup history.
- A roster is not the person index. `roster_snapshots` stores immutable,
  checksummed release metadata; `roster_memberships` stores canonical
  `players.id` membership. A partial or ambiguous refresh preserves the last
  published snapshot.
- Schema changes are explicit, backup-first migrations that refuse dirty data
  rather than guessing winners.

Published owner of each league's display stats:

| League / season | Canonical owner |
|---|---|
| MLB batting/pitching | Statcast |
| NBA through 2023 | hoopR |
| NBA after 2023 | ESPN published regular-season player table |
| NFL | nflverse weekly rollup |
| NHL | NHL API / nhle.com |

Purpose-built and relevant landed-tree verification passed. The verification
rule above supersedes spending time on unrelated v0 test-order, fixture, or
environment failures.

### Architecture boundary — do not force every product through one pipeline

| Product plane | Contract |
|---|---|
| MLB / NBA / NHL / UFC athletes | Shared canonical `players`, logs, stats, props, profiles |
| Teams and schedules | Stored team results/stats/coverage where published; some request-time ESPN adapters |
| World Cup | Partly shared athlete/log spine, currently dormant; preserve and regression-test |
| Esports | Separate event/match identity, result store, streams, and picks; athlete-spine gates do not apply |

An HTTP 200 from a request-time adapter does not prove the durable player joins
or profile history are correct. Live-source and stored-data evidence must remain
separate.

### Current data gates — code can continue, migration cannot

The canonical `player_stats` migration remains blocked by existing data:

| Gate | DEV | Production |
|---|---:|---:|
| display-name disagreements with `players` | 549 | 176 |
| duplicate canonical keys | 703 | 519 |
| duplicate MLBAM-ID groups | 0 | 317 |

There are also legacy invalid stat types and unowned sources in both databases.
Authoritative league refreshes must replace those populations before the
canonical table migration can apply.

The additive roster-snapshot migration passed on a disposable production clone:
backup verified, `quick_check=ok`, one migration record, and protected
`props`/`prop_results`/`prop_games` fingerprints unchanged. This proves the
schema operation; it does not authorize applying it to DEV or production.

A follow-on MLB repair prototype exists only as untracked work in
`/root/lp-v0613-backend-data` plus disposable `/tmp` artifacts. Its rollback
rehearsal changed no live data. It is parked until the migration/promotion phase
and is not part of commit `4394bb8`.

### Active build order

#### 1. NBA v1 slice — **NEXT**

- Publish current regular-season values from ESPN's
  `statistics/byathlete` table; do not recreate them from box scores when ESPN
  already publishes the season line.
- Keep hoopR as the historical owner through 2023 only.
- Resolve ESPN IDs into `players.id`; queue misses and duplicate source IDs.
- Publish a complete NBA roster snapshot before changing current membership.
- Preserve ESPN's explicit game phases: `PRE`, `REG`, `PLAYIN`, and `POST`;
  classify only the NBA Cup Championship as `CUP`, and require
  `completed=true` independently from a post-state status.
- Prove unique leader rows, canonical leader-to-profile links, recent games,
  matchup/projection evidence, and honest null handling.
- Make NBA Team Stats supported from a bounded, proof-backed season population.

2026-07-29 checkpoint:

- ESPN reports 582 regular-season player rows in one batch request. The
  disposable NBA clone first resolved 580; the explicit season-identity
  publisher then backfilled Markelle Fultz (`4066636`), inserted Andersson
  Garcia (`4702431`) as inactive, and enabled a 582/582 atomic
  `espn_site_stats` publication with zero unresolved rows.
- The identity merge rehearsal consolidated 272 split ESPN/hoopR pairs, moved
  264 historical stat rows, and published an idempotent 545-player, 30-team
  roster snapshot. DEV and production were not mutated.
- The guarded phase repair classified 1,017 regular-season games, 6 Play-In
  games, 85 postseason games, and one Cup final, and removed the postponed
  ten-row zero-box-score event on the clone. Logs remain intentionally
  insufficient to derive ESPN's published season table.
- ESPN standings require 30 teams at 82 games and 1,230 regular-season games.
  DEV still has the old 1,227-game population and now fails closed as
  `schedule_not_reconciled`. The clone's standings-backed publisher validated
  all 1,230 summaries and published 2,460 reciprocal result rows plus 2,460
  complete stat rows; NBA Team Stats returns 30 supported teams.
- The focused candidate suite passes 118 backend tests plus the NBA profile
  render test. The clone passes `quick_check`, produces unique leader links and
  regular-season-only history, and preserves byte-identical `props`,
  `prop_results`, and `prop_games`.

#### 2. NHL v1 slice

- Keep NHL API totals as the only season-display owner.
- Remove/rebuild the competing derived NHL population rather than choosing a
  duplicate at read time.
- Publish and verify the canonical NHL roster snapshot.
- Prove leader uniqueness, canonical profile links, durable game history, and
  Team Stats coverage.

#### 3. NFL v1 slice

- Keep nflverse as the canonical weekly/stat and schedule vocabulary.
- Load and expose the pinned 2026 schedule: 272 regular-season games, 32 teams,
  17 played weeks plus one bye per team.
- Finish complete 10-, 12-, and 14-team draft persistence.
- Ingest ESPN's published overall PPR rank and 2026 projected stat lines from
  the existing `kona_player_info` source. Coverage measured on 2026-07-29 was
  299/300 ranks and 283/300 projections, including 32/32 D/ST.
- Compute Legendary Picks PPR totals from the stored published stat line using
  one explicit tested formula; do not label unstable ESPN `appliedTotal` as the
  source and do not fabricate missing projections.
- Restore the intended `RK | PLAYER | BYE | ADP | PROJ | AVAILABLE` contract
  and the `PROJ 2026` player-card row.
- Make NFL Team Stats supported from a bounded, proof-backed season population.

#### 4. Parked MLB production repair and cross-league migration

- Rebuild MLB display stats from Statcast after identity-safe consolidation.
- Rehearse production's 317 duplicate MLBAM groups on a fresh disposable clone.
- Preserve props, re-resolve logs only from stable source keys, queue ambiguity,
  and verify every dependent reference and protected-table fingerprint.
- Apply partial unique native-ID indexes only after all conflicts are clean.
- Run the strict canonical-stat and roster migrations first on fresh clones,
  then on DEV only with explicit authorization.
- Publish one complete current roster snapshot for MLB, NBA, NFL, and NHL.

#### 5. Whole-application gate and tag re-cut

Before moving the v0.6.13 tag:

- every exposed league has unique canonical leaders and correct profile links;
- profiles, Matchups, projections, and recent history use the same
  league-correct log population;
- NBA/NFL/NHL Team Stats are supported and non-empty;
- the 2026 NFL schedule and bye UI work;
- 10/12/14-team drafts persist and reload completely;
- ESPN rank/projection provenance, formula, coverage, and honest nulls pass;
- UFC rankings/history/Predict, dormant World Cup regressions, esports match
  identity/results/streams/picks, props, and game detail pass their own gates;
- a fresh production clone passes backups, migrations, `quick_check`, data
  invariants, protected-table fingerprints, APIs, and the browser matrix.

Only after those gates pass may the existing v0.6.13 tag be re-cut and
production promotion be reconsidered. Production writes and deployment still
require explicit approval.

---

## 2026-07-31 — Fantasy news audit repair (CURRENT local candidate)

Commit `888fb51` repairs the RotoWire fantasy-news slice on local `dev`. It is
not pushed or deployed.

### Closed

- **Cross-player news assignment:** source/player IDs are retained. A persisted
  RotoWire crosswalk wins when present; until then, name is candidate discovery
  only and team + position must resolve exactly one canonical NFL player.
  Carlton Davis no longer leaks into Carl Davis, Marcus Harris resolves to the
  TEN corner rather than all three same-name rows, and suffixes such as Michael
  Penix Jr. resolve correctly.
- **False empty states:** source outage, stale cache, no news, unsupported
  league, and unresolved identity are separate API/UI states. A malformed or
  partial feed cannot replace the last validated snapshot.
- **Ordering and dates:** articles are newest-first before `limit`; date-only
  estimated returns remain on the source calendar day in viewer-local time.
- **Surface parity:** player page and mock-draft overlay use one shared news
  renderer with source attribution and identical error semantics.

### Measured boundary

- Live feed at verification: 172 updates, 157 unique RotoWire players.
- 135/157 resolve uniquely to canonical `players.id`; zero source-player IDs
  collide on one canonical player.
- 22 source players fail closed because the current DB disagrees on team or
  position, or lacks the person. Ten are fantasy positions (1 RB, 5 WR, 4 TE).
  Publishing `player_external_ids(source='rotowire')` can recover these only
  after stable-ID evidence exists; do not weaken matching to hide the gap.
- Gates: 10 focused backend news tests, 13 existing profile API tests, five
  React news tests under `America/Chicago`, public desktop player pages, and
  the 414×896 mock-draft overlay. Browser checks had zero console/page errors.

### Still separate

- The three feature commits ahead of `origin/dev` are `f4e05fb`, `3a5546d`, and
  `888fb51`, plus this context/roadmap documentation commit; no push occurred.
- This closes the local feature defect. It does not satisfy the whole-app
  v0.6.13 re-cut gates above and does not authorize DEV/production data writes,
  a tag move, service restart, or deployment.

---

## 2026-08-01 — Fantasy-news scope correction (supersedes 2026-07-31 surface parity)

Commits `fe1f296` and `9842792` correct the product boundary that `f4e05fb`
and `888fb51` got wrong:

- `/player/[id]` is a general player-detail surface. Its News tab again uses
  ESPN general reporting through `/api/player/{id}/news`; it does not render
  RotoWire fantasy analysis or ESPN's fantasy vertical.
- The mock-draft player overlay is the fantasy context. It alone consumes
  `/api/player/{id}/fantasy-news` and renders RotoWire notes and Fantasy Spin.
- ESPN search results are accepted only when ESPN resolves the query to exactly
  one NFL athlete with the profile's ESPN ID; same-name NFL players fail closed.
- RotoWire identity resolves from a persisted mapping when present, otherwise
  from Sleeper's published ESPN/GSIS-to-RotoWire crosswalk. Team changes do not
  break stable identity: Deebo Samuel resolves to RotoWire `13429` even while
  the local team row still says WSH and RotoWire says SF.
- The 172-update / 157-player league feed is a rolling snapshot, not complete
  player coverage. Public player-specific RotoWire history is merged with it;
  locked subscriber analysis is not copied. A true `no_news` state now requires
  a successfully loaded player history, not mere absence from the rolling feed.

DEV-tunnel evidence: Deebo's standalone page rendered ESPN reporting with no
RotoWire/Fantasy Spin; the in-draft overlay rendered six RotoWire updates,
including history, with no ESPN headline. Patrick Mahomes rendered five history
updates despite not relying on a current rolling-feed match. Both browser checks
had zero console/page errors. The focused gates pass 27 backend tests and five
React tests. This remains local/un-pushed and does not authorize production
deployment.

---

## 2026-08-01 — NFL player UI and news interaction completion

Commits `99553fb`, `1e48461`, and `9895508` close the remaining interaction and player-UI
requirements on the local DEV candidate:

- RotoWire fantasy-news cards in the mock-draft overlay are display-only. They
  expose no outbound links; the standalone ESPN general-news cards remain
  linked.
- Fantasy analysis follows the saved Gibbs reference as plain editorial copy:
  notes, then inline bold `SPIN:`, then date and source. The former nested green
  Fantasy Spin panel is removed.
- NFL pool rows render compact injury designations, and both the mock-draft
  detail overlay and standalone NFL player profile render the full designation.
  `ACTIVE` and null states do not produce warning tags; the stored
  `INJURY_RESERV` value is normalized to Injured reserve / IR.
- The four position-aware season metrics are one dark card with a full-width
  orange season header and four evenly divided value/rank columns, following
  the Joe Burrow ESPN reference saved from the Hermes Discord session.
- The season card is confined to Overview. The redundant
  `RB2 by ADP — not our ranking` sentence is removed, while the compact RB2
  badge remains.
- The player-profile contract now consumes `regular_season_games`, eliminating
  the rendered `undefined games` value.
- General ESPN results require the verified NFL athlete plus complete-name
  evidence in NFL article metadata. This preserves Deebo Samuel reporting while
  rejecting unrelated broad-name results such as Luke Fortner receiving darts
  or baseball headlines.
- The mock-draft pool API now enforces the supported position vocabulary:
  `QB`, `RB`, `WR`, `TE`, `PK`, and `DEF`. The measured DEV/public-tunnel
  population is 4,507 rows across exactly those six values; `TQB` and every
  IDP/coach/punter/lineman/blank value measure zero. The larger ESPN universe
  remains an ingest/source population, not a user-facing fantasy pool.

Evidence: 52 focused backend tests passed; eight Jest suites / 76 tests passed;
changed-file TypeScript diagnostics were empty; public mobile profile, pool,
detail overlay, general-news, and fantasy-news checks had zero console/page
errors. The fantasy overlay contained zero links, while Deebo's standalone ESPN
headline remained linked. This candidate is served by the managed DEV tunnel,
remains unpushed, and is not production.

### Correction: separate NFL league-page rankings pool

Commit `09fc934` closes a missed third pool surface. The `/leagues/nfl` Player
Rankings table is backed by `/api/nfl/draft-board`, not the mock-draft pool API.
It now:

- returns and renders the same compact NFL injury tags;
- restricts unfiltered and filtered results to `QB`, `RB`, `WR`, `TE`, `PK`,
  and `DEF`;
- removes `TQB` and unsupported-position pills; and
- rejects `position=TQB` instead of treating it as a valid board filter.

Fresh public-tunnel verification measured 772 eligible players across only the
six supported positions, zero `TQB` search results, and a rendered red `Q` tag
for Jahmyr Gibbs in the exact league-page Player Rankings table. The focused
backend suites passed 71 tests, the shared injury-tag suite passed three tests,
and the browser check had zero console/page errors. This correction is live on
managed DEV through auto-reload, remains unpushed, and is not production.
