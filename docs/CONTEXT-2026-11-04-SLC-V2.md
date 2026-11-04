# Context summary, 2026-11-04: SLC v2 research

Read this first. Follows `docs/CONTEXT-2026-11-02-SLC-V2.md`. Repo `/root/lp-slc-v1`, branch `pbv1-integration-2026-11-02`,
head `a6f06e79`, 20 commits ahead of `origin` (`831072df`). Nothing from 2026-11-03 or 2026-11-04 is pushed. V1.5 work is
on branch `slc-v1.5` in `/root/lp-slc-v1-5`, 16 commits ahead of `origin`, also unpushed.

## 1. Standing rules

- Hash-pinned layers (`slc_config.LAYER_CODE_FILES`) change only behind off-by-default research flags, with a numbered
  freeze amendment. The flags-off regression (Week 8 `2026_08_KC_DEN`, RNG v2, seeds 1 to 3) must match exactly.
- 2026 is sealed for development: schema and roster identity only, no 2026 outcomes for fitting or selection.
- Never push without explicit approval, never push to `dev` or `main`. Stage named files only. Separate commits per slice.
  No AI attribution. No em or en dashes.
- Talk to agents through tmux only (`tmux capture-pane -p -t pi:0.0`; `send-keys -l`, then `C-m`).
- Check `uptime` and `free -h` before heavy jobs. A local engine run takes about 7 minutes and 1.6 GB; run one at a time.
- Do not commit pi's `docs/research/SLC-V2-REALISM-GATES-DRAFT-2026-11-04.md` or
  `docs/research/TEMPORAL-WINDOW-2026-11-02/temporal_blend.py`. In `/root/lp-slc-v1-5`, do not commit
  `HOLDOUT-EXPOSURE-RECORD-2026.md` or `SLC-V15-WALKFORWARD-PROTOCOL-2026-11-03.md` without asking.

## 2. Decisions on record

- V1.5 does not advance (owner rule: lower log loss and Brier and a 95% interval below zero). Documented and stopped.
- Field goals: the ceiling is the longest attempt on record (76 yards) everywhere, desperation kicks allowed, make
  probability fitted to the kicker. The kick decision is weighted by yard line, not the whole situation cell (the cell's
  field bucket spans 38 to 67-yard kicks).
- Lineup groupings are drawn given the run or pass call (amendment 5).
- Season weights for the lineup table: 0.75 ** age over six seasons (grouping backtest).
- The live 2026 forecast may use published snap counts from earlier weeks (not participation, which has no 2026 source).

## 3. Work queue (owner: "go ahead with the queue"), all done and committed locally

| Item | Commit | Result |
|---|---|---|
| 1. Lineup hook | `9dbab0a1` (amendment 3) | Skill lineups carry snap to snap behind `--participation-field` |
| 2. Six-lineman and two-QB groupings | `7ca70d06` (amendment 4) | Codes `-OL<n>`, `-QB<n>` |
| 3. Grouping given the call | `f8bd934b` (amendment 5) | Pass-rate error by grouping 0.071 to 0.022; flags-off 0 of 3 differ |
| 4. Seasons 2016 to 2021 | `9cfbdcd5` | `build_tables.py --seasons --backfill-dir`; table `324c4e1a...` (2016 to 2025, 343,247 snaps) |
| 5. Thin-cell fallback test | `21c4f070` | Rule A (nearest distance, same down and field) kept |
| 6. Week-over-week grouping backtest | `ef8c1d87`, `7125f630` | Log loss A0 1.1666, A1 (0.75, 6 seasons) 1.1557, A2 (+ snap counts, N0 8) 1.1322, A3 (+ participation) 1.1329 |
| 7. Field goals by kicker | `524827d1` to `7580c9f6`, `20e3dba6` (amendment 6) | `--playcall-fg-kicker`; flags-off 0 of 3; smoke 3 of 3 valid; 359 tests |

V1 against V1.5 (`94cf8dcb` on `slc-v1.5`): 121 games of 2026 weeks 1 to 8, 20 seeds each. Winner log loss 0.6888 (V1)
against 0.6948 (V1.5), difference +0.0060 [-0.054, +0.070]. Both within noise of a coin flip (0.6931). Week 8 player
projections (14 games, the only scorable week) favour V1.5 on carries, rushing yards, targets, receptions and receiving
yards, also among players who recorded the stat (`dada4c08` adds this to the results doc; the verdict is unchanged).

## 4. Work on 2026-11-04 after the queue

Asked: refit the lineup table, wire in snap counts, backtest player snap shares, answer pi's questions.

1. `380ae267`: `participation_field.Field` gains `group_tilt` (snap-count tilt of the grouping draw), `player_weight`
   (current-season multiplier on a player's on-field rate) and `leave_power` (player-dependent leave hazard). All empty
   or zero by default. New `scripts/nfl_sequence/snap_update.py` (published snap counts, pfr id to gsis id through
   `players.csv` then the weekly roster) and `test_snap_update.py`. `lineup_fit.fit` and `fit_player_rates` take optional
   season weights.
2. `dcaec3de`: `weekly_player_backtest.py`, committed before the run.
3. `a6f06e79`: results, `WEEKLY-PLAYER-BACKTEST-RESULTS-2026-11-04.md`. Mean absolute error of a player's snap share per
   player-game, 2022 to 2025, 26,872 player-games:

   | Arm | Error |
   |---|---|
   | P0, table as it was | 0.2163 |
   | P1, six-season weights | 0.2175 (+0.0012, slightly worse for player rates) |
   | P1h, + player leave hazard, alpha 1.5 | 0.2034 |
   | P2, + current-season snap shares, N0 1 | 0.1553 |
   | N, published share to date (reference) | 0.1268 |

   Found while building it: the class-only hazard made a regular leave as often as a backup, so shares were too flat.
4. Why the layer still loses to share to date (2025 sample, 1,019 player-games with an earlier game): share to date
   0.117; the layer's blended target 0.127 (N0 1 still weights the table rate by 1/(1+G)); simulated 0.143 (unbiased by
   bin, but scattered per player: the weight scales per-grouping table rates, and players compete for a fixed number of
   slots). 91 of 1,019 weights hit the 50x clip. Candidate fixes, not run: N0 0 or a smaller grid; calibrate the
   weights before each game by simulating and rescaling until simulated shares hit their targets.
5. Refit tables exported, not committed: `docs/research/participation-model-2026-11-02/outputs/`
   `field_v4_decay075_2020_2025.json` (`9aaf7e57...`, for 2026 games) and `field_v4_decay075_2019_2024.json`
   (`81606560...`, for 2025 checks). Decay 0.75 over six seasons, `leave_power` 1.5, `leave_reference_rate` included.
   `export_field.py` gains `--decay` and `--leave-power`; without them it still writes the committed v4 table byte for
   byte (`b53b2566...`).
6. Engine wiring, uncommitted: `--participation-snap-counts` and `--participation-snap-counts-sha256` in
   `simulate_pregame_batch.py`; `slc_engine.load_reference(participation_snap_counts=...)` refuses another season's file,
   uses only weeks before the game, raises when a team has no earlier game in a file that has earlier weeks, and records
   the tilt and weights in the ledger's `research_integration`. `snap_update.PLAYER_N0 = 1.0`. Builder
   `build_snap_counts.py`. The per-seed replay command now carries the research table flags (it omitted
   `--participation-field` and `--playcall-fg-kicker` before).
7. pi's realism-gate questions answered in
   `/tmp/claude-0/-root/744b1ddf-da1c-4751-b1ee-106793d5f525/scratchpad/pi-realism-gate-answers.md` and sent via tmux:
   lineup grouping code (RB with FB) controls; top receiver is most targets at any position; RB2 is second-most snaps at
   position RB; denominator is the weekly roster ACT list (2025 has no pregame snapshots); 30 seeds per matchup (8,160
   games); per-seed `outcome['playcall']['lineup']` already has ID-keyed player snaps and grouping counts. pi is revising
   the draft and computing observed-only thresholds from 2023 and 2024; told not to simulate or commit.

## 5. Running or pending at the time of writing

- Local regression (`scratchpad/snap_regress/run.sh`): flags-off done, 0 of 3 seeds differ from the amendment 6
  baseline. The old v4 table with no snap counts is running; expect it to match `field_regress/v2_field_on` except the
  replay command.
- Next: `scratchpad/snap_regress/smoke.sh`, the refit table plus 2026 snap counts through week 7
  (`snap_counts_2026_through_w07.json`, `fc409bce...`, 214 team-games). This reads 2026 weeks 1 to 7 snap counts as
  forecast input only, which is the flag's purpose; nothing is scored on 2026.
- Then: amendment 7 doc and commit of the wiring, the refit tables and the builder.
- Owner question open: add the two calibration arms (N0 0, pre-game weight calibration) to the backtest before the
  smoke, or after the wiring.

## 6. Paths

- Scratchpad: `/tmp/claude-0/-root/744b1ddf-da1c-4751-b1ee-106793d5f525/scratchpad` (table `part-2016/`, backtest
  inputs `pbt_inputs.json`, regressions `field_regress/`, `snap_regress/`, comparer `regress/compare_runs.py`).
- Fast host: `ssh -o BatchMode=yes root@vmi3108149.contaboserver.net`, 6 cores, no pyarrow. Player backtest in
  `/root/repro/player-backtest`, V1 against V1.5 in `/root/repro/arms-season`.
- nflverse raw: `/root/lp-snapshots/nfl-backfill-2026-10-27/raw` (snap_counts, weekly_rosters, pbp_participation).
  `players.csv` pinned `c5239e14...` at `/root/gridiron-physics/data/raw/players.csv`.
- Frozen engine DB: `scratchpad/frozen/reference-inputs.sqlite`.

## 7. Open items

- Lineup layer: close the gap to share to date (section 4, item 4). The substitution shortfall (1.21 against 1.39
  entries per snap) was measured before the player hazard; not re-measured.
- Groupings: the six-season window and A3's N0 sat at the edge of their grids.
- Field goals: the kick decision has no clock, and does not depend on the kicker (65 to 69-yard attempts under-predicted,
  2.5 against 7 in 2025).
- Realism gate: pi's revised draft and thresholds need owner approval before any gate run.
- Nothing pushed; pushing `pbv1-integration-2026-11-02` and `slc-v1.5` needs the owner's go.
