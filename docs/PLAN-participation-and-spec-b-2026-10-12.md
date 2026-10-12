# Plan: participation tests and Spec B (2026-10-12, for Haiku to execute)

Written by Opus after verifying the 10-11 context. Every number here was measured on 2026-10-12
against `picks.dev.db` unless it says otherwise. Do the steps in order. Stop and report on any surprise;
do not improvise a fix.

## Already done (do not redo)

- Participation 2016 to 2025 is loaded into the dev DB as `nfl_hist_participation` by
  `load_nfl_history.py --source participation` (one season per call, file rows = stored rows for all 10,
  0 mismatches, `nfl_hist_loads` has a row per season with the sha256). Every 2016 to 2025 REG dropback
  in `nfl_pbp` joins to a participation row on `(game_id, play_id)`.
- Test 1 below (pressure) is pre-registered in `backend/nfl_feature_backtest.py`
  (`participation_keep_test`, the comment block above it). It has NOT been run.

## What the participation data looks like, by season (on REG dropbacks)

| Season | pressure flag on sacks | man/zone labelled | man share of labelled | Cover 1 / Cover 3 |
|---|---|---|---|---|
| 2016-2017 | null | 0% | none | none |
| 2018-2022 | null | 88.6 to 89.3% (sacks 0%) | 35.0, 37.2, 34.4, 30.3, 28.8 | about 23-30% / 30-34% |
| 2023 | true | 99.6% (sacks 98.5%) | 41.3 | 32.0 / 18.3 |
| 2024 | true | 99.8% | 48.5 | 36.5 / 17.7 |
| 2025 | true | 99.9% | 31.0 | 22.4 / 27.7 |

Defenders in box (about 6.0) and pass rushers (about 4.25) read the same in all ten seasons.

## Why man/zone was left out of test 1, and why that was too strong

Man/zone is important and it is usable. The inconsistency is in how it was labelled, not in the team signal:

1. **Missing years.** 2016 and 2017 have no coverage labels at all. A coverage test can only start in 2018.
2. **Sacks are unlabelled through 2022.** In 2018-2022 about 11% of dropbacks have no label, including
   every sack. From 2023 nearly every dropback is labelled, sacks included. Same pattern as the pressure
   flag, so it looks like a change in who charted the plays in 2023 (not verified against a publisher
   note). Fix: compute man share on non-sack dropbacks in every season.
3. **The league level jumps in 2023 and 2024, then comes back.** Man share 29% in 2022, 41% in 2023,
   49% in 2024, 31% in 2025. Cover 3 halves (32% to 18%) in 2023-24 and Cover 1 rises, then 2025 looks
   like 2018-2022 again. A real league-wide swing that size that reverses in one year is unlikely; it
   looks like a labelling change. Fix: never compare raw shares across seasons. Use each team's share
   minus that season's league share, and keep the window inside one season.
4. **The team signal is stable.** Team man share, first half vs second half of a season, r = 0.81, 0.72,
   0.77, 0.70, 0.65, 0.85, 0.67, 0.62 (2018 to 2025). Teams range from about 10% to 65% man. So it is a
   real, persistent team trait, as stable as target share.

So the right move is a separate, pre-registered coverage test (test 2), not dropping it.

## Why pressure first (test 1)

- It is the one participation column with a direct twin already graded: `pressure_matchup` used QB hits
  and was not kept (-0.0002). Charted pressure is the better measurement of the same thing, so this test
  answers a clean question: was QB hits too noisy, or does pressure just not predict margin?
- After counting every sack as a pressure, its definition reads the same in all ten seasons, so it gets
  the longest window (2016 to 2025).
- Expectation is low: QB-hit pressure carries over weakly (+0.34 split-half). Run it anyway, it is cheap.

Man/zone does not predict margin on its own (it is a style, not a quality). It only matters as a matchup:
an offense that is good against man facing a defense that plays a lot of man. Test 2 is built that way.

## Steps

### 1. Commit the pre-registration before any run
Opus committed it with this plan. Check `git log -1` shows the plan and `nfl_feature_backtest.py`.
If not, stop.

### 2. Run test 1 (pressure)
```
cd /root/lp-nfl-lock-by-version/backend
free -h            # need > 1 GiB available
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
  /root/legendarypicks/backend/venv/bin/python nfl_feature_backtest.py --feature participation_keep
```
About 1 to 2 minutes, under 200 MB. Keep rule (fixed in the code): pooled 2017-2023 F-B interval
entirely below zero, AND the 2024 and 2025 F-B points not above zero. Write the verdict exactly; do not
reinterpret it. If it errors, report the error and stop.

### 3. Pre-register test 2 (coverage matchup), commit, then run
Add to `nfl_feature_backtest.py`, docstring and constants first, commit, THEN run. The definition is
fixed here; copy it, do not change it:

- Seasons 2018 to 2025. Dropbacks = `qb_dropback = 1 AND sack = 0` joined to `nfl_hist_participation`
  with `defense_man_zone_type IN ('MAN_COVERAGE', 'ZONE_COVERAGE')`.
- Window: the same season only, weeks strictly before the game. Week 1 column = 0 (counted, printed).
- League values per season to date: `L_man` = man share, `L_eM` and `L_eZ` = mean `epa` on man and on
  zone dropbacks.
- Offense: `eM` = (sum epa vs man + 200 x L_eM) / (man dropbacks + 200), same for `eZ` with zone.
- Defense: `m` = (man dropbacks faced + 200 x L_man) / (labelled dropbacks faced + 200).
- Home edge = (eM_home - eZ_home) x (m_away - L_man). Away edge the same the other way.
  Column = home edge - away edge. Expected coefficient sign: positive.
- Grading: walk-forward stack fit from 2018 (`stack(..., seasons=list(range(2018, 2026)))`), base refit
  on the same rows. Groups: 2019-2023 pooled, 2024, 2025. Same keep rule as test 1. Print per-season
  diagnostics and the fitted coefficient like `participation_keep_test`.
- Tests before the run (new file `test_nfl_participation_features.py`): a hand-built 2-team, 2-week
  fixture where the expected column is computed by hand; week 1 gives 0; a sack never enters a share.
- CLI: `--feature coverage_keep`.

### 4. Record results
New file `docs/RESULTS-nfl-participation-2026-10-12.md` with both outputs pasted verbatim, the
verdicts, and the data table above. Update `docs/INDEX-nfl-model-research-2026-10-12.md` section 1
(two rows) and section 3 (participation row: stored, seasons, columns). Commit by file name. No push.

### 5. Spec B (worktree `/root/lp-player-proj`, branch `feat/player-projections-availability`)
Do not touch `/root/legendarypicks`. Two open items, both from
`docs/REVIEW-SPEC-player-projections-availability-2026-10-10.md`:

a. **B2 air-yards denominator.** 355 of 355 2026 `air_yards` season rows in `player_team_shares` have a
   `team_value` that differs from the sum of `nfl_team_game_totals` (example ARI 935 vs 944).
   Measure first, read-only: for 5 teams print both numbers and the per-game difference, and check
   whether the difference equals the no-receiver pass air yards (the spec, line 232, says
   `air_yards_unassigned` is exactly that). Report the cause BEFORE changing code. Then rebuild:
   `build_player_game_shares.py --season 2026 --dry-run` first, read its output, then without
   `--dry-run` only if the dry run reconciles. Acceptance (spec line 218): season table rebuilt from
   per-game, diff vs the old season table = 0 on overlapping metrics, and team air yards = sum of
   team-game totals for every team.
b. **B3 real WR1-out example.** Find one 2025 team whose WR1 (top target share) missed at least one
   REG game, using `nfl_hist_injuries` or the game logs, not a guess. Call `splits()` from
   `backend/player_splits.py` for that team with and without him and paste the output into the review
   doc. If no case qualifies, say so with the query you ran.
c. Run the focused suite (52 tests at `fd9ad96`) and report the count. Commit by file name. No merge
   into `dev`, no push.

## Rules (from the context file, still binding)
Dev DB only. Pre-register before running, never loosen after. Keep rule is pooled. `git add` by file
name. No `git stash`, no push, no merge into `dev`, no timers. No em dashes. Check `free -h` before runs.
