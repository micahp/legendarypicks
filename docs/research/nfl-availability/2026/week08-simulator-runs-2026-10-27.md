# Week 8 simulator runs — interim report

This report records completed results incrementally. It does not promote a model or alter any run inputs.

## ARI at DAL

- Run: 10,000 seeds, seed range 1–10,000; process PID 671344; exit code 0.
- Pinned source: branch research/nfl-sim-run-index-2026-10-27, commit 1aedc435b4f41553b0f03aca5897c240e6967de4.
- Started 2026-10-27 20:11:21 UTC; finished 2026-10-28 01:32:27 UTC; wall time 5:21:06. Simulator-reported runtime before report writing: 19,233.1928 seconds.
- As-of: 2026-10-27T18:20:23Z. Availability was classified as unverifiable: the snapshot contains missing-report flags, with no injury designation for these teams. This run is exploratory.
- Run counts: 9,439 complete regulation, 402 complete overtime, 158 blocked, 1 simulation error; 9,832 valid full games (98.32%); 9 regulation-end ties.
- Error: seed 5722, TypeError: '<=' not supported between instances of 'NoneType' and 'int'.
- Blocked counts:
  - blocked kick, dead ball outside field: 4
  - blocked kick, kicking recovery outside field: 8
  - blocked kick, kicking return outside field: 4
  - unresolved field-goal kick outcome (guarded penalty/fumble/review): 48
  - unresolved punt outcome (guarded penalty/fumble/review): 24
  - blocked kick, receiving return outside field: 24
  - unmodelled safety free kick: 14
  - thin field-goal cell at 50+: 32
- Distribution over 9,832 valid full games: ARI win probability 50.15% (4,931 wins); DAL 49.85% (4,901 wins); mean score ARI 20.3354, DAL 20.2818; mean total 40.6173.

## Artifacts and provenance

- Output: /tmp/nfl-week08-runs-20261027-1aedc435/out/2026_08_ARI_DAL.json
- Output SHA-256: b78d02a04ca232f6a187ace71ed9c2384954e3b6b81b9810885c675b32c4ae1d (3,601,584 bytes)
- Availability snapshot: nfl-2026-w08-20261027T182023Z-c9ad71877b; content SHA-256 c9ad71877bc03ddf865210d2e44d5fdfd8d42f55323e03de60ba61c0422096eb.
- ARI-DAL full-depth roster input SHA-256: c4fea8534e5700b2a908e399a79c5b73424db18c9f058f561dbcaf3a4fe57360.
- ARI-DAL base pregame snapshot SHA-256: 663ac8566477c3b64d23af810672fc99675a8769d6a2b9e81a586f26b88e36cf; final frozen pregame snapshot SHA-256: 6aa14de4c69b9e688af2cd9737fe86db88f7d32a86f0067a507bba14f3c7c265.
- Game-information snapshot: gameinfo-2026-w08-20261027T185659Z-039a4748a3; content SHA-256 039a4748a3453b95f83c438af556ffadd98631a5fdcb93cd665f88acf3f5d936 (recorded as not used by the model).
- Run registry: /root/lp-snapshots/nfl-sim-runs-week08-20261027-1aedc435-retry1.

Original TypeError seeds and their frozen inputs:

| Game | Seeds | Full-depth roster input SHA-256 | Base pregame snapshot SHA-256 | Final frozen pregame snapshot SHA-256 |
|---|---:|---|---|---|
| ARI at DAL | 5722 | `c4fea8534e5700b2a908e399a79c5b73424db18c9f058f561dbcaf3a4fe57360` | `663ac8566477c3b64d23af810672fc99675a8769d6a2b9e81a586f26b88e36cf` | `6aa14de4c69b9e688af2cd9737fe86db88f7d32a86f0067a507bba14f3c7c265` |
| BAL at BUF | 6917, 9243 | `37a16dc62f20598bab2e9165cabeadf0fdda64cbc8ae6b5f745d1d979621e2c4` | `0acf0f348233e01f835f95aab78d639a689c6a893b2a8a818ea7f268ce17c09d` | `e3743bd6358310cd5cc1e1cf070fec3d0ae654922d1f6d966315818af6c6c2eb` |
| CHI at SEA | 1261, 7805 | `5d88ab40fc503915b28310053208d02c2070685fb0c5dab58b02a7538e041a5c` | `e5cc4b9b83509354fa8c33e65e8be20a292a50cdc844b1ad5ad6bd6b6ffd8f5f` | `9239c62d4f2987c90dadf959e5527a2222f8c51ed7b31c22f6a9fbbae35bddd4` |

## Four additional completed original runs

Each run used seeds 1-10,000 on the pinned commit and snapshots listed above. Availability was unverifiable, so these runs are exploratory.

| Game | Regulation / overtime / blocked / errors | Valid full games | Regulation-end ties | Away / home win probability | Mean away-home score; total | Runtime (s) |
|---|---:|---:|---:|---:|---:|---:|
| ATL at TB | 9,431 / 400 / 169 / 0 | 9,822 (98.22%) | 9 | 50.45% / 49.55% | 20.4638-20.4419; 40.9056 | 19,524.0024 |
| BAL at BUF | 9,451 / 365 / 182 / 2 | 9,806 (98.06%) | 10 | 49.84% / 50.16% | 20.4395-20.5434; 40.9830 | 19,373.0080 |
| CAR at GB | 9,412 / 398 / 190 / 0 | 9,802 (98.02%) | 8 | 51.46% / 48.54% | 20.5225-20.2812; 40.8037 | 19,377.5937 |
| CHI at SEA | 9,452 / 380 / 166 / 2 | 9,823 (98.23%) | 9 | 50.50% / 49.50% | 20.5368-20.4321; 40.9690 | 19,447.1116 |

### Per-game artifact checks

- ATL at TB: finished 2026-10-28 01:37:15 UTC, PID 671345, exit 0. Output SHA-256: e31c9b6b595cc724409583a6a99d5de1cbc58db06de14b74d14118c18a26add9. No simulation errors.
- BAL at BUF: finished 2026-10-28 01:34:33 UTC, PID 671346, exit 0. Output SHA-256: cd34763246a56a107b2eb3188f023f43f9fdda784d72cb8464fff1bc4e966a22. Errors at seeds 6917 and 9243: TypeError, comparison of NoneType and int.
- CAR at GB: finished 2026-10-28 01:34:33 UTC, PID 671347, exit 0. Output SHA-256: de0e828d010383f80143b7bcc1a34a0df1167d12a0eef44094746e4d4e7df4fc. No simulation errors.
- CHI at SEA: finished 2026-10-28 01:35:39 UTC, PID 671348, exit 0. Output SHA-256: 0e9295ae63a5c97056ad3168e0fd1a8a0bf41d4e972ead8df9d0abc72f8efaae. Errors at seeds 1261 and 7805: TypeError, comparison of NoneType and int.

### Run-control update

At user direction, SIGTERM was sent to retry processes for CLE-PIT (681702), IND-JAX (681814), LAC-LA (681815), LV-NYJ (681874), and MIN-DET (681929). A subsequent process check found none of those simulator PIDs running. Interrupted retries are not included in the completed-run counts.
