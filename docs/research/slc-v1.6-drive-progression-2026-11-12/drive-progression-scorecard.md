# V1.5 / corrected V1.6 drive-progression scorecard — 2026-11-12

## Result

The bounded replay completed **100 valid games per matchup and profile**: ARI–DAL and ATL–TB, for 200 games / 400 team-games per profile. All five blocker fixes were enabled in each arm. V1.6 materially corrected early-down sack rates, but it did **not** close the fourth-and-short gap or the giveaway gap. The V1.6 freeze gate remains open.

This is a diagnostic comparison, not a causal estimate of the label fix. V1.5 and V1.6 differ in multiple model settings, even though matchup seeds and other pinned inputs were held constant. Seed IDs do not guarantee common random draws between profiles.

## Main results

Per team-game unless marked as a rate. Historical is the same frozen local database used by the run, filtered to 2022–2025, regular-season weeks 1–18.

| Metric | Historical | V1.5 | V1.6 corrected |
|---|---:|---:|---:|
| Drives | 10.86 | 10.24 | 10.51 |
| Run attempts | 24.39 | 29.92 | 29.35 |
| Run yards per attempt | 4.29 | 4.35 | 4.49 |
| Dropbacks | 37.30 | 36.98 | 35.89 |
| Net yards per dropback, sacks included | 6.18 | 7.07 | 6.35 |
| Sacks | 2.44 | 0.59 | 2.13 |
| Sack rate per dropback | 6.55% | 1.60% | 5.94% |
| Giveaways, excluding turnovers on downs | 1.19 | 0.60 | 0.53 |
| Punt-ending drives | 3.86 | 3.11 | 3.74 |
| Touchdown drives | 2.49 | 2.88 | 2.41 |
| Field-goal-attempt drives | 1.98 | 1.86 | 1.94 |
| Turnover-ending drives | 1.09 | 0.61 | 0.56 |
| Turnovers on downs | 0.62 | 0.80 | 0.88 |

V1.6’s first-down dropback sack rate was **4.94%** (historical 5.04%); second-down dropbacks at 6–9 yards to go were **5.17%** (historical 5.76%). This is a large correction from V1.5’s 1.01% and 1.75%. Punt and field-goal drive rates also moved closer to historical. Giveaways remain substantially low; turnover-on-downs are high. Counting failed fourth-down conversions as turnovers would mask that gap, so those outcomes are reported separately here.

## Down and distance

Success rate means gaining at least 40% of to-go on first down, 60% on second, and the line to gain on third/fourth; touchdowns count as success. These rates include scrimmage run/dropback plays only.

| Metric | Historical | V1.5 | V1.6 corrected |
|---|---:|---:|---:|
| First-down success | 51.2% | 53.6% | 52.4% |
| Second-down success | 47.6% | 51.1% | 48.6% |
| Third-down success | 40.0% | 47.4% | 43.6% |
| Fourth-down scrimmage success | 54.4% | 58.9% | 55.8% |
| Third-and-3–5 situations | 3.19 | 4.31 | 4.05 |
| Third-and-10+ situations | 3.40 | 2.25 | 2.65 |
| All fourth-down situations | 7.18 | 6.89 | 7.67 |
| Fourth-and-5-or-short, all decisions | 3.04 | 4.01 | 4.14 |
| Fourth-and-5-or-short run/dropback decisions | 1.15 | 1.66 | 1.68 |

The overall third-down success gap narrowed from V1.5, while third-and-medium remains about 27% high and fourth-and-short all-decision opportunities about 36% high. The scrimmage-only fourth-and-short figure is provided separately because fourth-down kicks are also decisions in the all-opportunities count. Historical fourth-down counts exclude `no_play` rows; the simulator cannot sample a penalty/no-play branch.

## Early-down dropback decomposition

| Situation | Historical | V1.5 | V1.6 corrected |
|---|---:|---:|---:|
| First-down dropback share of run/dropback plays | 50.0% | 45.5% | 44.0% |
| First-down dropback sack rate | 5.04% | 1.01% | 4.94% |
| First-down incompletion rate | 34.3% | 28.4% | 28.1% |
| First-down negative-yardage rate, all scrimmage plays | 7.95% | 7.52% | 9.21% |
| First-down run yards per attempt | 4.43 | 4.34 | 4.46 |
| First-down net dropback yards | 6.73 | 8.01 | 7.58 |
| Second-down dropback share | 61.7% | 56.2% | 56.3% |
| Second-down dropback sack rate | 5.62% | 1.47% | 5.30% |
| Second-down incompletion rate | 34.4% | 30.5% | 28.1% |
| Second-down negative-yardage rate, all scrimmage plays | 8.24% | 6.25% | 8.57% |
| Second-down run yards per attempt | 4.31 | 4.24 | 4.41 |
| Second-down net dropback yards | 6.08 | 6.72 | 5.86 |

This does not support the old claim that V1.6 still suppresses early-down negative yardage overall: its negative-yardage rate is slightly above history on both downs, and the sack rates are close. The remaining differences are visible in the mix and conditional outcomes: V1.6 selects fewer early-down dropbacks, and its incompletion rate is 6–7 percentage points below historical. First-down net dropback yardage is high; second-down net yardage is slightly low. These findings narrow the mechanism to call mix and conditional non-sack outcomes/yardage; they do not establish which one causes the excess short fourth downs.

## Interpretation and stop point

- The sack-label correction is supported for sack calibration in this run. It did not resolve the drive-progression and fourth-down opportunity gaps.
- The data do not justify another fourth-down policy change; the excess remains upstream.
- Do not call giveaways fixed: after excluding turnovers on downs, V1.6 has 0.53 giveaways per team-game against 1.19 historically.
- This bounded run answers the broad metrics question. It does not identify a single causal implementation change, so no speculative sampling change is claimed here. The next code change should be tied to the observed early-down call/incompletion/yardage discrepancy and judged against this same scorecard, rather than starting another broad search.

## Reproducibility

The machine-readable metrics and all per-run hashes are in [`drive-progression-scorecard.json`](drive-progression-scorecard.json). Each full run report embeds the frozen roster inputs and run configuration; its roster snapshot identifier, snapshot hash, reference hash, profile/configuration hash, and blocker list are recorded there.

- Historical database: `/root/legendarypicks/backend/data/picks.dev.db.pre-roster-sync-20261111.bak`; SHA-256 and byte size are in the JSON. This frozen database differs from the source used by some earlier reports, so historical numbers here supersede those earlier comparisons for this run.
- Classifier-before-runtime materialization: `slc-history.sqlite`, SHA-256 `d05e88f77b03ad488eb27aa7d3b67eac1d37bf4c42df01bf5c748e93524084ab`, 212,104 classified rows; built and inspected from that frozen database.
- Four run summaries, ordered-play exports, seed ledgers, and boxscores were generated under `/tmp/slc-v16-drive-scorecard-2026-11-12/`. Their SHA-256 values are recorded in the JSON. Each arm had 100 valid full games, no simulation/validation errors, and no blocked games.
- All arms used the two pinned roster snapshot IDs listed in the JSON, play-call artifact `27c02afd6d9f6f80a38b3bc7ae278b1efebcc7caa5664688c64c55bc0c698ac7`, streak input SHA-256 `4d3e0d712134396ea91d1d9d8bca11ce9d6089674d9d6e2360696f44e311af5c`, and the five blocker fixes. The V1.6 arms enabled corrected pass-label conditioning and exact-distance yardage; coverage outcome conditioning was disabled.
- Historical denominators: 1,087 games / 2,174 team-games. Each simulated profile: 200 games / 400 team-games.

The compressed full-run artifact is [`evidence/v15-v16-100-seed-runs.tar.gz`](evidence/v15-v16-100-seed-runs.tar.gz), 68,765,088 bytes; SHA-256 `d5ecf4b75b500c1fbb852b93a1988d99d374fd36be55444c1a2b2563096e4505`. It contains each run's summary JSON, ordered plays, seed ledger, and boxscores for all four arms.
