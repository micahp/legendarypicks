# NFL session context, 2026-10-12 (status of everything touched)

Supersedes `CONTEXT-nfl-2026-10-11.md` for status. Start with `INDEX-nfl-model-research-2026-10-12.md` (levers,
stats, branch inventory) and `PARKED-nfl-ratings-2026-10-12.md` (what is NOT to be re-analyzed). Nothing
below is pushed. Every number was measured on 2026-10-12 unless it says otherwise.

## 1. Is Spec B done? Built end to end, not merged, not seen in a browser (updated later 10-12).

Full status and evidence: `docs/STATUS-spec-b-2026-10-12.md` on the Spec B branch (head `e361a78`). The table below
is the earlier status; B4 to B8 are now built (B4 tested on real 2025 data; B5 and B8 only by jest and type check;
B6 gate passed thinly, rushing not published; B7 job run once for week 6 on dev, nothing graded yet). 2024 snap
counts were loaded and availability rebuilt with bracketed absences.

Spec B (`SPEC-player-projections-availability-2026-10-09.md`, section 7) has slices B0 to B8. Branch
`feat/player-projections-availability` (worktree `/root/lp-player-proj`, head `88d3bbe`, 12 commits not in
`dev`, nothing uncommitted).

| Slice | Status |
|---|---|
| B0 date fix, snap counts, injuries | Not on this branch. The review says the inputs already exist in the base and the weekly availability refresh includes injuries. Publisher reconciliation for them was not re-run. |
| B1 availability table | Built and reviewed. The five review findings are fixed in `fd9ad96`. |
| B2 per-game shares | Built. Rebuilt on a fresh publisher file 10-12: season denominators equal the publisher's weekly sums for 32 of 32 teams. One game is still missing (BUF at LA plays 10-12 night); rerun `build_player_game_shares.py --season 2026` on 10-13 morning. |
| B3 splits | Built. Real example: Puka Nacua out 2025 week 7, Stafford with and without (one game, shows the feature works, not an effect size). In the review doc. |
| B4 "without" filter, backend | **Not started** |
| B5 "without" filter, frontend | **Not started** |
| B6 projection engine v2 and redistribution | **Not started** |
| B7 weekly job, grading, ESPN benchmark | **Not started** |
| B8 API and projection record panel | **Not started** |

Still true about B1 to B3: the focused suite passes but the "52 tests" figure in the old notes does not
reproduce (44 on the review's file list, 59 with the shares and identity tests, all passing). Not merged into
`dev`, not on prod. The checklist in the HANDOFF doc ("Before anything goes to dev") is not satisfied yet.
Order in the spec after B1 to B3: B4 and B5 next (the user-visible props.cash feature), then B6 to B8.

## 2. NFL model research (`feat/nfl-model-foundation`, head `c84f880`, 14 commits not in `dev`)

Rule used throughout: pre-register in code, commit, then run; keep only if the pooled interval is entirely
below zero and 2024 and 2025 points are not above zero. Decided by Micah today: the market prior is not our
forecast (our model is v1 plus EPA by unit); no paying for timestamped odds.

Run today, all **not kept** (F-B is Brier change vs base; negative is better):

| Feature | Pooled | 2024 | 2025 |
|---|---|---|---|
| Penalties, season to date | +0.0000 [-0.0003, +0.0004] | +0.0008 | -0.0006 |
| Turnover margin | +0.0002 [-0.0001, +0.0004] | -0.0001 | +0.0000 |
| Independent preseason prior | -0.0008 [-0.0017, +0.0002] | +0.0007 | +0.0016 |
| FTN blitz, variants A and B | +0.0001 / -0.0002 | | coefficient flips sign |
| Participation pressure (2016+) | -0.0003 [-0.0010, +0.0005] | +0.0008 | +0.0002 |
| Participation coverage man/zone (2018+) | +0.0002 [-0.0002, +0.0006] | -0.0001 | +0.0000 |
| Contention (simulated P(playoffs) < 1%, wk 10+) | -0.0006 [-0.0017, +0.0006] | -0.0046 [-0.0089, -0.0003] | -0.0003 |

Contention is the closest to a keep: all three points go the right way and 2024 alone excludes zero, but the
pooled interval includes zero, so it stays not kept. Any retry must be a new pre-registered variant.

Stability split question (Micah: early and late season differ): measured four splits. First quarter vs last
quarter is not less alike than the two middle quarters at equal size; odd vs even weeks is the cleaner
split; turnover luck is near zero under every split. The table is in the INDEX; it came from a one-off query,
not a saved script. The keep tests never used a half-season split.

Man/zone coverage was first dropped as "inconsistent" and then reinstated: team man share is stable
(first vs second half r 0.62 to 0.85); what changes is labelling (none in 2016-17; sacks unlabelled until
2022; league man share 29% in 2022, 41%, 49% in 2023-24, 31% in 2025). The test used within-season shares
relative to the league and excluded sacks.

## 3. Data state (dev DB, `picks.dev.db`)

- New: `nfl_hist_participation`, 2016 to 2025, file rows equal stored rows for all 10 seasons, loaded by
  `load_nfl_history.py --source participation` (`nfl_hist_loads` has a row each with sha256).
- `nfl_pbp` gained `penalty`, `penalty_team`, `fumble_lost`, `fumble` (2010 to 2025 backfilled). **They are
  null on all 11,327 2026 rows.**
- **2026 week 5 play-by-play is missing**: 1 of 15 games stored, although nflverse had 14 (file updated
  10-12 09:05 GMT). BUF at LA is not played yet. Agreed: one 2026 ingest on 10-13 morning. **Nothing
  schedules play-by-play ingestion.** The step exists only on `feat/nfl-epa-efficiency`, and ordering matters:
  land the research branch's ingest (which writes the four new columns) in `dev` first, or the weekly replace
  will write rows without them.
- `player_team_shares` rebuilt for 2026 (see section 1).

## 4. NFL grading (the new request)

- The grader already existed (`grade_nfl_locks.py`, writes `projection_grades`: Brier, margin error, total
  error, against the spread). It had never been run and no timer runs it: 0 grades, 37 finished locks.
- **Ran it 10-12 on the dev DB**: graded 37, a second run graded 0 (idempotent). Checked before writing: an
  independent ATS calculation matched on 37 of 37, and the spread sign was tested against outcomes
  (positive spread, home wins 71.6%, n=109).
- Result, 2026 week 5 only, graded games (tiny n, not evidence; straight up counts are winner-picked
  wins-losses, ties apart): adopted v1 8-3 with 1 tie, against the spread 5-6 with 1 push, 12 graded;
  v2 EPA (untuned first lock) 7-4 with 1 tie, ATS 5-6 with 1 push, 12 graded; the pre-freeze 10-09 v1 9-3 with
  1 tie, ATS 6-7, 13 graded. **An earlier figure of "v1 17 of 23, 11-13-1" added the adopted and the
  pre-freeze v1 together, counting the same games twice; do not use it.** Each version still has 1 lock
  awaiting a final.
- The live Model tab already showed each lock's grade ("off X, ATS W/L"), so the 37 grades appear.
- **Finished**: branch `feat/nfl-grading-record` (worktree `/root/lp-nfl-grading-record`, head `397d944`,
  one commit, a fast-forward of `dev`, not merged). Adds the straight-up result to each graded lock
  (`Pick ✓/✗/Tie`), a season record panel per model (winner W-L plus ties, against the line W-L plus pushes,
  n graded, locks awaiting a final; counts only, no win-rate percentages, "No graded games yet" instead of
  0-0), and `ops/systemd/legendarypicks-nfl-grade.{service,timer}` (daily 06:30 Chicago, NOT installed; the
  grader is idempotent and refuses games not final). Verified: 45 backend tests pass (7 new, expected values
  worked by hand); 3 new jest component tests pass; the record on the real dev DB matches an independent count
  (sums of 17-6 and 11-13-1 across the two v1 versions, 7-4 and 5-6-1 for EPA); strict type check of the tab
  passes and a deliberate type error is caught by the same setup. **Not checked: the tab in a browser.** It
  appears on `/leagues/nfl?tab=model` only after the merge.

## 5. Playoff odds and ratings (`feat/nfl-playoff-odds`, head `ce5c7f9`, 2 commits ahead of `dev`)

Product surface for the model already on `dev`, not model research. Fast-forward of `dev` (contains the `dev`
tip `3e5d3cc`), not merged. Adds `/api/nfl/playoff-odds` and `/api/nfl/ratings`, an odds-only job
`jobs/nfl_playoff_odds.py` (no locks, no grading), the page `/nfl/playoff-odds` plus a link, and timer and
service files (NOT installed). 97 NFL tests pass; job run on a scratch DB copy: 32 teams, sum of P(playoffs)
14.0, no `game_projections` rows. Not checked: browser render and full type check (syntax only).
**The page is empty until the job runs; the job's resource guard refuses while swap is full.** The page copy
does not yet say that v1 trails the market (15 of 16 seasons on Brier); one sentence is pending.

It replaced the 10-09 ratings work: the old branch `feat/nfl-ratings-playoff-odds` was deleted after review
(tag `archive/feat/nfl-ratings-playoff-odds`). That work would have deleted `dev`'s Model tab, locked a week,
duplicated the grader and read dropped columns. Parked and dropped items, with retrieval commands:
`PARKED-nfl-ratings-2026-10-12.md`.

## 6. Branches and worktrees

Live NFL work: `feat/nfl-model-foundation`, `feat/player-projections-availability`, `feat/nfl-playoff-odds`,
`feat/nfl-grading-record` (finished, unmerged), and `feat/nfl-epa-efficiency` (holds the weekly pbp step; remove once moved).
Deleted today with an archive tag each (17 `archive/*` tags exist): 15 branches already in `dev` plus the old
ratings branch; worktrees `lp-nfl-data-foundation`, `lp-nfl-schedule-a0`, `lp-nfl-ratings` removed (their ignored
files were checked first; three run logs copied to `/root/lp-archive/2026-10-12/`). Restore with
`git branch <name> archive/<name>`. Left in the list, not model work: `feat/nfl-allday` (Micah: forget it),
`codex/nfl-v1` (probably superseded, not verified line by line), `feat/prop-repair` (a 13-line fix that never
landed). 44 worktrees remain. `dev` has 8 modified and 15 untracked files that are not ours (radio and
GameCard front-end edits, sim output JSONs, four docs): left alone.

## 7. Mistakes caught today (so nobody repeats them)

- The first context summary (Haiku) had three wrong facts and four numbers with no source; fixed in `2758de1`.
  The four new-feature results did reproduce exactly when re-run.
- The plan's "355 air-yards rows" and the "52 tests" were stale; real values 378 and not reproducible.
- `git merge-tree --write-tree` does not exist on this box's git 2.25; a script printed "CONFLICTS" from the
  error. The ancestor check is the real answer.
- The old ratings API test could not even be collected on Python 3.8 (`int | None`): it had never run here.
- A "safe to remove" note in the index about `lp-nfl-schedule-a0` was wrong on its face (it had a unique
  commit), though the files turned out to be in `dev`.

## 8. Risks and open decisions

- **Swap is 4.0 of 4.0 GiB used.** Heavy jobs are risky; the playoff-odds job refuses by design.
- No timer was installed or changed today. Pending: playoff-odds timer, grading timer, weekly pbp step.
- Decisions for Micah: merge `feat/nfl-playoff-odds` into `dev` (and open `/nfl/playoff-odds` once); merge
  order for the research ingest; install timers; whether to keep `codex/nfl-v1` and `feat/prop-repair`;
  whether the 2026 week 6 locks resume (skipped on instruction).
- Not done and not started: Spec B slices B4 to B8; coverage and other FTN-style features need new
  pre-registered variants; the CONTEXT/INDEX files are unpushed.

## 9. Next steps, in order

1. 10-13 morning: 2026 play-by-play ingest (after BUF at LA lands), then `build_player_game_shares.py`.
2. Merge `feat/nfl-grading-record` when Micah says (disjoint from the playoff-odds branch, either order), then look at `/leagues/nfl?tab=model` once.
3. Merge `feat/nfl-playoff-odds` when Micah says; add the "v1 trails the market" sentence first.
4. Land the research branch's pbp ingest in `dev`, then add the weekly pbp step.
5. Spec B: B4 backend, then B5.
