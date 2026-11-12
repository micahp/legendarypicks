# V1.6 residual gap: source-population audit candidate (2026-11-12)

**Base:** `slc-v1.6@a635a96c`. The source-population correction was merged locally into `slc-v1.6` at `41c6b0cb` for a bounded V1.6-only rerun. No probability weights were tuned.

## Observed full-game evidence

The pushed 100-seed-per-matchup scorecard shows:

| Metric per team-game or rate | Historical | V1.6 |
|---|---:|---:|
| First-down dropback share | 50.03% | 44.02% |
| Second-down dropback share | 61.66% | 56.34% |
| First-down incompletions per dropback | 34.27% | 28.12% |
| Second-down incompletions per dropback | 34.36% | 28.15% |
| Giveaways per team-game (no TOD) | 1.189 | 0.528 |
| Sacks per dropback | 6.55% | 5.94% |
| Fourth-and-5-or-short per team-game | 3.043 | 4.14 |

At V1.6's observed first/second-down play volume, the dropback-share deficits amount to ~1.66 first-down and ~1.15 second-down additional dropbacks per team-game. At the present dropback volume, the incompletion-rate deficits amount to ~0.75 additional incompletions on each down, ~1.50 combined. These are *accounting counterfactuals*, not causal simulator predictions.

The historical scorecard includes all regular-season PBP eligible for the scorecard calculation, while E1's historical outcome sampler excludes penalties, missing same-quarter successors, turnovers without clean new-offense successors, and defensive return touchdowns. The underlying supported-event baseline needs to be calculated before attributing the entire giveaway gap to event weighting.

## Concrete source-population bug found

`pass_label_outcomes.PassLabelOutcomeModel.fit()` included `fumble_lost` outcomes from historical designed runs and QB scrambles in its **pass-attempt-only** baseline. The model is applied after the simulator has already selected a dropback and a pass-outcome group. A run fumble is outside that candidate population. This branch excludes run/scramble fumbles from that fit.

`slc_setup_cache.pass_label_input_sha256()` also now includes `play_type` and `qb_scramble`, which have become model-fit inputs, preventing an incorrect content-cache hit.

Regressions added:
- A pass-label fit with 80 extra rushing/scramble fumbles must have the same base and conditional probabilities as the pass-only fit.
- Changing the source event's run/dropback flags must change its fit-cache identity.

## V1.6-only full-game rerun

The correction was rerun on the same two matchups, seeds, and frozen data inputs as the earlier V1.6 scorecard: 100 seeds each for ARI–DAL and ATL–TB (200 valid games / 400 team-games), with all five blocker fixes enabled. The database SHA-256 remained `7dc065201762daf516daba6f23c271173966548e7c3349a00ce7bd543f273cdf`; both roster snapshot IDs, snapshot files, playcall artifact, streak file, and 212,104-row materialized-history artifact were unchanged. Paired RNG snapshot hashes matched the prior run in each matchup. The fast-host name did not resolve in this environment, so this rerun used the local read-only copy of the same database.

| Metric | Prior V1.6 | Corrected V1.6 | Historical |
|---|---:|---:|---:|
| Giveaways per team-game | 0.5275 | 0.5300 | 1.1891 |
| First-down incompletions per dropback | 28.12% | 28.15% | 34.27% |
| Second-down incompletions per dropback | 28.15% | 28.17% | 34.36% |
| First-down sacks per dropback | 4.94% | 4.93% | 5.04% |
| Second-down, 6–9 to-go sacks per dropback | 5.17% | 5.12% | 5.76% |
| Third-and-3–5 per team-game | 4.045 | 4.060 | 3.185 |
| Fourth-and-5-or-short per team-game | 4.140 | 4.138 | 3.043 |

The corrected fit explicitly excluded **301 non-pass fumble rows**. The full-game rerun shows no material change in giveaways, incompletions, or progression metrics: giveaways remain far below history, and early-down incompletions remain about six percentage points low. The correction fixes the training-population defect, but it does not explain or close these full-game gaps. The run completed 100/100 valid games for each matchup with zero simulation errors.

Raw corrected outputs, including ordered plays, seed ledgers, boxscores, and reports, are in `/tmp/slc-v16-pass-fumble-fix-2026-11-12/` on this host. The pass-fit cache recorded a miss on ARI–DAL and a hit on ATL–TB, using the corrected cache identity. This validates execution of the corrected V1.6 path, not held-out event log loss or calibration.

## Required evidence to promote

1. Compare supported historical giveaway outcomes with all historical giveaways, including exclusion counts by cause, down, and event. This identifies population mismatch before any probability tuning.
2. On an untouched chronological 2025 cohort, compare old/new conditional pass-event log loss and calibration. Preserve sack distribution.
3. On the frozen ARI-DAL and ATL-TB 100-seed setup, compare corrected vs baseline with paired RNG, checking interceptions, lost fumbles (run and pass separately), incompletions, fourth-and-short, and legal full-game coverage.
4. If the change does not improve heldout event score and V1.6 drive outcomes without regression, do not promote it.

The prior run evidence is `docs/research/slc-v1.6-drive-progression-2026-11-12/evidence/v15-v16-100-seed-runs.tar.gz`, 68,765,088 bytes. The corrected run's raw outputs remain in the local `/tmp` directory above and have not been added to Git.

No probabilistic correction to the released V1.6 model is asserted.
