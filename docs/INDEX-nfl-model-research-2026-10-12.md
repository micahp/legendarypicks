# Index: NFL model research, where everything is (2026-10-12)

Read this first. It lists every lever and stat we have considered, what happened to it, where the data
is, and where the code and results are. Update the status column when something changes.

## 1. Levers for the game model (Brier against the benchmark ladder)

Source plan: [RESEARCH-nfl-model-inputs-2026-10-11.md](RESEARCH-nfl-model-inputs-2026-10-11.md).

| Lever | Status | Result | Where |
|---|---|---|---|
| Offseason carryover (shrink, prior games) | tested, no change | 21 settings, none passes the rule on 2024 and 2025 | [RESULTS-nfl-ladder-carryover-2026-10-12.md](RESULTS-nfl-ladder-carryover-2026-10-12.md), `backend/nfl_ladder.py` |
| Preseason market prior | tested, kept | +0.0055 Brier gain, market-derived, so not our own forecast | [RESULTS-nfl-features-vs-market-2026-10-11.md](RESULTS-nfl-features-vs-market-2026-10-11.md) |
| EPA per play by unit (v2 stack column) | tested, kept (marginal) | +0.0019 gain, 2011 to 2023 | same as above |
| Rating uncertainty (sigma by week) | tested, not kept | 0 change | same as above |
| Margin spread by game | covered by the rating uncertainty test | not kept | same as above |
| QB relative to team baseline (QBI) | tested, not kept | -0.0001 | [RESULTS-nfl-backfill-features-2026-10-11.md](RESULTS-nfl-backfill-features-2026-10-11.md) |
| Availability (AVAIL, snap share) | tested, not kept | -0.0001 | same as above |
| Special teams EPA | tested, not kept | +0.0006 | [RESULTS-nfl-features-vs-market-2026-10-11.md](RESULTS-nfl-features-vs-market-2026-10-11.md) |
| Venue, rest and wind | tested, not kept | +0.0003 | same as above |
| Pressure matchup (QB hit rate) | tested, not kept | -0.0002 | [RESULTS-nfl-matchup-features-2026-10-12.md](RESULTS-nfl-matchup-features-2026-10-12.md) |
| Sack matchup | tested, not kept | +0.0001 | same as above |
| Share-weighted absence | tested, not kept | -0.0000 | same as above |
| Independent preseason prior (EPA regressed, QB change, coach, returning snaps; no market data) | **not started** | | proposed next, see section 4 |

## 2. Stats: stability and status

Stability = first half of a season against the second half (r). Source:
[RESULTS-nfl-stability-stats-2026-10-12.md](RESULTS-nfl-stability-stats-2026-10-12.md).

| Stat | Stored in dev DB? | Stability r | Predictive test | Note |
|---|---|---|---|---|
| Target share (per player) | derivable from `nfl_pbp` | +0.70 | not yet (Spec B first) | input for player props |
| Carry share (per player) | derivable from `nfl_pbp` | +0.74 | not yet | input for player props |
| Receiving TD share | derivable | +0.31 | not yet | noisy, do not weight |
| Rushing TD share | derivable | +0.42 | not yet | noisy |
| Pressure generated (`qb_hit` per dropback) | yes, since 10-11/12 | +0.34 | tested, not kept | weak carryover |
| Sack rate allowed | yes (`sack`) | +0.39 | tested, not kept | |
| QB scramble rate | yes, since 10-11/12 | +0.70 | not tested alone | team style |
| No-huddle rate | yes, since 10-11/12 | +0.86 | not tested | team style, probably totals not margin |
| Blitz rate, pass rushers, QB out of pocket, QB-fault sacks | FTN, 2022 to 2025 only (`nfl_hist_ftn_charting`) | not measured | not tested | about 1,100 games, keep feature count small |

## 3. Stats not yet in the model: published, not stored

Checked 2026-10-12 against the 2024 nflverse play-by-play file (372 columns). `nfl_pbp` stores a curated
subset, so none of these are in the DB yet.

| Idea | Published columns (nflverse pbp) | Stored? | Notes |
|---|---|---|---|
| Penalties | `penalty`, `penalty_team`, `penalty_yards`, `penalty_type`, `penalty_player_id`, `first_down_penalty` | no | the referee is in `nfl_schedule.referee` (check its coverage first) |
| Turnover luck | `fumble_lost`, `interception`, `fumble` | no | new idea, untested; test whether fumble and interception rates carry over before adjusting ratings |
| Third-down and drive luck | `third_down_converted`, `third_down_failed`, `drive_time_of_possession`, `drive_play_count` | no | new idea, untested |
| Pass rate over expected | `xpass`, `pass_oe` | no | new idea, untested |
| Yards after catch and expected EPA | `yards_after_catch`, `xyac_epa` | no | new idea, untested |
| Win probability and field goal probability | `vegas_wp`, `fg_prob` | no | probably not needed (market-derived) |
| Participation (formations, personnel, defenders in the box, coverage) | not in the nflverse pbp file; a separate release | no | which seasons are covered is **not checked** |
| Time to throw, Next Gen Stats | not in the pbp file; separate release | no | which seasons are covered is **not checked** |

## 4. Next, in the order we agreed

1. **Week 6 locks before Thursday 10-15 20:15 ET** (only hard deadline). Needs the week 5 result, the
   2026 pbp refresh from this worktree, and the completeness check.
2. **Independent preseason prior.** Built only from published data (last season's EPA by unit, regressed
   toward average; QB change from `home_qb_id`; coach change from `home_coach`; returning starters from
   snap counts). No market input. Tested on the same ladder and the same keep rule.
3. **Penalties and turnover luck** as one cheap batch: backfill the published columns the same update-only
   way as the QB columns, test stability, then test prediction on top of EPA.
4. **FTN and participation last**, because their sample is small. Check participation season coverage
   before any ingest.
5. **Spec B** (player projections) uses the shares, and its checklist is in the handoff.

Open decisions for Micah:
- Schedule the weekly pbp ingest in `dev`: `scripts/nfl-availability.sh` on branch
  `feat/nfl-epa-efficiency` has the step (Tuesday 09:30); `dev` does not.
- Push `dev` (local, 58 commits ahead of origin's `dev`, not pushed) and this branch.
- Recurring line capture and the Sam recorder (approved 10-11, not set up).

## 5. Where the code and the branches are

| Thing | Location | Status |
|---|---|---|
| Model harness, features | `backend/nfl_feature_backtest.py` on `feat/nfl-model-foundation` | committed `cde089a` |
| Ladder and carryover | `backend/nfl_ladder.py` on `feat/nfl-model-foundation` | committed `f3b5dda` |
| Model page (v1 locks) | `dev` | merged 10-12, live on :3096 `/leagues/nfl?tab=model` |
| Spec A doc (v1 and v2 separate) | `dev` | merged 10-12 (`8d7840f`) |
| Old EPA blend (retired) | branch `feat/nfl-epa-efficiency` | worktree removed; code kept on branch only |
| Old EPA blend result and review | `dev` (docs only) | archived 10-12 (`3e5d3cc`) |
| Spec B (player projections) | branch `feat/player-projections-availability`, worktree `/root/lp-player-proj` | 10 commits not in dev, 1 uncommitted doc |
| NFL ratings, grading, tiebreakers | worktree `/root/lp-nfl-ratings` | **keep**: 28 uncommitted files, 6 not in dev (`nfl_grading.py`, `nfl_tiebreaker_data.py`, their tests, model systemd unit and timer) |
| All Day lineups (not model) | worktree `/root/lp-nfl-allday` | unrelated to the model |
| Clean worktrees with nothing unique | `/root/lp-nfl-data-foundation`, `/root/lp-nfl-schedule-a0` | safe to remove, not removed yet |

## 6. Rules that apply to all of this

- Pre-registered rules are written before the run. Parameters are fixed in the docstring first.
  Do not loosen a rule after seeing a result.
- Keep rule for features: pooled 2011 to 2023 interval entirely below zero, and the 2024 and 2025
  point differences not above zero.
- The dev DB is read-only for analysis. Backfills write only the added columns, keyed on
  `(game_id, play_id)`. Never `ingest_nfl_pbp_logs.py --year` on past seasons.
- Check RAM before batch work (available memory has been about 1 GiB).
- Pushes and merges into `dev` only when asked.
