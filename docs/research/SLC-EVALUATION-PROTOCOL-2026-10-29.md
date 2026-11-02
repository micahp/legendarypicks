# SLC evaluation protocol, 2026-10-29

Model: SLC v1 (`slc_v1_incomplete`), research branch `research/slc-model-2026-10-28`. This protocol is fixed before the Week 8
forecasts are locked. Coaching and physical movement are outside v1. Nothing is merged to dev or main, and nothing is deployed.

## 1. Three evaluation classes, kept apart

| Class | What it is | What it may support |
|---|---|---|
| `backtest` | Snapshot built only from inputs with a verified availability time before the cutoff, for a game whose outcome is not in the model | A predictive claim, if the model is locked before the game |
| `exploratory_replay` | Snapshot with unverified or reconstructed inputs, labelled `evaluation.verified=false` | Debugging, engine checks, distribution and scoring calibration. Never a predictive claim |
| `prospective_forecast` | Snapshot built from raw captures acquired before the cutoff, every input hash-pinned, plus a model locked before kickoff | A predictive claim, scored once the game is played |

A capture builds only `prospective_forecast`. The database builder refuses that class. Nothing built from present-day tables is a
`backtest` unless every input has a verified availability time, and no source has one today (`VERIFIED_CAPTURE_SOURCES` lists
only the raw capture).

## 2. Holdout

- 2026 outcomes are sealed from all fitting, tuning, calibration and selection.
- A 2026 read needs an explicit game cutoff and verified provenance. An unbounded 2026 read or fit is refused.
- The play-call artifact for a 2026 evaluation is fitted through 2025 (`SLC-PLAYCALL-ARTIFACT-v1.json`, sha256 `27c02afd...`) and
  is not refit on 2026 results.
- The play pool for any game uses prior seasons only (`eligible_before=(season, 1)`). A 2026 forecast draws on 2022 to 2025.
- Decision model v1 has already been run on 2026 test data. It is excluded from every prospective forecast until the exposure is
  settled in writing. That decision belongs to the project owner.

## 3. Fit windows by evaluation season

| Evaluation season | Fit window | Artifact |
|---|---|---|
| 2024 | 2010 to 2023 | `SLC-PLAYCALL-ARTIFACT-FIT-2010-2023-v1.json` (sha256 `962bae5b...`) |
| 2025 | 2010 to 2024 | `SLC-PLAYCALL-ARTIFACT-FIT-2010-2024-v1.json` (sha256 `07929a45...`) |
| 2026 | 2010 to 2025 | `SLC-PLAYCALL-ARTIFACT-v1.json` (sha256 `27c02afd...`) |

`check_artifact_cutoff` refuses any artifact whose reference season is not the game season, or whose fit reaches the game season.

## 4. Reference pools: cutoff audit

Verified on 2026-10-29 by loading the reference at cutoffs (2024,1), (2025,1) and (2026,1) (`REFERENCE-COHORT-AUDIT-2026-10-28.md`
and `SLC-REFERENCE-CUTOFF-VERIFICATION-2026-10-29.md`). Each source below advances with the cutoff and holds no season at or
after it:

- play pool (e1 rows): max (2023,18), (2024,18), (2025,18) at the three cutoffs
- participant facts: max season equal to the cutoff's prior season
- blocked-kick records and kick table: rebuilt from the cutoff
- safety-kick pool, overtime drive pool, missed-field-goal pool: grow with the cutoff
- overtime try fallback: refitted from tries before the cutoff
- overtime choice rate: the Beta(1,1) prior at each cutoff (no observed choices are recorded in the play-by-play); a documented limit

## 5. Prospective forecast requirements

A forecast is prospective only when all of the following hold. Otherwise it is refused, or classified `exploratory_replay`.

1. Each raw input is acquired before the cutoff, and the cutoff is before the game's kickoff. The acquisition time, the URL, the
   publisher's Last-Modified and the file's SHA-256 are recorded in the manifest.
2. The snapshot is built from those files only. Nothing is backfilled after kickoff.
3. The snapshot records every required input, or the missing one is named. The injury report is recorded as present or absent
   for each team, and is not treated as complete when it is absent.
4. The model is locked before kickoff: the commit, the artifact hash, the snapshot hash, the SHA-256 of each batch output, and
   the seed count. The lock is committed and pushed before kickoff.
5. Each game appears once in the readiness manifest, with its schedule and depth verification, injury availability, cutoff, model
   version, connected layers, missing layers, evaluation class and lock status.

## 6. Market comparison cohort

- The Week 5 to 7 games with pre-kickoff market captures (`nfl_line_snapshots`, captured_at before kickoff) form a separate cohort.
- A comparison is made only against a prediction that was genuinely locked before that game. A newly simulated replay is not an
  independent forecast, and no retrospective SLC Brier score is reported as independent.
- Where no locked model prediction exists, the cohort supports a market-only baseline and nothing more.

## 7. Scoring checks (exploratory)

- The scoring calibration (`scoring_calibration_2024.py`, `scoring_compare_2024.py`) compares the engine with the 2024 regular
  season, weeks 2 to 18. Week 1 is excluded because no earlier depth chart exists.
- It is used to find which transition layer drives any gap. It is not used to tune the model on 2026, and it does not establish
  predictive accuracy.

## 8. Stop rules

- The 10,000-seed batch does not start until the connected-layer manifest and the prospective input checks pass.
- No change to dev or main, and no deployment, without explicit approval.
- A model version change after a lock creates a new version and a new lock. The locked forecast is not edited.
