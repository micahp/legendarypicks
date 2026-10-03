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
