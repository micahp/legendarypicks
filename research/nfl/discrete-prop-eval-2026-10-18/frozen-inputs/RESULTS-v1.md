# RESULTS: NFL rushing carries distribution v1

Measured 2026-10-17 on `picks.dev.db` (read-only for every grade), branch
`feat/nfl-rushing-carries-dist-v1` from `scratch/spec-b-rebase`. Pre-registration:
`docs/SPEC-nfl-rushing-carries-dist-v1.md`.

## Verdict: NOT_ADOPTED

The candidate misses the pre-registered gate. Modeling participation and carry-count uncertainty
**does** lower CRPS, and the improvement is established in both seasons, but the resulting distribution
is **too wide**: 50/80/90% coverage moves away from nominal in both seasons, in every comparison. Two of
the three gates pass; the coverage gate fails decisively, so the candidate is not adopted into Spec B.
It is frozen as a research candidate for prospective confirmation only.

## What was tested

Spec B projects a carry mean conditional on the player appearing and publishes `p_plays` beside it, but
has **no carry-count distribution** for rushing. Four analytic distributions, all anchored on the frozen
Spec B carry mean `m` (point estimates never moved):

| id | distribution | what it adds |
|---|---|---|
| B0 | `NB(m, R)` | the incumbent shape |
| B1 | `(1-p)[0] + p NB(m, R)` | participation |
| B2 | `(1-pq)[0] + pq ZTNB(m/q, R_t)` | participation + role-aware hurdle |
| B2' | `(1-q)[0] + q ZTNB(m/q, R_t)` | hurdle only, played subset (attribution) |

Population: every Spec B candidate with `m > 0`, weeks 3-18, RB and FB (FB folded into RB), with QB
reported separately and not gated. Outcome is the box-score `carries`, **0 when he has no box-score
row**, so inactive games are in the population. No post-game filter. Paired CRPS intervals are
clustered by game.

### The target, audited first

`backend/audit_nfl_rushing_attempts.py` reconciles weekly `carries` with `nfl_pbp` per player-game,
all 17 seasons 2010-2026 (26,740 RB player-games, 10,059 QB player-games, 190,388 RB carries):

- Weekly `carries` **includes quarterback kneels** and **excludes two-point tries**. Remove two-point
  rushing plays and the two sources agree **exactly on every player-game**: 0 mismatches in all 34
  season-position groups, and 0 rows with carries but no play-by-play rushing play in either direction.
- QB carries are not RB carries: **43.9% of QB carries are scrambles and 21.3% are kneels**, against 0%
  of either for running backs (1 scramble in 190,388 RB carries). That is why QB is out of the gate: a designed run, a broken play and a
  victory formation are three different processes collapsed into one count.

## Fitted parameters (forward only)

| eval season | fit seasons | R | q (m<3 / 3-8 / >=8) | R_t | p (none / Q / Out / Doubtful) |
|---|---|---|---|---:|---|
| 2025 holdout | 2024 | 3.254 | 0.529 / 0.879 / 0.993 | 5.00 | 0.912 / 0.600 / 0 / 0 |
| 2026 development | 2024-2025 | 3.657 | 0.539 / 0.904 / 0.997 | 5.00 | 0.913 / 0.635 / 0 / 0 |

`R_t` sits on the highest grid value in both fits, so the truncated component wants more dispersion than
the grid allowed. That is the first symptom of the over-dispersion the coverage gate then measures.

Participation can only be fitted where the availability table exists (2024 onward). The 2025 holdout
therefore rests on a one-season parameter fit; that is a data limitation, not a choice.

## 2025 holdout (fit 2024)

2,500 candidate-games over 240 games; 1,966 played, and 244 have no availability row at all.
Designations: 2,317 none, 96 Out, 80 Questionable, 7 Doubtful. **534 candidates did not play. Of those,
only 110 carry a designation** (80 Out, 25 Questionable, 5 Doubtful), 180 are undesignated and 244 are
absent from the availability table, so the injury report identifies 21% of the non-participation.

### All pregame candidates (n = 2,500)

| model | CRPS | cov50 | cov80 | cov90 | MAE | bias | Brier(any) | AUC(any) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 2.0604 | 0.546 | 0.819 | 0.910 | 2.9401 | +0.038 | 0.2376 | 0.7833 |
| B1 | 1.9533 | 0.636 | 0.896 | 0.949 | 2.7485 | -0.639 | 0.1854 | 0.8271 |
| B2 | **1.9093** | 0.713 | 0.914 | 0.955 | 2.7868 | -0.517 | 0.1700 | 0.7976 |

Paired CRPS against B0, clustered by game: B1 **-0.1071 +/- 0.0380**; B2 **-0.1511 +/- 0.0381**.

### RB only (n = 1,714) and QB, not gated (n = 786)

| subset | model | CRPS | cov50 | cov80 | cov90 | MAE | bias |
|---|---|---:|---:|---:|---:|---:|---:|
| RB | B0 | 2.4087 | 0.538 | 0.798 | 0.894 | 3.3661 | -0.240 |
| RB | B1 | 2.3241 | 0.607 | 0.879 | 0.942 | 3.2063 | -1.020 |
| RB | B2 | 2.2639 | 0.667 | 0.889 | 0.940 | 3.2443 | -0.902 |
| QB | B0 | 1.3008 | 0.565 | 0.865 | 0.945 | 2.0113 | +0.643 |
| QB | B1 | 1.1447 | 0.698 | 0.934 | 0.966 | 1.7503 | +0.190 |
| QB | B2 | 1.1359 | 0.812 | 0.968 | 0.989 | 1.7891 | +0.321 |

Paired against B0: RB B2 -0.1448 +/- 0.0515; QB B1 -0.1561 +/- 0.0400, QB B2 -0.1649 +/- 0.0411.
QB is the subset where the hurdle would actually ship, but the gate is RB and the coverage failure is
the same there.

### Played only (n = 1,966) — the attribution table

| model | CRPS | cov50 | cov80 | cov90 | MAE | bias |
|---|---:|---:|---:|---:|---:|---:|
| B0 | 2.0772 | 0.613 | 0.862 | 0.934 | 2.8211 | -0.870 |
| B1 | 2.1898 | 0.640 | 0.875 | 0.935 | 2.9201 | -1.388 |
| B2 | 2.1549 | 0.700 | 0.899 | 0.943 | 2.9387 | -1.263 |
| B2' | 2.0460 | 0.686 | 0.901 | 0.944 | 2.8508 | -0.731 |

Paired: B1 +0.1126 +/- 0.0138, B2 +0.0776 +/- 0.0152, **B2' -0.0312 +/- 0.0095**.

This is the cleanest result in the experiment. Once the population is restricted to games he actually
played, the participation mixture is **harmful** (it puts zero mass on games that were played), and the
hurdle alone is a small, established improvement. Participation and count shape are two separate
mechanisms and only the second one works conditionally.

### Early weeks (3-5, n = 462)

B0 2.0350, B1 1.9260, B2 1.8653; paired B2 -0.1697 +/- 0.0773. Coverage 0.535 -> 0.712 at 50%.

## 2026 development (fit 2024-2025), weeks 3-6

489 candidate-games over 48 games; 272 played. Of the 217 who did not play, 14 carry a designation row
and 203 have no availability row at all (the 2026 table is only partly loaded). This season is
**explored development evidence**, not a fresh test.

| subset | model | CRPS | cov50 | cov80 | cov90 | MAE | bias |
|---|---|---:|---:|---:|---:|---:|---:|
| all | B0 | 2.0887 | 0.491 | 0.816 | 0.896 | 2.9972 | +0.122 |
| all | B1 | 2.0017 | 0.573 | 0.912 | 0.959 | 2.8902 | -0.474 |
| all | B2 | 1.9764 | 0.685 | 0.912 | 0.963 | 2.9330 | -0.343 |
| RB | B0 | 2.3710 | 0.493 | 0.791 | 0.883 | 3.3630 | -0.012 |
| RB | B2 | 2.2753 | 0.628 | 0.908 | 0.960 | 3.3526 | -0.546 |
| played | B0 | 2.0511 | 0.585 | 0.857 | 0.930 | 2.8504 | -0.597 |
| played | B2' | 2.0583 | 0.684 | 0.849 | 0.960 | 2.8975 | -0.451 |

Paired against B0: all B1 -0.0871 +/- 0.0666, all B2 -0.1123 +/- 0.0714, RB B2 -0.0957 +/- 0.0752,
played B2' **+0.0072 +/- 0.0337**. Weeks 3-5 alone: B2 -0.1159 +/- 0.0723 and coverage 0.483 -> 0.681.

The 2026 season reproduces the 2025 pattern on CRPS and on coverage, and it **does not** reproduce the
conditional hurdle gain: on played games B2' is a wash. The one established piece of count-shape
evidence is therefore one season old, not two.

## Gate, evaluated as pre-registered

| # | criterion | 2025 | 2026 | result |
|---|---|---|---|---|
| 1 | CRPS lower, paired game-clustered interval excludes zero | -0.1511 +/- 0.0381 | -0.1123 +/- 0.0714 | **pass** |
| 2 | 50/80/90 coverage closer to nominal than B0 | 0.213/0.114/0.055 worse | 0.185/0.112/0.063 worse | **fail** |
| 3 | MAE no worse by more than 0.02 | -0.153 better | -0.064 better | **pass** |

Coverage deviations from nominal, absolute: 2025 B0 0.046/0.019/0.010 against B2 0.213/0.114/0.055;
2026 B0 0.009/0.016/0.004 against B2 0.185/0.112/0.063. The incumbent's intervals are already close to
nominal; the candidate moves them away at every level in both seasons. Because the rule required **all**
criteria, the verdict is NOT_ADOPTED and the workstream moves on.

## Why coverage fails while CRPS improves

- A 30-40% zero mass applied uniformly across candidates is the wrong shape for a per-item interval. For
  a Questionable starter the conditional distribution is a full workload; the mixture bolts a large
  zero probability onto it and the central 50% band then spans zero plus the upper tail.
- This is not simple under-dispersion. Mean predictive sd is 3.43 (B0) and 3.59 (B2) against a pooled
  observed sd of 6.24 on 2025. Both are far below the marginal spread, and B2 still over-covers
  per item: coverage is a per-item property, and the pooled sd is dominated by the mix of starters and
  backups, not by within-player uncertainty.
- `R_t` choosing the top of its grid in both fits says the same thing from the other side: the truncated
  component is being asked to carry dispersion the mixture created.
- The participation signal itself is coarse. `p` is a four-level function of the injury designation, and
  **only 110 of 534 non-participants in 2025 carried a designation**; the other 424 (180 undesignated,
  244 with no availability row) all take p = 0.912. The mechanism that improves CRPS is real; the
  information behind it is thin, and it is applied almost uniformly rather than individually.

Discrimination of `P(carries >= 1)` tells the same story: Brier improves (0.2376 -> 0.1700 in 2025,
0.2495 -> 0.1898 in 2026) but AUC does not (0.7833 -> 0.7976, 0.7591 -> 0.7582). The layer is better
calibrated, not better informed.

## What this means for Spec B, and what it does not

- Do **not** ship the hurdle. It improves a proper score and breaks interval calibration.
- The participation layer is worth keeping in view for the point estimate, but not as implemented. On
  the pregame population it improves MAE by 0.19 (2025) and 0.11 (2026) carries; restricted to games
  he played, it is harmful. So the result answers a **pricing** question, not a projection question: if
  the served number is a bet that is voided when he does not play, participation must stay out of the
  mean; if the served number is an unconditional carries forecast, it belongs in.
- Neither candidate touches rushing efficiency. `rush_yds` and `rush_td` were not simulated here, so the
  downstream carries-to-yards question in step 5 of the plan is **not** opened.

## Frozen candidate and prospective confirmation

`docs/frozen-nfl-rushing-carries-dist-v1.json` holds the frozen B2 parameters (fit on 2024-2025) and is
the only parameter set the prospective run may use. Status: `RESEARCH_CANDIDATE_ONLY`, not adopted.

The prospective window is **2026 weeks 7-18**, games not played as of 2026-10-17. Grade once the weeks
are complete, with no refit:

```bash
cd backend
export LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db
python3 nfl_rushing_carries_dist_v1.py --eval-season 2026 --fit-seasons 2024 2025 \
    --weeks 7 18 --frozen ../docs/frozen-nfl-rushing-carries-dist-v1.json \
    --json ../../rush_prospective_2026_wk7_18.json
```

This is the only genuinely new evidence for this candidate. 2026 weeks 3-6 are development evidence and
must not be re-used as confirmation; 2025 has now been used as a holdout once and cannot confirm a
re-specified model.

## Next facet: individualised participation

The experiment isolates where the loss is. The next candidate is not another count distribution; it is a
better participation model:

1. Replace the four-level designation rate with `P(plays)` from recent form (Spec B's own
   `recent_form` table) crossed with designation, fitted forward on 2024-2025. That can distinguish the
   424 of 534 non-participants the designation misses.
2. Fit a single-inflation zero-inflated NegBin (`P(0)` free, count component untruncated) instead of the
   full hurdle, so the zero mass is a fitted parameter rather than the product of two probabilities.
3. Grade coverage at 50/80/90 as the **primary** gate and CRPS as the secondary, because this experiment
   showed a CRPS gain that degrades calibration.

## Reproducing

```bash
cd backend
export LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db
python3 audit_nfl_rushing_attempts.py --seasons 2010 2011 2012 2013 2014 2015 2016 2017 2018 \
    2019 2020 2021 2022 2023 2024 2025 2026
python3 nfl_rushing_carries_dist_v1.py --eval-season 2025 --fit-seasons 2024 --json rush_2025.json
python3 nfl_rushing_carries_dist_v1.py --eval-season 2026 --fit-seasons 2024 2025 --json rush_2026.json
```

Runtime is about 6-7 seconds per evaluation season. Both scripts are read-only against `LP_DB_PATH` and
need only sqlite3 and the standard library.
