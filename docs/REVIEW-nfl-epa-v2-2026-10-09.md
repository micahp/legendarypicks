# REVIEW: NFL EPA v2 gate and model-validation design

Reviewed 2026-10-09 on branch `feat/nfl-epa-efficiency` at `e2141c0`, based on
`dev` at `a6921c9`. The review was read-only against
`/root/legendarypicks/backend/data/picks.dev.db`.

## Outcome

**Grade: C-. Block this branch from merge as written.**

The branch honestly reports that its EPA candidate loses to frozen v1, but it also has three
material problems:

1. The implementation is not the model SPEC A section 9 requested. It uses team-game EPA totals,
   not EPA per play split into offense/defense and pass/rush components.
2. The reported 2025 "holdout" refits probability sigma from 2025 outcomes, although SPEC A says
   to carry the 2024 sigma into 2025 unchanged.
3. EPA training games are all marked non-neutral, including the five neutral games in 2024 and
   seven in 2025.

The evidence is against this specific total-EPA post-hoc blend. It is not evidence against a
proper EPA-per-play model, and it is not evidence against the planned later context model.

## Correction after review discussion: what 2025 is for

The initial review said that prospective 2026 grading was the only clean out-of-sample test left.
That was too absolute and framed the work as an ad hoc search among strategies. The original
documents describe a staged model program:

| Version | Information added | Incremental question |
|---|---|---|
| v1 | Scores, opponent adjustment, recency and home field | Does a basic team-strength model work? |
| v2 | EPA-per-play process metrics | Does EPA improve v1? |
| v3 | Coaching, play calling, matchup interactions and availability | Does context improve v2? |

The database contained completed 2024 and 2025 seasons when SPEC A was written, with no 2023 season
loaded. That operational constraint, not a statistical argument, is why the spec assigned 2024 to
development and 2025 to frozen evaluation.

A season is not literally consumed. What is consumed is its role as independent evidence: after a
model is changed because of its 2025 result, the revised model cannot call another score on 2025 an
untouched holdout. The intended sequence remains valid:

1. Develop a fixed architecture using data through 2024.
2. Compare frozen versions on the same 2025 games.
3. After the architectural decision, refit the selected production model through 2025 for 2026.
4. Grade locked 2026 predictions prospectively.

This distinction already exists inside SPEC A. Its validation rule freezes 2024 sigma for the 2025
gate, while its general production description fits sigma from 2024-2025 residuals. Refitting
through 2025 for 2026 is reasonable; doing that and still calling the recalibrated 2025 score a
holdout is not.

The original total-EPA v2 has already received its 2025 test. It should not be altered in response
to the losing games and then retested on 2025 as if the answer were unseen. A separately specified
v3 remains a valid planned model stage, especially because coaching/scheme and availability were in
the methodology before the EPA result. For stronger evidence, backfill earlier seasons and use
rolling-origin folds before the final 2025 comparison.

## Task 1: diagnosis

### 1. EPA and points carry mostly the same information

Final-season ratings, using the configured priors, give:

| Season | Overall Pearson | Spearman | Team-sign agreement | Game-winner agreement |
|---|---:|---:|---:|---:|
| 2024 | 0.9700 | 0.9633 | 31/32 | 228/256 |
| 2025 | 0.9494 | 0.9410 | 31/32 | 222/255 |

Component Pearson correlations:

| Season | Offense | Defense |
|---|---:|---:|
| 2024 | 0.8986 | 0.7170 |
| 2025 | 0.8584 | 0.8728 |

The only final-rating sign disagreements were San Francisco in 2024 and Indianapolis in 2025.

Game correctness:

| Season | Both correct | v1 only | EPA only | Both wrong |
|---|---:|---:|---:|---:|
| 2024 | 155 | 14 | 14 | 73 |
| 2025 | 138 | 19 | 14 | 84 |

EPA usually makes the same call as points. In 2025, its disagreements were net harmful.

2024 v1-only correct:

```text
2024_04_DAL_NYG, 2024_04_DEN_NYJ, 2024_04_LA_CHI, 2024_05_NO_KC,
2024_07_NE_JAX, 2024_07_NYJ_PIT, 2024_10_PIT_WAS, 2024_11_BAL_PIT,
2024_11_WAS_PHI, 2024_12_SF_GB, 2024_13_PHI_BAL, 2024_14_JAX_TEN,
2024_17_TEN_JAX, 2024_18_SF_ARI
```

2024 EPA-only correct:

```text
2024_03_BAL_DAL, 2024_03_CHI_IND, 2024_04_KC_LAC, 2024_04_TEN_MIA,
2024_06_BUF_NYJ, 2024_06_CIN_NYG, 2024_06_WAS_BAL, 2024_07_BAL_TB,
2024_07_DET_MIN, 2024_10_SF_TB, 2024_12_BAL_LAC, 2024_13_LA_NO,
2024_14_CHI_SF, 2024_15_NYJ_JAX
```

2025 v1-only correct:

```text
2025_02_BUF_NYJ, 2025_02_LAC_LV, 2025_02_LA_TEN, 2025_02_TB_HOU,
2025_04_NYJ_MIA, 2025_04_PHI_TB, 2025_04_SEA_ARI, 2025_06_BUF_ATL,
2025_11_TB_BUF, 2025_14_IND_JAX, 2025_14_PHI_LAC, 2025_14_WAS_MIN,
2025_16_JAX_DEN, 2025_16_LA_SEA, 2025_16_TB_CAR, 2025_17_ARI_CIN,
2025_17_CHI_SF, 2025_18_DAL_NYG, 2025_18_GB_MIN
```

2025 EPA-only correct:

```text
2025_05_TB_SEA, 2025_06_SEA_JAX, 2025_07_MIA_CLE, 2025_07_PHI_MIN,
2025_08_BUF_CAR, 2025_09_BAL_MIA, 2025_09_SF_NYG, 2025_11_CHI_MIN,
2025_11_SF_ARI, 2025_12_ATL_NO, 2025_15_BUF_NE, 2025_16_NE_BAL,
2025_17_PHI_BUF, 2025_18_LAC_DEN
```

### 2. Selection explains some optimism, not the entire 2024 result

For the chosen EPA structure (`epa_half_life=12`, `epa_cap=14`), shrinking the blend weight gives:

| Weight | 2024 Brier | 2025 Brier, 2024 sigma | Pooled retrospective |
|---:|---:|---:|---:|
| 0.000 | 0.222452 | **0.228811** | 0.225606 |
| 0.025 | 0.222110 | 0.228825 | 0.225440 |
| 0.100 | 0.221124 | 0.228901 | 0.224979 |
| 0.200 | 0.219905 | 0.229083 | 0.224453 |
| 0.400 | 0.217802 | 0.229726 | 0.223702 |
| 0.600 | **0.216148** | 0.230738 | **0.223349** |

Every positive tested weight makes strict 2025 Brier worse, monotonically. A tiny weight removes
most of the harm but also removes nearly all incremental value.

Additional checks:

- Pooled retrospective selection picks `w=.5, epa_half_life=6, epa_cap=14` under the registered
  tie rule: Brier `0.223311`.
- Tune on 2024 weeks 2-9, evaluate weeks 10-18: blend Brier `0.199754` versus v1 `0.201021`, but
  blend margin MAE is worse (`10.123` versus `9.920`).
- Reverse sensitivity, tuning on 2025, picks `.5/3/14`: `0.228368` versus v1 `0.228736`. Applied
  backward to 2024 it scores `0.218539` versus `0.222459`. This is diagnostic, not a chronological
  holdout: the 2025 fit uses a 2024 prior and the evaluation runs backward.
- Leave-one-week-out 2024 selection chose weight `.6` in 15 of 17 runs and `.5` in two. One
  anomalous week does not explain the high 2024 weight.
- Week-clustered paired bootstrap, blend minus v1:
  - 2024: `-0.006305`, 95% interval `[-0.012863, +0.000053]`.
  - Strict 2025: `+0.001927`, 95% interval `[-0.002543, +0.006420]`.

The 2024 signal survives shrinkage and an internal temporal split, so it is wrong to call it purely
grid-selection noise. It is statistically marginal, highly redundant with v1 and does not transport
to 2025.

### 3. Small-sample EPA noise is not the main explanation

Pure EPA-margin residual sigma versus v1, pooling the same week across 2024 and 2025:

| Week | n | v1 sigma | EPA sigma | EPA - v1 |
|---:|---:|---:|---:|---:|
| 2 | 32 | 11.7892 | 11.8466 | +0.0574 |
| 3 | 32 | 16.5135 | 16.8196 | +0.3061 |
| 4 | 32 | 13.4087 | 13.3471 | -0.0616 |
| 5 | 28 | 13.3828 | 13.8204 | +0.4376 |
| 6 | 29 | 12.7328 | 12.3012 | -0.4316 |
| 7 | 30 | 14.5377 | 14.1883 | -0.3494 |
| 8 | 29 | 14.9719 | 14.9343 | -0.0377 |
| 9 | 29 | 12.1559 | 11.5802 | -0.5757 |
| 10 | 28 | 11.6706 | 11.8703 | +0.1997 |
| 11 | 29 | 13.0024 | 12.6201 | -0.3824 |
| 12 | 27 | 11.2814 | 11.4712 | +0.1898 |
| 13 | 32 | 10.7723 | 11.7060 | +0.9337 |
| 14 | 27 | 12.5422 | 12.8692 | +0.3270 |
| 15 | 32 | 11.4134 | 10.6117 | -0.8017 |
| 16 | 32 | 12.7295 | 13.3650 | +0.6355 |
| 17 | 32 | 14.1738 | 14.3302 | +0.1564 |
| 18 | 32 | 12.7119 | 12.6401 | -0.0718 |

```text
Weeks 2-4:  v1 14.9820, EPA 15.1322, delta +0.1502
Weeks 5-18: v1 12.9573, EPA 12.9701, delta +0.0128
```

The early EPA fit is only slightly noisier. Small-sample residual noise does not explain the
out-of-sample reversal.

### 4. Evaluation and implementation defects

#### The reported 2025 calculation refits sigma from 2025

`nfl_epa_efficiency.evaluate()` calls `with_sigma()` independently for every evaluated season.
SPEC A requires the 2024 residual sigma to be applied unchanged to 2025.

| Evaluation | Blend Brier | v1 Brier |
|---|---:|---:|
| Report-style, own 2025 sigma | 0.230376 | 0.228736 |
| Strict, frozen 2024 sigma | 0.230738 | 0.228811 |

The gate still fails. The issue changes the interpretation, not the verdict.

#### Neutral-site training bug

`epa_games()` hardcodes `neutral=False`. The dev database has five scored neutral regular-season
games in 2024 and seven in 2025. Correcting that in memory gives:

```text
2024 Brier: 0.216148 -> 0.216805; MAE: 10.4601 -> 10.4928
2025 Brier: 0.230376 -> 0.230303; MAE: 10.7457 -> 10.7424
maximum projection movement: 0.812 points
```

The bug does not explain the failure, but it is a merge-blocking correctness issue. Every synthetic
schedule fixture uses `location=None`, so the nine tests cannot catch it.

#### The model does not implement SPEC A section 9

SPEC A asks for EPA per play, with offense/defense and pass/rush components. The branch sums
offensive EPA into team-game totals and feeds those totals into the points-model shape. It computes
play counts but does not use them. Opponent defense is implicit in the ridge fit, but per-play
normalization and pass/rush components are absent.

Current retained and selected rows:

| Season | PBP rows | Non-null EPA | Model-selected plays |
|---|---:|---:|---:|
| 2024 | 47,274 | 46,730 | 33,947 |
| 2025 | 46,452 | 45,908 | 33,455 |
| 2026 | 11,327 | 11,197 | 8,058 |

Only about 73% of non-null EPA plays enter the model. The selected definition includes sacks,
two-point attempts, kneels and one `no_play` in each completed season. That may or may not be the
right football definition; it must be explicit and validated rather than hidden behind the null-EPA
count.

#### Other errors and gaps

- The result report's 2025 margin MAE of `10.73` is not reproducible from the current branch and
  current dev DB. The current value is `10.7457`, which rounds to `10.75`; neutral-corrected output
  rounds to `10.74`.
- Both prior loads catch every `ValueError` and silently continue without a prior. Malformed prior
  data is therefore indistinguishable from an intentionally absent season.
- No week-ahead projection leakage was found. The week-3 planted-EPA fixture passes, and live reads
  restrict each fit to earlier weeks.

## What a defensible v2 and v3 look like

The next EPA candidate should be a fixed architectural version, not a holdout-driven search for a
blend that erases the losing games:

- offense and defense EPA per play;
- pass and rush components;
- regression by play/opportunity count;
- the same walk-forward cutoff as v1;
- sigma frozen from the development window for each evaluation window;
- identical game rows and scoring for v1 and v2.

The planned context version should then add pregame-only information. A Vikings pressure matchup,
for example, should combine expected defensive pressure/blitz tendency, offensive-line pressure
allowed, quarterback performance under pressure, the offense's play-calling response and the
availability of the relevant rushers, defensive backs and offensive linemen.

Availability cannot be a raw count of absent defenders. It should weight expected snaps lost,
position, role, starter/replacement quality and whether the absences create a concentrated unit
weakness the opponent can attack.

Coaching should be represented primarily through regime-aware tendencies such as neutral pass rate,
early-down pass rate, pace, play action, blitz rate and fourth-down aggressiveness. The model must
measure only context that adds information beyond team results and EPA, or it will double-count the
same team quality.

The schedule already stores coach names, and the dev DB has injury reports, snap counts and depth
charts. It does not yet have SPEC B's `player_game_availability` table. The retained `nfl_pbp` schema
also lacks a direct pressure/blitz field; sacks alone are not a complete pressure measure. A source
audit is required before claiming that matchup can be modeled.

For stronger development evidence, ingest earlier seasons and run rolling-origin comparisons on the
same games. Freeze each version before its next-season fold, retain 2025 as the common comparison for
the frozen versions, then refit the selected architecture through 2025 for 2026 production.

## Task 2: adversarial grade

### Credit

- Published play-level EPA is copied rather than recomputed.
- Team vocabulary is normalized at the ingest boundary.
- The current dev DB has zero duplicate PBP keys and zero schedule-orphan PBP rows.
- The failed gate was reported rather than disguised as adoption.
- The base SHA is stated and correct.
- Nine targeted synthetic tests pass.

### Deductions

1. **Major: A9 model contract not implemented.** Totals replace per-play rates; pass/rush
   components are absent.
2. **Major: holdout protocol violated and mislabeled.** Sigma is refitted from 2025 outcomes.
3. **Major: neutral-site correctness bug.**
4. **Major: required audit trail omitted.** SPEC A says every tried configuration goes to
   `model_runs`. A rejected status would not imply adoption.
5. **Done-report contract incomplete.** Fixtures are identified as synthetic, but there is no
   fixture-to-real-payload comparison, explicit uncovered-state inventory or complete inventory of
   other readers and external callers.
6. **Published-first only partially satisfied.** Published EPA is retained, but the derived filter
   and aggregation have no published comparator, immutable source artifact/checksum or exact
   snapshot replacement.
7. **Production impact understated.** `scripts/nfl-availability.sh` loops DEV and PROD. The installed
   weekly timer points at that script, while the production DB currently has no `nfl_pbp` table.
8. `INSERT OR REPLACE` is not exact-snapshot idempotence. If nflverse removes a row from a rewritten
   season file, the stale local row remains.

## Merge blockers

- Fix neutral handling.
- Evaluate the gate with 2024 sigma frozen into 2025, and distinguish that gate from a final
  2024-2025 production refit.
- Do not label the current implementation SPEC A9. Implement per-play/pass-rush EPA or label it an
  experimental total-EPA blend.
- Correct the result report's 2025 status and margin MAE.
- Record attempted configurations with explicit experimental/rejected statuses.
- Do not merge the timer wiring without an explicit production rollout decision, exact source
  reconciliation and stale-row behavior test.
- Add a real-data neutral-site test and failure tests for malformed prior data and rewritten-source
  row deletion.

## Reproduction evidence

Required grid:

```bash
cd /root/lp-nfl-epa/backend
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
  /root/legendarypicks/backend/venv/bin/python nfl_tune_epa.py
```

Material output:

```text
chosen: w=.6, epa_half_life=12, epa_cap=14
Brier .2161, log loss .6228, margin MAE 10.46
v1 Brier .2225, log loss .6362, margin MAE 10.49
```

Targeted tests:

```bash
cd /root/lp-nfl-epa
PYTHONDONTWRITEBYTECODE=1 \
  /root/legendarypicks/backend/venv/bin/python \
  -m pytest -q backend/test_nfl_epa_efficiency.py
```

```text
.........                                                                [100%]
9 passed in 0.61s
```

Data-shape checks:

```text
duplicate (season, game_id, play_id) keys: 0
PBP rows with no schedule game_id:       0
neutral scored REG games:                2024=5, 2025=7, 2026=3
```

Release-surface checks:

```text
installed ExecStart=/root/legendarypicks/scripts/nfl-availability.sh
installed OnCalendar=Tue *-*-* 09:30:00 America/Chicago
installed Persistent=true
dev DB nfl_pbp rows=105053
prod DB nfl_pbp table=absent
```

Review worktree status before writing this document:

```text
HEAD e2141c0a4fde8fa94eb94e9a963566127be0570b
base a6921c9d43faa7a8602454203bad92bb38cae907
untracked CODEX-TASK-epa-review.md (left untouched)
```
