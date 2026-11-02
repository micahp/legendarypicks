# SLC integration ledger, verified, 2026-10-29

Replaces the status claims in `SLC-INTEGRATION-LEDGER-2026-10-28.md` where they differ. Every entry below was checked against the
named commit (git ls-tree, git show, git grep for imports and call sites) on 2026-10-29. "In SLC" means the file exists at the SLC
research branch head `3e2ecf3b` (model code unchanged since `ad7e26d9`). "Invoked" means a call site on the simulation path, not an
import alone.

Two corrections to the earlier audit, verified:
- The pushed SLC branch was not at `bbc21f7` when checked. `bbc21f7` is an ancestor of the branch. The remote head was `fa86fd49`
  at the time, and the branch is now `3e2ecf3b`.
- The score-clock policy is passed to the drive engine's pre-play state (commit `ac7471af`). The engine does pass the live score.
  It is not called by the default batch; it is called only when `--playcall-artifact` is passed (SLC path).

## Components

Fields: repository and branch and commit; files; in SLC; invoked by the engine; input and output contract; training window, cutoff
and provenance; runtime test; missing step.

### 1. Score-clock play-call layer (connected)
- Repo and branch: Legendary Picks `research/slc-model-2026-10-28` (ancestor chain from `bbc21f79`); artifact commit `6512a2cd`.
- Files: `scripts/nfl_sequence/slc_playcall.py`, `scripts/nfl_sequence/playcall_model.py`,
  `docs/research/SLC-PLAYCALL-ARTIFACT-v1.json` (2010–2025, sha256 `27c02afd...`), and the 2024 and 2025 cutoff artifacts.
- In SLC: yes.
- Invoked: yes, on the SLC path. `slc_engine.load_reference` passes the artifact to `e2_reference.load`, which installs
  `PlayCallSampler` as the drive policy. `e1_drive.simulate` calls `sampling_policy.sample` once per play.
- Contract: in: quarter, clock, down, distance, yardline, score difference, offense team. Out: intent (run or dropback), the chosen
  historical row, and a decision record with the probability used.
- Training window and cutoff: fit 2010–2025 for 2026 evaluations; 2010–2023 for 2024; 2010–2024 for 2025. Recency reference equals
  the game season. Provenance: 522,235 primary plays (2026 artifact).
- Runtime test: `test_slc_playcall.py` (12 tests, including score and clock sensitivity and play-before-outcome order), and
  `run_slc_game.py` and the batch runner exercised on 2026 Week 8 and 2024 snapshots.
- Missing step: kick decisions use the situation cell's historical share, labelled as a fallback.

### 2. Pre-event participant selection (connected on its branch, not merged)
- Repo and branch: Legendary Picks `research/slc-preevent-2026-10-29`, commit `50cf81b9`.
- Files: `scripts/nfl_sequence/pre_event.py`, `test_pre_event.py`, and changes in `slc_playcall.py`, `game_state.py`, `e1_drive.py`,
  `slc_engine.py`.
- In SLC: no, on a separate branch. The locked forecasts use `ad7e26d9`, which predates it.
- Invoked: yes, on that branch. `slc_engine.play` sets `PlayCallSampler.participant_chooser`. The chooser runs after the intent
  is drawn and before the outcome. `game_state.participants_for` reads the choice and fails closed if it is missing.
- Contract: in: snapshot rosters and usage shares, intent, seed and decision index. Out: the passer (starting QB) and target for a
  dropback, or the rusher for a run, with side and team.
- Training window: none. The choice uses the pregame roster and usage shares only.
- Runtime test: `test_pre_event.py`, and 257 related tests pass. A full trace has 156 plays, and each pass and run has a consistent
  participant (verified). On three Week 8 seeds the scores match the locked model, and the S0 control is identical.
- Missing step: the outcome is not conditioned on the chosen player. Participant-conditioned outcomes need player rates and a
  cutoff-safe model.

### 3. Pregame roster and depth snapshot, captured (connected)
- Repo and branch: `research/slc-model-2026-10-28`; commits `ad7e26d9`, `3e2ecf3b`.
- Files: `scripts/nfl_sequence/pregame_capture.py`, `pregame_snapshot.py`, `test_pregame_capture.py`,
  `docs/research/slc-week8-2026/snapshots/*.json`, `capture-manifest.json`. Raw files are outside the repo and hash-pinned.
- In SLC: yes.
- Invoked: yes. The batch and single-game runners take `--snapshot-file`.
- Contract: in: the raw depth-chart, injury and schedule files with hashes and times. Out: a frozen snapshot with rosters, starter
  QB1, injury report per team, and an evaluation class.
- Provenance: schedule and depth acquired 2026-10-28 23:59Z to 2026-10-29 00:00Z (before kickoff); publisher times precede
  acquisition; cutoff 2026-10-29 00:02:21Z. Injury rows exist for CAR-GB only.
- Runtime test: `test_pregame_capture.py` (chain breaks), `test_pregame_provenance.py`, `test_holdout_2026.py`.
- Missing step: injury reports for 13 of 14 Week 8 games are absent at capture. The engine does not consume the injury report.

### 4. Team offense and defense splits (not connected)
- Repo and branch: Legendary Picks `research/nfl-historical-splits-2026-10-27` at `1d70898b`. `backend/player_splits.py` and docs
  (`NFL-TEAM-SPLITS-2026-10-27.md`) are on that branch.
- In SLC: no.
- Invoked: no. The only team term in the engine is the team-by-down effect inside the play-call artifact.
- Contract on the branch: per-team split tables (not verified in this pass).
- Training window and cutoff: not verified for a per-cutoff build.
- Missing step: a cutoff-safe per-season builder for SLC, and a combination rule with the play-call team-by-down term so the effect
  is not counted twice. Not started.

### 5. Team-specific playbooks (not connected)
- Repo and branch: Gridiron Physics `research/nfl-team-season-playbooks-2026-10-27` at `0c1541c`. 76 files under `data/playbooks/`,
  for example `KC-2025.json`.
- In SLC: no.
- Invoked: no. The playbook data feeds the play-call training observations (`playcall_observations.py` reads a pinned path
  `/root/gridiron-playbooks-research/...`), not team play choice.
- Contract: per team and season, counted and rated categories (formation, personnel, pass rate, situations) with source play IDs.
  Season 2025 only.
- Training window and cutoff: 2025 season, complete before 2026. A prior-season use for 2026 is admissible under the cutoff rule.
- Missing step: a mapping from playbook categories to play-call weights, a check that the mix changes, and a validation. Not started.

### 6. Statistical role decision model (not connected, holdout exposure)
- Repo and branch: Legendary Picks `research/nfl-historical-splits-2026-10-27`. The file `scripts/nfl_sequence/decision_model.py` is
  in commit `fd2a5aea` (an ancestor of that branch). It is not present at the branch's current path.
- In SLC: no. No module imports it at `3e2ecf3b`.
- Invoked: no.
- Holdout exposure: the repo's integration manifest records that decision model v1 has already been run on 2026 test data.
- Missing step: a decision on the exposure, from the project owner, before any prospective use. Then the port and a cutoff-safe fit.

### 7. QB opportunity propensity (not connected)
- Repo and branch: Legendary Picks `feat/nfl-props-opportunities-propensity` at `06cba41d`. `backend/nfl_qb_opportunities_propensity.py`.
- In SLC: no. Invoked: no.
- Contract: a team-game opportunity model (`fit`, `evaluate`), a player-game projection, not a per-play decision.
- Usage in the file: `--fit-seasons 2013 ... 2021 --season 2026`. Holdout exposure to be checked.
- Missing step: a per-play adapter, a cutoff audit, and an evaluation without 2026 use.

### 8. Receiver target-share distribution (not connected, holdout exposure)
- Repo and branch: `nfl-receiver-target-share-dist-v1` at `79523c00`. `backend/nfl_receiver_target_share_dist_v1.py`.
- In SLC: no. Invoked: no.
- Contract: player-game target-share distributions, Monte Carlo (`N_SIMS=1000`), not per-play.
- Holdout: the module's docstring says it was "tested on holdout 2026".
- Missing step: a per-play adapter, and settlement of the holdout exposure.

### 9. Rushing carries distribution (not connected, holdout exposure)
- Repo and branch: `feat/nfl-rushing-carries-dist-v1` at `24d793c6`. `backend/nfl_rushing_carries_dist_v1.py`, with a pre-registered
  spec.
- In SLC: no. Invoked: no.
- Contract: player-game carry distributions (zero-truncated negative binomial mixtures), not per-play.
- Holdout: the spec states it was corrected "before any valid holdout number". Exposure to be confirmed against the 2026 data.
- Missing step: a per-play adapter, and a holdout check.

### 10. Rushing participation v4 (not connected, holdout exposure)
- Repo and branch: `feat/nfl-rushing-participation-v4` at `fc6dba4b`. `backend/nfl_rushing_quantile_map_v4.py`.
- In SLC: no. Invoked: no.
- Holdout: its default evaluation seasons are `2025 2026` (`--eval-seasons`).
- Missing step: a per-play adapter, and settlement of the holdout exposure.

### 11. Contextual sampler (inherited, optional, not in v1)
- Repo and branch: `research/nfl-contextual-integration-2026-10-26` at `1e2bb3bf`. `scripts/nfl_sequence/contextual_pool.py` is in SLC.
- In SLC: yes. Invoked: only when `contextual_mode` is set. `e2_reference.load` refuses to combine it with the play-call layer.
- Missing step: a combination rule, if it is to be used with the play-call layer.

### 12. Simplified team-tendency sampler (inherited, optional, not in v1)
- Repo and branch: `research/lp-event-team-tendency-2026-10-28` at `bbc21f79` (ancestor of SLC). `scripts/nfl_sequence/team_tendency.py`.
- In SLC: yes. Invoked: only when `team_tendency=True` in `e2_reference.load`, and refused with the play-call layer.
- Missing step: as for the contextual sampler.

### 13. E1, E2, reducer, game-state engine, game statistics (connected, inherited)
- Files: `e1_drive.py`, `e2_reference.py`, `game_state.py`, `reducer.py`, `game_stats.py`.
- In SLC: yes. Invoked: yes, on every game. `game_stats` produces role allocations, not projections.
- Runtime test: the existing engine suites (246 at the earlier head; 257 related tests pass at the current head), and 120
  exploratory replay games with 0 errors.

### 14. E3 clock candidate (optional research mode)
- Files: `clock_d.py`, `clock_d_games.py`, `clock_d_replay.py`. In SLC: code present. Invoked: only in the optional mode.

### 15. Coaching (excluded from v1)
- Repo and branch: `research/playcall-coaching-2026-10-28` on origin at `ea761ceb`. Excluded from SLC v1 by decision.

### 16. Physical QB behaviour (excluded from v1)
- Gridiron Physics `exp/qb-decision-2026-10-25` at `2aee6f1`. A separate physical simulation, not the statistical QB model.

## Summary

- Connected on the SLC path: play-call layer (1), captured pregame snapshot (3), engine (13).
- Connected on a branch, not merged: pre-event participant selection (2).
- Inherited, optional, not in v1: contextual and team-tendency samplers (11, 12), E3 clock (14).
- Not connected: team splits (4), playbooks (5), role decision model (6), QB opportunity (7), receiver target share (8), rushing
  carries (9), rushing participation (10).
- Excluded from v1: coaching (15), physical QB (16).

Holdout exposure is recorded for items 6, 8, 9 and 10, and checked, not yet settled, for item 7.
