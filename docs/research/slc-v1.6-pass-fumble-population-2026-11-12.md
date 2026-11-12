# V1.6 residual gap: source-population audit candidate (2026-11-12)

**Base:** `slc-v1.6@a635a96c`. This research branch does not alter the V1.6 release candidate.

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

**Not established:** Whether this correction brings V1.6 giveaways closer to historical rates, or whether it improves event-level held-out scoring. It must not be merged based solely on structural correctness.

## Required evidence to promote

1. Compare supported historical giveaway outcomes with all historical giveaways, including exclusion counts by cause, down, and event. This identifies population mismatch before any probability tuning.
2. On an untouched chronological 2025 cohort, compare old/new conditional pass-event log loss and calibration. Preserve sack distribution.
3. On the frozen ARI-DAL and ATL-TB 100-seed setup, compare corrected vs baseline with paired RNG, checking interceptions, lost fumbles (run and pass separately), incompletions, fourth-and-short, and legal full-game coverage.
4. If the change does not improve heldout event score and V1.6 drive outcomes without regression, do not promote it.

The archived run evidence is `docs/research/slc-v1.6-drive-progression-2026-11-12/evidence/v15-v16-100-seed-runs.tar.gz`, 68,765,088 bytes. Its raw binary content is not accessible through the available GitHub text connector. The scorecard and code were inspected; no claim is made that this branch was validated by the archived individual plays or by a fresh full-game run.

No probabilistic correction to the released V1.6 model is asserted.
