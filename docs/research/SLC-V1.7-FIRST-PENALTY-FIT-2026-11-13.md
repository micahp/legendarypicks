# First V1.7 penalty fit: official-gamebook matched research cohort

**Status: exploratory first fit; not release-ready or population-calibrated.**
The selected-cohort holdout shows a substantial pre-snap calibration gap and
unequal official-match coverage across foul types. The fitted model must not be
used as the V1.7 full-game penalty model until those limitations are resolved.

## Data and validation

Sampled 60 regular-season games, 12 per season from 2021 through 2025, with
four random games in each six-week band per season (seed 170612). Source PBP
and parsed foul clauses were aligned against the actual NFL GSIS gamebooks.
For retained rows, the source description had to match a unique official
scrimmage block at the same quarter and clock, and the official block had to
agree on down, distance, field spot and foul count. Matched foul type, team and
disposition had to pass the source/official checks. This is automated
source-to-official text/state corroboration, not independent officiating
adjudication. [Example official gamebook](https://www.nflgsis.com/2025/REG/07/59949/Gamebook.pdf).

The extraction produces separate pre-snap and live-ball opportunities. A
no-foul label requires an official-matched scrimmage block without a foul; a
pre-snap foul does not create a live-ball opportunity. Nullified dropbacks are
included only where the description supplies evidence of a snap and pass;
unknown play class, multiple fouls, offsetting/ambiguous or unsupported fouls,
missing matches and contradictory states are excluded rather than called clean.
This exclusion is outcome-dependent and can bias the estimated rates.

A 40-record manual check selected from **retained matches**, stratified by five
seasons, accepted/declined, and foul type, plus two no-foul plays per season,
agreed with the official gamebook text in 40/40 cases: 15 accepted, 15 declined,
10 no foul. The exact IDs, official URLs and gamebook hashes are in
`manual-validation-sample.json`. Because the sample was drawn after exact
matching and is small, 40/40 is conditional agreement, **not an unbiased
classification-accuracy estimate** for unmatched or excluded rows.

Among 8,051 eligible source-row candidates, 6,189 (76.9%) matched a unique
official text block; 6,033 source rows passed all inclusion gates. Coverage
varies across labels, which is a material limitation:

| Source-row stratum | Candidate | Official text matched | Included |
|---|---:|---:|---:|
| No parsed foul clause | 7,296 | 5,682 | 5,673 |
| False start, accepted | 138 | 102 | 102 |
| Offensive holding, accepted | 104 | 62 | 35 |
| Offensive holding, declined | 18 | 15 | 15 |
| Defensive holding, accepted | 42 | 28 | 27 |
| Defensive holding, declined | 20 | 17 | 17 |
| Defensive pass interference, accepted | 66 | 42 | 42 |
| Defensive pass interference, declined | 4 | 4 | 4 |
| Defensive offside, declined | 8 | 7 | 7 |
| Multiple clauses | 27 | 20 | 0 |

The manifest contains all source seasons, foul-type/disposition strata and
exclusion counts. Across the sample, 1,862 candidate rows could not be
uniquely matched, 88 had unsupported/uncertain fouls, 39 nullified live plays
had unknown play class, 20 matched rows had multiple fouls, and nine had foul
count disagreement. Counts are at successive gates, not additive independent
population estimates. A further 2,454 rows failed the initial scrimmage
candidate filters.

## Chronological fit and 2025 holdout

The existing `penalty_train.py` fitted the 2021–2024 opportunities, using a
2025-01-01 UTC cutoff; 140 training opportunities were removed because the
gamebook's HTTP Last-Modified was after that cutoff. The held-out cohort is 12
2025 games. The 2026-acquired nflverse extract and schedule were used to align
and classify the official records, so this is a **retrospective** chronological
holdout, not a proven point-in-time forecast. A gamebook Last-Modified time is
not proof of when a particular revision first became available.

Training has 9,614 opportunities (4,871 pre-snap, 4,743 live-ball), with 266
accepted and 43 declined fouls. Holdout has 2,174 opportunities (1,092
pre-snap, 1,082 live-ball), with 34 accepted and 16 declined fouls. Each
opportunity is a phase observation; a snapped play can contribute one to each
phase, so do not interpret these as unique plays.

| Model | Any-foul Brier | Multiclass Brier | Log loss | Mean predicted foul rate |
|---|---:|---:|---:|---:|
| League phase-only | 0.022444 | 0.045416 | 0.153689 | 3.38% |
| Context only | 0.022345 | 0.045357 | 0.156840 | 3.29% |
| Team adjusted | 0.022387 | 0.045351 | 0.155074 | 3.24% |

The observed selected-cohort holdout rate is 50/2,174 = 2.30%. Team-adjusted
pre-snap predictions averaged 2.55% versus 10/1,092 = 0.92% observed;
live-ball predictions averaged 3.94% versus 40/1,082 = 3.70% observed. The
league baseline had the lowest overall log loss; these small samples do not
establish that team effects improve generalization. Since the cohort excludes
unmatched and unsupported events, none of these observed rates establishes
actual NFL all-foul frequency or model calibration on the full opportunity
population.

## Reproducibility

Artifacts are stored outside Git at `/root/slc-v17-penalty-official-cohort-v5/`:
source/gamebook `manifest.json`, raw extracted `train.jsonl`/`holdout.jsonl`,
cutoff-filtered `train-cutoff.jsonl`, `official-evidence.jsonl`, the reviewed
sample, the model and manifest, and `holdout-scores.json`. Gamebook PDFs are
there as local source evidence; large raw data is not committed.

| Artifact | SHA-256 |
|---|---|
| Source manifest | `ee9f042d424799fb7caab5b039a969e4d798b75b8bfd0eaad160385d1931c34d` |
| Cutoff training JSONL | `a7e87a5e4cee08b22b438298595ca8ad922dfec0a4a07677520f77895e9f0cee` |
| Holdout JSONL | `4b7d29e8f05bc8546af1307b9e085797ea0beaa3ac48e0634784e09308bc62c5` |
| Official evidence JSONL | `28bf30260af07bbd355f0e71ce899b245469d1dc85f97951636e4f98018981f2` |
| Manual validation sample | `6c92d080ec4afb8c6a3eb4388ef0c9ea88fbefe8bde7bf46af6bcbb2fceb3ba4` |
| Model JSON file | `bad0fdb71c0afb4095c2bf8de3fd9d413857053657de25b6422e6cd3c087e0e2` |
| Holdout scores | `b1b9f8eca5c8e8820d935e95a73877efdb3f238a91d77df30d3cc23f510e3172` |

The model's canonical content hash reported by its trainer is
`c4f1c9bb863bb4a5b2bf8ae1a815554cb02e9b6cac5c7d7024c441d085211071`;
the file hash differs because the file includes a trailing newline.

`build_verified_penalty_opportunities.py` builds the matched cohort, and
`evaluate_penalty_holdout.py` adds the phase-only control and per-phase
calibration to the existing trainer scores. `label_verified=true` in these
research inputs denotes the documented automated official text/state match;
it is not a claim that each play received an independent human adjudication.
The existing adapter's stricter per-record verification contract has **not**
been met and was not bypassed. Before release, resolve outcome-dependent
coverage, independently audit unmatched strata and no-foul opportunities,
expand game/season coverage, and rerun calibration and full-game validation.
