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

**Open, not yet decided:**
- **Version numbers.** Suggested: A = **v0.7.0**, D = **v0.8.0**, accounts + subscription +
  multiplayer = **v0.9.0**. This shifts what this file previously called v0.8.0. Confirm
  before the first `scripts/release.sh` run.
- **Where R4 (NFL schedule through the API) goes.** It was the third item in the old single
  cut and Micah's new sequence does not mention it. It is unblocked (B2/B3 resolved) and
  currently homeless — attach it to A or D, or ship it separately.

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
