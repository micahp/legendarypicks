# SLC v2 blocked-kick validation failure

This folder preserves the complete failed game record for Default SLC v2, DEN–CAR, seed `300786`. The simulator returned a complete regulation record, but the game validator rejected its blocked-kick state transition. The box score reconciled; the game is still invalid because game validation failed.

## Reproduce the validator failure

From the repository root, run:

```sh
python3 docs/research/slc-v2-failure-evidence-2026-11-10/reproduce_validator_failure.py
```

This loads the preserved full record and runs `game_state.validate_game()` with the pinned validator source. It checks the compressed evidence hash and confirms the same `FootballAssertionError` and violated assertion. It does not run a new simulation seed.

## Original simulation

The seed was part of the Default V2 control arm, not the legacy V1 run. Its run configuration was:

```sh
python3 scripts/nfl_sequence/simulate_pregame_batch.py \
  --snapshot-file docs/research/slc-v2-failure-evidence-2026-11-10/den-car-week9-snapshot.json \
  --db /root/legendarypicks/backend/data/picks.dev.db \
  --slc-profile v1_full_stack --slc-v2 --rng-protocol v2 \
  --playcall-artifact docs/research/SLC-PLAYCALL-ARTIFACT-v1.json \
  --playcall-streak-file docs/research/slc-v2-failure-evidence-2026-11-10/wl-streaks-2026-11-07.json \
  --slc-fg-ordinary-cutoff 60.0 \
  --participation-snap-counts docs/research/slc-v2-failure-evidence-2026-11-10/snap-counts-through-week-8.json \
  --participation-snap-counts-sha256 36f28e18af3080df9f160d42dd5e3e59c37cfacf0dd24772ea51cfd41cadcfca \
  --games 1 --seed-start 300786 --export-boxscores \
  --max-simulation-errors 1000 --out /tmp/slc-v2-den-car-seed-300786.json \
  --slc-blocker-fix run_scramble_backoff \
  --slc-blocker-fix long_field_goal_feasibility \
  --slc-blocker-fix blocked_kick_source_audit \
  --slc-blocker-fix blocked_kick_geometry \
  --slc-blocker-fix safety_free_kick_boundaries
```

This command regenerates the seed only when run against the same source and identical database and inputs. The original source commit was `8a5d809ffaec720b3d7b8ddb487f33c55e5d0d0e`. The fast-host database was `/root/legendarypicks/backend/data/picks.dev.db`, 3,631,009,792 bytes, SHA-256 `1a775208bc6e38763ef59c38a6cc79bda3636007feb8c6dc44f085f668341daa`. The database is not copied into this repository. The self-contained validator replay above does not need it.

## Failure

- Game: `2026_09_DEN_CAR`, 2026 Week 9; seed `300786` (the 119th seed in range `300668–301000`).
- Snapshot: captured `2026-11-07T22:16:59Z`; scheduled kickoff `2026-11-08T18:00:00Z`. Its classification is `verified_forecast`. The snapshot predates finalized game rosters; that timing does not invalidate it.
- Result: `status=validation_error`, `valid_full_game=false`, `complete_game=false`.
- Validator: `ILLEGAL_STATE`, drive 12, play 102. It rejected a blocked punt recovered by the receiving team, whose next state was first-and-1 at its own 3-yard line.
- Box-score reconciliation: `passed`. Clock reconciliation: `reconciled`.
- Failure: `FootballAssertionError: ILLEGAL_STATE: drive 12 play 102 state_after: a blocked kick hands over a first down; found down 1 and 1 to go at yardline 3; context={'violated_assertion': 'drive 12 play 102 state_after: a blocked kick hands over a first down; found down 1 and 1 to go at yardline 3'}`
- RNG-v2 stream root: `cd7248fbdfcd1300936a7c8e64a9285c099e1cac56a50fc2e5a2da45686a3d1b`. Per-seed stream evidence root: `b1dae3fe9521670da472e926d7ba39c43c73509cf9f4e58bbfa26a84d66240cc`.

The failure occurred during the three-way comparison's Default V2 control run. The completed seed was preserved and was not rerun.

## Preserved inputs

- `failed-game-record.json.gz`: immutable simulator capture, including the full record, assertion evidence, RNG-v2 manifest, and input identities. The compressed file SHA-256 is `6e7531d0e5e828f7a43348142056423be66a4cb61f26b437cd8a6702d54e765c`.
- `seed-300786-outcome.json`: original complete JSONL seed row from the run ledger.
- `den-car-week9-snapshot.json`: exact frozen game snapshot.
- `snap-counts-through-week-8.json` and `wl-streaks-2026-11-07.json`: exact external model inputs used by the command above.
- `SHA256SUMS`: hashes for every preserved file.

The weekly snap-count file was acquired separately from the game snapshot. This is input provenance; the frozen game snapshot remains a valid pre-final-roster snapshot.

## Validator source hashes

The failed run identified source commit `8a5d809f`. These hashes pin the validator and the relevant runtime files from that commit:

| File | SHA-256 |
| --- | --- |
| `scripts/nfl_sequence/game_state.py` | `cd80cac2c0fb78195ab651cae4d175a4bd4b8e85d346e8add1f2d9dc35bb18b0` |
| `scripts/nfl_sequence/football_assertions.py` | `47b85e14d977fd16719e1c9a52496baf0c156272472a4c0298d035d954ffd9b8` |
| `scripts/nfl_sequence/game_legality.py` | `5ca1996c0492cd422052e25c07d71f97097a8c99d97aa1cb842babdaa0ba8a08` |
| `scripts/nfl_sequence/slc_engine.py` | `a3d676dd993a20307e8d088bd06189f19a3a3a1c9a5e48007c5e3498680d53a5` |
| `scripts/nfl_sequence/slc_outputs.py` | `ddcdce54d13db5be53e4db078a6c7bd50ead459a1673d6d5817c492e91509a13` |
| `scripts/nfl_sequence/rng_protocol.py` | `32bbe6523479607b206d4db2522ac54ac585430cc6583fb701161de85d560a6f` |
| `scripts/nfl_sequence/slc_config.py` | `fa16b8abcd90cd282fba55293e7152e5df34aa97d3ab3782cbef7bdaece2ffc7` |
| `scripts/nfl_sequence/slc_playcall.py` | `c5f7c60e8543cef53cf0c93a240c13ae049e59cec71e0fd0e79688537c8133c0` |

The simulation process used `simulate_pregame_batch.py` SHA-256 `b765850db95de76bd0fc474b3f23075d1f352254bdfe267c2440d78bccdb67f9`. The committed file at source commit `8a5d809f` hashes to `1d5789b2c071fa3a688716517e5e57c3e9e7bf8310289508747aac7ef8a38eb4`. The runtime worktree had a local C-pairing CLI change; this Default V2 run did not pass any pairing flag, so that branch was not used. The failed record and hashes above preserve the exact validator input independently of that CLI detail.
