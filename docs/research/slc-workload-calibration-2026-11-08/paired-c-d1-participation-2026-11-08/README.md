# Paired C versus D1 with week 1–8 participation updates

Date: 2026-11-08

Research branch: `research/slc-workload-d-evaluation-2026-11-08`
Simulation source commit: `59624176`

## Result

Ran 20 paired seeds for each arm on ARI–SEA, DAL–IND, and DEN–CAR. All 120 games were valid and passed box-score reconciliation. C and D1 used the same RNG-v2 stream root and identical per-seed stream evidence within each matchup.

D1 remains the preferred **experimental** player-share estimator. C remains the historical-share control. This work does not change the simulator's production default; D2 was not run.

## Participation update

Both arms used the existing week-ahead participation update in `snap_update.py`, with the same input and parameters:

- Snap-count input SHA-256: `6bc6591a1d42befaa6c67e1fb373ca1486001fdd1d55df235a81cfe244d168eb`
- Participation-field SHA-256: `9aaf7e57ce45bc525393de105c2b803673d441b589588a279a28e57ce2880a41`
- Group prior strength: 8 team games; player prior strength: 1 active game
- Last snap week used: Week 8 for all six teams; CAR had seven games through Week 8 because of its bye

A separate three-seed ARI–SEA smoke pair at source commit `2b63b114` isolates this update under D1. All six games were valid and reconciled, and the RNG roots and per-seed streams matched. Mean SEA RB appearances shifted as follows:

| Player | D1 without current-season snap update | D1 with update | Carries/game, without → with |
| --- | ---: | ---: | ---: |
| Zach Charbonnet | 39.67 | 23.00 | 14.00 → 8.33 |
| Emanuel Wilson | 0.33 | 15.33 | 0.33 → 6.33 |
| George Holani | 16.33 | 19.00 | 6.00 → 5.67 |
| Jadarian Price | 0.00 | 5.33 | 0.00 → 0.67 |

This is a small smoke sample. In the 20-seed C-versus-D1 comparison, which had the update enabled in both arms, the corresponding simulated SEA means were much closer: Charbonnet 24.25 versus 25.85 snaps/game, Wilson 8.95 versus 9.25, Holani 21.25 versus 20.65, and Price 8.10 versus 8.60. The participation update and the workload-share estimator are separate interventions.

## Candidate-set finding

Participant-selection traces show the lineup filter often leaves one RB/FB candidate for a carry decision, even when the pre-lineup population contains multiple RB/FB candidates:

| Matchup | C: one candidate | D1: one candidate |
| --- | ---: | ---: |
| ARI–SEA | 803/960 (83.6%) | 832/973 (85.5%) |
| DAL–IND | 981/1,089 (90.1%) | 986/1,101 (89.6%) |
| DEN–CAR | 960/1,092 (87.9%) | 935/1,060 (88.2%) |

These rates are diagnostic. One-back personnel is common, so a single candidate does not by itself show an error. The results do show that player-share weights cannot change many carry decisions once the sampled lineup leaves only one eligible back. In ARI–SEA, Charbonnet was selected as the sole RB/FB candidate on 143 C carry decisions and 175 D1 decisions over the 20 seeds. The full candidate traces and per-player weights are available in the seed ledgers.

## Observed data and limitations

The observed comparison is derived directly from the pinned week 1–8 snap-count input used by both arms. It contains 119 positive identified RB team/player/week rows for the six teams, with a canonical row hash of `03df13b391f45dcad3ca346cc7791eab24d03a50a2a35d5ca1636e0d2fa50878`. Player averages in `per-player.csv` are conditional on those positive rows; an absent row is left blank and is not treated as inactivity. Team snap denominators are inferred from the rounded source percentages. Acquisition time remains unknown.

For Seattle, the source rows and simulated Week 9 snap shares illustrate both the signal and the coverage gap:

| RB | Observed rows | Observed mean share when recorded | C modeled mean share | D1 modeled mean share |
| --- | ---: | ---: | ---: | ---: |
| Zach Charbonnet | 1 | 36.5% | 36.8% | 39.2% |
| Emanuel Wilson | 7 | 40.2% | 13.9% | 14.3% |
| George Holani | 8 | 37.1% | 32.8% | 31.7% |
| Jadarian Price | 4 | 39.6% | 12.5% | 13.2% |

The observed share is conditional on a positive snap row, while modeled shares average across all 20 seeds. The source row count and unknown game-day availability prevent a direct accuracy claim. In particular, Charbonnet has only one observed row, and a missing or zero row cannot be read as an inactive designation. The week 8 extension contains no verified active-roster list.

The simulator exports 4,600 player-game rows for 115 distinct players across both arms. `roster_eligible`, `active_roster`, `game_day_active`, and `roster_status` are unknown in all 4,600 rows. The observed snap source has no acquisition timestamp, and the week 1–8 extract is retrospective. These results therefore do not verify the frozen input's availability at the official game cutoff or establish game-day eligibility. The app database was opened read-only; its full database file was not hashed for this run.

The participation field counts modeled RB/FB/TE/WR lineup appearances. It excludes QB and offensive-line snaps, so it is not identical to the published offensive snap measure. The three-matchup, 20-seed results are exploratory and do not support a production-default change.

## Artifacts

- `results.json`: matchup identities, paired stream checks, validity, score distributions, snap-update settings, eligibility coverage, and artifact hashes.
- `per-player.csv`: C and D1 carries, targets, lineup appearances, shares, paired differences, and observed prior snap rows for every player in the three snapshots.
- `candidate-sets.json`: selected position groups, post-lineup candidate counts, and the single-RB candidate rates above.
- `lineup-update-smoke.json`: the separate three-seed snap-update comparison.
- `observed-rb-snaps.json`: exact read-only query, rows, parameters, and canonical row hash.
- `seed-ledgers-and-snapshots.tar.gz`: seed-level outputs and the three matchup snapshots, including the three-seed smoke ledgers.

The focused SLC workload, participation, pairing, and engine suite passed: **104 tests**.
