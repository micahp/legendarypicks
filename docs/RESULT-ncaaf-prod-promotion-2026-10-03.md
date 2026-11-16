# NCAAF PROD promotion result — 2026-10-03

The NCAAF fixture-folding and CFBD-first settlement repair was promoted to
PROD as release `v0.9.7` (`e237ee9`). The release was cut from the isolated
`release/v0.9.7` branch directly atop `v0.9.6`, excluding unrelated work on
`dev`. Only the release script pushed to origin.

## PROD database work

Before any write, an online SQLite backup was created at:

`backend/data/picks.db.pre-ncaaf-fold-20261003T184408Z.bak`

The source and backup both passed `PRAGMA quick_check`. The fold was rehearsed
on a disposable clone, where every planned action was inspected. The clone and
live runs had no `REFUSE` lines and no result-bearing loser rows.

The PROD apply:

- folded 2,198 props onto canonical linked fixtures;
- linked 76 props to verified ESPN events;
- left 100 current-slate props on three fixtures for the scheduled linker;
- reduced `prop_games` from 2,413 to 2,324;
- preserved all 283,844 existing result rows at fold time; and
- left zero orphan props.

The repeated post-apply dry run reported zero remaining `FOLD` or `LINK`
actions. PROD still returned `ok` from `PRAGMA quick_check`.

## First PROD settlement work

The measured stale NCAAF backlog began at 4,952 unsettled props. The first
managed settlement pass reached NCAAF but was stopped by the existing parent
service's one-hour timeout before printing a summary. Its durable rows recorded
1,632 settlements. One explicitly paced continuation, limited to the untouched
range through 2026-09-05, settled another 184 props without changing systemd
units or retrying ESPN in a loop.

Combined result:

| Outcome | Props |
|---|---:|
| Settled directly from the CFBD line | 1,798 |
| Settled through the bounded ESPN fallback | 18 |
| Total settled | 1,816 |
| Remaining stale backlog | 3,136 |

The remaining stale population reconciled as follows:

| Remaining state | Props |
|---|---:|
| Pending with durable reason | 2,642 |
| Known intermittent ESPN HTTP 403 | 66 |
| Linked but not reached by the interrupted managed pass | 374 |
| Still unlinked and old enough for the six-hour query | 54 |
| Total | 3,136 |

`settlement_attempts` contained 4,810 state-change rows for 4,524 distinct
props. Pending prop 872565 was spot-checked and had exactly one attempt row,
with reason `no_cfbd_row+athlete_absent_from_boxscore`.

The 374 unattempted linked props were deliberately left for ordinary scheduled
passes. The 66 errors were all the already-known intermittent ESPN 403 class;
there was no mass or contradictory settlement failure.

## Final verification

- PROD held 401,304 props, 285,660 results, and 2,324 prop games.
- `PRAGMA quick_check` returned `ok` and orphan props remained zero.
- The backend and frontend containers were running with zero restarts.
- The local and public home routes returned HTTP 200.
- The public NCAAF league route returned HTTP 200 with populated slate data.
- Public game `401856636` rendered 16 players, settled lines, and three leaders.
- The focused NCAAF settlement suite passed all eight tests before release.
- The full release dry run passed before `v0.9.7` was cut.

The detailed replay and query evidence is recorded in
`docs/REPLAY-ncaaf-repair-steps-4-5-2026-10-03.md`. The promotion evidence and
the updated DEV/PROD `settlement_attempts` classification were committed on
`dev` as `60c70ca` (`docs: record NCAAF PROD promotion evidence`). That evidence
commit remains local because the task authorized no push outside the release
script.
