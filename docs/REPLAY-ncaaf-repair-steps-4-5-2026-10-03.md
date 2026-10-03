# NCAAF repair steps 4-5, DEV replay — 2026-10-03

Steps 4 and 5 of the 2026-10-02 repair order
(`docs/DIAGNOSIS-ncaaf-settlement-2026-10-02.md`) are implemented and rehearsed
on DEV only. Step 6's separate authorization still gates any PROD migration;
PROD data, settings, services, and schedules were not touched. Every number
below was measured on `backend/data/picks.dev.db` on 2026-10-03 through the
stated query or run.

## Step 4a — the stale unlinked Bovada fixtures are folded/linked

`fold_ncaaf_unlinked_fixtures.py` (commit `28c6f6a`), rehearsed on a disposable
clone, then applied to DEV. Scope: NCAAF rows with no event id, no final, and a
date before today — 93 rows carrying 2,350 unsettled props. The current slate
belongs to the scheduled linker.

- 86 rows folded onto their linked same-date twins or onto the linked holder of
  their verified event id: **2,172 props** moved by
  `prop_game_merge.fold_prop_game` (props + `prop_game_source_ids`), loser rows
  deleted, zero result rows lost (no loser held one).
- 4 rows took their ESPN event id from the unique final scoreboard snapshot of
  their date: **80 props** now sit on linked rows. Army/South Florida →
  `401862702`, Pittsburgh/Syracuse → `401858225`, Coastal Carolina/Liberty →
  `401869941`, Temple/Army → `401862779`.
- 3 rows (98 props) are the 2026-10-02 Liberty@Delaware, Penn State@Northwestern
  and Pittsburgh@Virginia Tech fixtures — left for the scheduled linker, which
  resolves them from the nightly scoreboard.
- Sam Houston State at Texas Tech folded onto row 7931 (event `401856805`,
  already linked): the Bovada club word "Sam Houston State" is outside the
  vocabulary, so the twin rule could not see the twin, but the event id is the
  identity.

DEV `PRAGMA quick_check` ok after the apply; zero orphan props.

## Step 4b — the passing-TD market alias

`total_passing_touchdowns -> passing_touchdowns` in `MARKET_ALIASES`
(commit `7026773`), with a regression test. The alias was invisible while all
such props sat on unlinked fixtures; unaliased they would have graded
unmappable the moment the fixtures folded.

## Step 5 — the CFBD-first NCAAF settler, with durable attempt reasons

`settlement/ncaaf_settle.py` wired into `settle_game` (commit `501341e`).
Eleven markets grade from the stored CFBD line keyed by event id + ESPN athlete
id: passing/rushing/receiving yards, passing/rushing/receiving TDs, INT, pass
attempts, receptions, and the three yardage/TD compounds. A row that lacks a
market's key is not evidence of zero — that prop falls to the ESPN fallback,
which keeps the existing DNP rule (zero only when another boxscore category
proves the athlete appeared). Markets CFBD does not publish (kicking,
completions, carries, total-TD components) never grade from the line.
Every prop attempt lands in `settlement_attempts` with stage, terminal, and the
reason trail, deduped so an unchanged state writes no new row.

Focused suites: 8 NCAAF settlement tests pass; adjacent settlement suites
50 passed; the two pre-existing soccer-catalogue failures fail identically on
the unmodified tree.

## Step 6 — the full DEV replay, measured

`settle_props.py --league ncaaf` against DEV (exit 0; intermittent ESPN site
403s left 82 props pending-with-error for the next scheduled pass):

| Disposition (latest attempt per prop) | Props |
|---|---:|
| settled, stage `cfbd` (`cfbd_line`, no request) | 2,152 |
| settled, stage `espn_fallback` | 22 |
| pending, `no_cfbd_row+athlete_absent_from_boxscore` | 2,116 |
| pending, `market_not_published_by_cfbd+no_cfbd_row+athlete_absent_from_boxscore` | 374 |
| error, boxscore 403 (stay open, retry next pass) | 82 |

CFBD-first settles by market: receiving_yards 1,158, passing_yards 456,
total_passing_touchdowns 320, rushing_yards 218.

Stale NCAAF backlog (kickoff > 6h ago, unsettled): **4,844 props before
(2,494 linked + 2,350 unlinked) → 2,670 after** — 2,572 pending on linked,
final games each with a durable reason, plus the 98 unlinked current-slate
props. The 2,174 resolved = 2,152 CFBD-line settles + 22 fallback settles.

## Known follow-ups, deliberately not done here

- Duplicate props: the fold can land a Bovada prop beside an identical relay
  prop on one game. The board's duplicate population is pre-existing and
  dominated by relay cross-book republishes; `dedupe_props.py` is the
  documented tool and its use is a separate decision.
- The 2,116 athlete-absent pendings are the honest DNP-shaped population: no
  published stat line anywhere. Terminal grading of those requires the
  originating book's void/DNP rule, which is step 5's fail-closed boundary,
  not a defect.
- PROD apply of all of the above requires separate authorization (repair order
  step 6).

## PROD apply — 2026-10-03

Step 6 was separately authorized by `TASK-ncaaf-prod-promo-2026-10-03.md`.
Release `v0.9.7` (`e237ee9`) was cut from an isolated branch directly atop
`v0.9.6`, after the full release dry run passed, so unrelated scoreboard work
on `dev` did not ride the release. The production backend and frontend images
were rebuilt from that release; both containers came up with zero restarts,
the local and public home routes returned 200, and the public NCAAF league and
game-props routes rendered populated data.

All database counts below were measured directly from
`backend/data/picks.db` on 2026-10-03 UTC. The stale-backlog instrument is the
same population as the DEV replay: unsettled NCAAF props whose fixture kickoff
was more than six hours old, split by whether the fixture has an ESPN event id.
Before the fold, at 18:36 UTC, it measured **4,952 props / 244 fixtures**:
2,624 props on 149 linked fixtures and 2,328 props on 95 unlinked fixtures.
The database held 401,304 props, 2,413 prop games, and 283,844 results; orphan
props were zero and `PRAGMA quick_check` was `ok`.

The online SQLite backup
`picks.db.pre-ncaaf-fold-20261003T184408Z.bak` was created and both source and
backup passed `PRAGMA quick_check` before the write. A disposable PROD clone
first printed every planned action: 96 source rows / 2,374 props, with 2,198
props in `FOLD`, 76 in `LINK`, and 100 on three 10-02 fixtures in `LEAVE`.
There were no `REFUSE` or result-bearing loser rows. Clone apply, repeated dry
run, `quick_check`, and orphan checks all passed. The identical live dry run
was then applied: **2,198 props folded and 76 linked**. Its post-apply dry run
had zero `FOLD`/`LINK` residue and only the same 100 current-slate props in
`LEAVE`; `quick_check` remained `ok`, orphan props remained zero, results
remained 283,844, and prop-game rows fell from 2,413 to 2,324.

The first managed PROD settlement pass reached NCAAF but was terminated by the
existing parent service's one-hour timeout before it could print its summary.
Its durable rows show 1,632 settlements: 1,616 from the CFBD line and 16 from
the bounded ESPN fallback. One explicit paced continuation was therefore
limited to the untouched range through 2026-09-05; it completed 33 games and
settled another 184 props (182 CFBD, 2 fallback), with 572 pending, one
game-level HTTP 403, zero unmappable, and zero voided. No retry loop or
systemd change was made.

Combined promotion-pass result: **1,816 props settled** — 1,798 directly from
the CFBD line and 18 through the fallback — and the stale backlog moved from
4,952 to **3,136**. At 19:14 UTC the latest durable attempt per prop was:

| Disposition (latest attempt per prop) | Props |
|---|---:|
| settled, stage `cfbd` (`cfbd_line`) | 1,798 |
| settled, stage `espn_fallback` | 18 |
| pending, `no_cfbd_row+athlete_absent_from_boxscore` | 2,258 |
| pending, `market_not_published_by_cfbd+no_cfbd_row+athlete_absent_from_boxscore` | 384 |
| error, boxscore HTTP 403 | 66 |

The interrupted managed pass had not yet attempted 374 linked stale props;
they remain open for the ordinary scheduled passes rather than being retried
ad hoc. Another 54 stale props remain on the two unlinked fixtures old enough
for the six-hour query at measurement time. These 374 unattempted + 2,642
pending-with-reason + 66 intermittent-403 errors + 54 unlinked account for all
3,136 open stale props. `settlement_attempts` held 4,810 state-change rows for
4,524 distinct props. Pending prop 872565 was spot-checked: exactly one row,
with reason `no_cfbd_row+athlete_absent_from_boxscore`.

Final PROD checks: 401,304 props, 285,660 results, 2,324 prop games, zero
orphan props, and `PRAGMA quick_check` `ok`. The public NCAAF slate returned
29 games / 857 distinct prop questions; game 401856636 returned 16 players,
33 settled lines, and three leaders. The only settlement errors measured were
the known intermittent ESPN 403 class.
