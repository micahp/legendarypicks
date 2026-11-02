# Substitution gap, root cause (2026-11-02)

Status: research only. Not wired into the simulator. Fit on 2022 to 2024. Scored on the 2025 holdout, which was
previously exposed and is used here as retrospective evaluation only. No parameter was tuned to 2025.

Sources: `outputs/substitution_gap_diagnostic_2025.json` (diagnose_substitution_gap.py),
`outputs/candidate_substitution_2025.json` (candidate_substitution.py). Field: `field_2022_2024.json`, sha256
`8f555979fe6ba08f37f926c2a9fb93d52998722e1fa55ad706250a5b52d5d0e9`.

## Definitions (identical on both sides)

- A pair is two consecutive offensive snaps by the same team in the same game. The observed and simulated sides are
  built from the same team-game keys, with the same pairs (asserted per team-game per seed).
- Clean pair: both snaps match their own listed grouping (the listed skill-position counts equal the grouping's counts).
- Entries: skill players on the second snap who were not on the first.
- Drive boundary: the play-by-play drive number changes between the two snaps. Three holdout snaps have no drive id.
- Observed pairs: 29,531 clean and 4,374 contradicting (33,905 total, 570 team-games). The simulated arms use three seeds,
  so the model rows are 3 times these counts (88,593 clean, 101,715 total).

## 1. Histograms, entries per pair (0, 1, 2, 3, 4+)

Clean pairs, forced grouping (observed grouping given on each snap):

| | 0 | 1 | 2 | 3 | 4+ | entries/pair |
|---|---|---|---|---|---|---|
| Observed 2025 | 0.263 | 0.317 | 0.275 | 0.120 | 0.026 | 1.331 |
| Model (forced) | 0.237 | 0.416 | 0.272 | 0.069 | 0.006 | 1.191 |
| Model (free) | 0.239 | 0.418 | 0.268 | 0.068 | 0.007 | 1.186 |

All pairs, forced: observed 1.395, model 1.214. Free: model 1.190.

Shape: the model is close on zero-entry pairs (unchanged lineups, 0.24 against 0.26 clean). It over-produces one-entry
pairs and under-produces the tail: three or more entries is 0.146 observed against 0.075 model.

## 2. Decomposition of the gap

The all-pairs gap (forced) is 0.181 entries per pair (free: 0.205, the figure the paste quotes as 0.21). Factors overlap,
so the shares below are within each factor only, not additive across factors.

| Factor | Stratum | Share of pairs | Observed | Model (forced) | Contribution to gap |
|---|---|---|---|---|---|
| Label validity | clean | 87.1% | 1.331 | 1.191 | 0.122 |
| | contradicting | 12.9% | 1.827 | 1.368 | 0.059 |
| Drive boundary | same drive | 84.6% | 1.318 | 1.199 | 0.100 |
| | new drive | 15.4% | 1.818 | 1.293 | 0.081 |
| Package change | grouping changed | 44.3% | 2.013 | 1.714 | 0.132 |
| | grouping held | 55.7% | 0.905 | 0.817 | 0.049 |
| Position group (all pairs) | RB | | 0.338 | 0.316 | 0.022 |
| | TE | | 0.437 | 0.397 | 0.040 |
| | WR | | 0.620 | 0.500 | 0.120 |

Within clean pairs only, the gap is 0.140 (10.5%). The position split of that is WR 0.094 (67%), TE 0.026, RB 0.020.

The drive boundary is the largest structural factor. On clean pairs, a new drive has 1.770 observed entries per pair
against 1.277 modelled. Same-drive pairs are 1.252 against 1.176. New drives are 15% of clean pairs but carry about half
the clean gap (roughly 0.075 of 0.140). The per-season observed figure for new drives is stable across 2022 to 2025 (1.73
to 1.77), so this is structural, not drift.

Stint: on clean pairs, the model leaves less often than observed at stints 1 to 5 and more often at stint 6 and over
(for example WR stint 1: 0.317 against 0.371 observed; WR stint 6: 0.114 against 0.105). The model holds long-stint
players too long, which feeds back into the churn rate.

## 3. Exclusion ledger, 2025 (34,475 snaps)

| Category | Snaps | Share | What it means |
|---|---|---|---|
| consistent | 31,692 | 91.9% | listed skill mix equals the grouping |
| missing_skill_labels | 2,214 | 6.4% | fewer than five skill-labelled players; the lineup cannot be read from labels |
| five_labels_wrong_position_mix | 481 | 1.4% | five labelled players, mix differs from grouping: valid players with differing listed positions |
| extra_skill_labels | 88 | 0.3% | more than five labelled skill players |

Total inconsistent: 8.1%. Contradicting pairs carry more churn (1.83 observed entries per pair against 1.33 clean), so the
8% inflates the observed gap rather than adding noise.

The ledger separates the 1.4% (valid players, differing labels) from the 6.4% (unlabelled lineups). It cannot yet say
whether the 6.4% are invalid lineups or valid players whose labels are missing; that needs roster identity for those snaps.
Largest inconsistent groupings: 11 (1,040 snaps), 12 (841). Teams with most: JAX 406, NE 310, PIT 253, HOU 233, NO 215.

## 4. Remaining gap on the clean population

Clean, forced: observed 1.331, model 1.191, gap 0.140. By drive: new drive 0.493 gap, same drive 0.076 gap. Package
frequencies match by construction in the forced arm (grouping is given). Multi-class change: observed 0.337 of clean
pairs, model 0.250. Unchanged lineup: observed 0.263, model 0.237.

## 5. Structural audit of the single swap pass

From `scripts/nfl_sequence/participation_field.py` `advance`:

- Rotation (the stint hazard) applies only in classes whose count holds.
- A class whose count changes gets one churn draw per on-field player, at a single rate per class (`leave_prob('swap', cls, 0)`).
  That rate ignores stint, drive boundary and other classes.
- Surplus removal uses stint hazard weights. The deficit is filled from the bench by per-player rate.
- Each class is drawn independently, so simultaneous multi-class churn is only the product of small rates.

Consequences:
- No stint dependence in changed classes.
- No drive-boundary input.
- No joint structure across classes. The triple swap 11→11 (RB, TE and WR each swap one player) is observed at 1.94% of
  clean pairs against 0.55% modelled.

The per-class runtime rate is not affected by the fitting issue below: its total excess matches the total regardless
of how it is allocated. The problem is only in splitting it by stint. My first candidate fit allocated count-change
departures across stints in proportion to players, which gives negative stint rates (TE stint 6: -0.098; WR stint 6:
-0.025). Departures from a falling class are chosen by stint-weighted hazard, so that allocation is wrong. The candidate
below fits stint rates only on rising classes, where there are no count-change departures.

## 6. Five largest missing signatures (clean, forced)

Ranked by contribution to the entries gap. Observed support is 572 clean pairs in 2025 (share 1.94% of 29,531).

| Signature (grouping > grouping \| class changes) | Observed share | Model share | Contribution |
|---|---|---|---|
| 11>11 \| RB:-1+1 TE:-1+1 WR:-1+1 | 1.94% | 0.55% | +0.042 |
| 11>11 \| TE:-1+1 WR:-1+1 | 2.80% | 1.83% | +0.019 |
| 11>12 \| RB:-1+1 TE:-0+1 WR:-2+1 | 0.75% | 0.13% | +0.018 |
| 11>12 \| TE:-0+1 WR:-1+0 | 4.06% | 6.00% | -0.019 |
| 11>11 \| WR:-1+1 | 5.96% | 7.88% | -0.019 |

The two negative rows are signatures the model over-produces: single-WR swaps, and a single WR-for-TE change at 11→12.
The missing signatures are coordinated multi-class changes, which the single swap pass cannot produce.

Drive-boundary sub-split (clean, observed, from a scratch analysis): at a new drive, 51% of pairs have multi-class
change against 31% within a drive; the triple 11→11 swap is 3.7% against 1.6%; unchanged lineup is 9% against 29%.

## 7. Candidate tests (fit 2022 to 2024, scored on 2025)

Candidate script: `candidate_substitution.py`. Variants: B0 is the runtime mechanics and must reproduce validate_lineups.py
(B0 clean forced: 1.1912, matching the diagnostic). Everything else is research-only and not in `scripts/`.

- S, stint-dependent swap: churn rate per stint bucket in changed classes, fit on rising classes only.
- D, drive-boundary split: separate hazards at a new drive.
- J, joint leaver counts: each snap draws how many players leave from each class together, from the 2022 to 2024
  distribution for the same grouping transition. Which players leave is stint-weighted. Transitions with fewer than 30
  weighted pairs fall back to per-player draws. 30 is a support threshold set before the run, not tuned.
- JD: J with the drive-boundary split.

Results on the forced arm (clean pairs; observed 1.331, multi-class 0.337, same drive 1.252, new drive 1.770):

| Variant | Entries/pair | Multi-class | Same drive | New drive | Unchanged |
|---|---|---|---|---|---|
| B0 runtime | 1.191 | 0.250 | 1.176 | 1.277 | 0.237 |
| S stint swap | 1.218 | 0.257 | 1.201 | 1.308 | 0.240 |
| D drive split | 1.192 | 0.250 | 1.122 | 1.584 | 0.241 |
| SD both | 1.216 | 0.257 | 1.138 | 1.650 | 0.241 |
| J joint | 1.306 | 0.329 | 1.278 | 1.466 | 0.279 |
| JD joint + drive | 1.309 | 0.329 | 1.224 | 1.782 | 0.278 |

Reading:
- Stint-dependent swap closes about a fifth of the clean gap and does nothing for new drives. It is a real but small effect.
- The drive split alone moves churn toward new drives but pulls same-drive churn down, because hazards fitted on same-drive
  pairs underpredict once the stint distribution feeds back. It does not improve the total.
- The joint leaver-count model closes about 90% of the clean gap, and matches the multi-class share (0.329 against 0.337),
  the unchanged share and the 3+ tail. JD matches both drive strata within 0.03.

Caveats on J and JD:
- Out of sample on counts: the table is fit on 2022 to 2024 and scored on 2025. The grouping transitions are observed in
  the forced arm, so the match tests stability of the leaver-count distribution across seasons, not the transition model.
- Who leaves is not validated. The stint weighting is the same as the runtime's, and I have not tested player-level
  replacement.
- Fallback covers about 5% of simulated snaps (5,325 of roughly 103,000 per run), mostly rare transitions.

Free-grouping arm (the grouping is also drawn by the model; clean pairs; observed 1.331, RB 0.329, TE 0.414, WR 0.589):

| Variant | Entries/pair | RB | TE | WR | Multi-class | Unchanged | 3+ share | Same drive | New drive |
|---|---|---|---|---|---|---|---|---|---|
| B0 runtime | 1.186 | 0.306 | 0.374 | 0.506 | 0.249 | 0.239 | 0.075 | 1.183 | 1.205 |
| S stint swap | 1.222 | 0.321 | 0.387 | 0.514 | 0.258 | 0.234 | 0.086 | 1.220 | 1.231 |
| D drive split | 1.194 | 0.307 | 0.374 | 0.513 | 0.250 | 0.239 | 0.077 | 1.132 | 1.539 |
| SD both | 1.214 | 0.317 | 0.386 | 0.511 | 0.257 | 0.239 | 0.086 | 1.151 | 1.561 |
| J joint | 1.313 | 0.334 | 0.414 | 0.566 | 0.335 | 0.274 | 0.145 | 1.304 | 1.363 |
| JD joint + drive | 1.313 | 0.332 | 0.414 | 0.566 | 0.333 | 0.271 | 0.142 | 1.244 | 1.696 |

Observed: multi-class 0.337, unchanged 0.263, 3+ share 0.146, same drive 1.252, new drive 1.770.

Reading, free arm: JD matches observed RB and TE within 0.003 and leaves WR 0.023 (4%) short, against 0.083 for B0. It
reproduces the multi-class share (0.333 against 0.337), the unchanged share (0.271 against 0.263) and the 3+ tail (0.142
against 0.146). Its new-drive entries are 1.70 against 1.77 observed; same drive is 1.24 against 1.25. Bench shortfalls are
rare (54 to 250 snaps per run against 183 for B0). Joint-table fallback is about 4% of simulated snaps (3,721 to 4,860 per run).

Forced-arm per-class (clean): JD gives RB 0.328, TE 0.413, WR 0.568 against 0.329, 0.414, 0.589. So the WR shortfall
remains in the forced arm too, which is what the free arm inherits.

Still not tested: whether the joint model picks the right individuals (player-level replacement), and any workload
distribution (player snap shares) against observed. The WR gap, about 0.02 entries per pair, is the next thing to look at.

## 8. Not yet done

- Player-level replacement model: which individual replaces whom, conditional on package, role and roster.
- Top-20 signatures per team with learned probabilities.
- Handling of the 2022 missing position labels.
- Player snap shares and workload distributions against observed (the paste's evaluation list).
- Model of the 6.4% unlabelled lineups, which needs roster identity.

## 9. Not done on purpose

- No SLC integration. The simulator stays the control.
- No tuning to 2025. The 2025 holdout is scored once per candidate.
- The 2022 to 2024 field is the only fit input; no 2026 data is used.
