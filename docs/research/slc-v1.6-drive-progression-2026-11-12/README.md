# SLC V1.6 drive-progression diagnostic — 2026-11-12

## Result

The opt-in ordered-game export is implemented in `simulate_pregame_batch.py` as `--export-plays`. It preserves the already generated game record, including ordered drives, plays, and before/after states. The four compressed JSONL files in `evidence/` are 20 games per arm from the same two frozen Week 8 snapshots and seeds 1–10.

This diagnostic did **not** identify and correct a specific transition defect. The exact-distance source-row checks had zero down/distance mismatches among 2,064 inspected exact-branch plays. Within-drive state continuity also had zero mismatches. These checks rule out those two suspected implementation errors in this sample; they do not prove all transition paths correct.

The V1.6 baseline still has excess third-and-3–5 and fourth-and-short situations relative to the 2022–2025 clean historical reference. A tested intervention that disabled team event weights made those metrics worse. That intervention was reverted; V1.6 configuration and V1.5 behavior remain unchanged. Do not freeze V1.6 on this evidence.

## Inputs and reproducibility

- Code at run start: `bca58454` (`slc-v1.6`); ordered-play exporter was an uncommitted working-tree change used for these runs.
- Frozen snapshots: `2026_08_ARI_DAL` and `2026_08_ATL_TB`, cutoff `2026-10-29T00:02:21Z`.
- Snapshot SHA-256: ARI–DAL `503d276915f5c2a09add5a53927a4531e9c84a6cd15b6021dd6b59f623016599`; ATL–TB `60d5eb9c2464d1c70df638068f9ffc4819e97f6d857e63df3e23aab03c773c49`.
- Reconstructed read-only reference extract SHA-256: `9589ad821c83f6b772d0a6b7beb0baf9d85a2a5d90093572ce53cb506bb120f2`. This is not the original mutable database and is not claimed to reproduce it.
- Both arms: 20/20 valid games, 40 team-games. The second arm used the same snapshots and seeds with `playcall_team_outcomes` disabled, solely to test whether those weights explained the progression pattern.
- Historical reference: 2,174 team-games, 2022–2025 clean play-by-play. The simulation arm is only two matchups; comparisons are diagnostic, not a broad estimate.

## Drive-progression results

Per team-game except rates. “Baseline” is the V1.6 candidate as configured before the experiment. “Weights off” is the rejected intervention.

| Measure | Historical | V1.6 baseline | Weights off |
|---|---:|---:|---:|
| Third-down attempts | 12.72 | 13.25 | 14.58 |
| Third-and-3–5 situations | 3.16 | 4.05 | 4.38 |
| Third-and-10+ situations | 3.45 | 2.48 | 2.90 |
| Third-down conversion rate | 39.4% | 43.4% | 42.0% |
| Fourth-down situations | 6.83 | 7.23 | 7.85 |
| Fourth-and-5-or-short | 2.95 | 3.75 | 4.38 |
| Fourth-and-2-or-short | 1.37 | 1.55 | 1.95 |
| Sacks | 2.42 | 2.18 | 1.95 |
| Turnovers | 1.20 | 1.13 | 1.80 |
| Early-down mean gain | 5.37 | 5.83 | 5.22 |
| Early-down negative plays | 4.43 | 3.78 | 3.83 |
| Drives | 10.79 | 10.60 | 11.10 |

On V1.6 baseline, second-down plays transitioned to third-and-3–5 4.05 times per team-game, versus 3.16 historically; transitions to third-and-10+ were 2.48 versus 3.41. This is consistent with too few long-yardage outcomes after early downs. In this small sample, first-down dropbacks had a 67.2% completion rate and 3.5% sack rate, compared with historical 64.1% and 5.3%. Second-down 6–9-yard dropbacks occurred 5.48 times per team-game versus 4.25 historically, with 64.8% completions and a 3.7% sack rate versus historical 62.9% and 6.1%.

These are observed associations in the replay, not proof that a particular weight or yardage sampler is the cause. Disabling team event weights reduced early-down gains but increased third-down volume, short distances, fourth-down opportunities, and turnovers. It is not a correction and has been reverted.

## What is and is not established

- Exact-distance source selection matched the requested down and distance in all 2,064 inspected exact-branch plays.
- Within-drive state transitions were continuous in all inspected records: each next play’s starting state matched the preceding play’s resulting state.
- The observed drift is upstream of the reducer: simulated early-down outcomes, especially dropbacks, more often leave short third downs and less often leave third-and-long than the historical reference.
- This bounded test did not isolate whether the remaining cause is play-call mix, conditioned outcome sampling, or the sampled yardage distribution. It did not test or alter the fourth-down decision policy.
- The reference extract is reconstructed and 2026 penalty status is incomplete in the source DB; historical comparisons use clean 2022–2025 rows. Two matchups cannot establish general calibration.

## Evidence files

Each JSONL starts with a manifest and then has one full game record per seed. Files are gzip-compressed to keep the repository additions below GitHub’s recommended per-file size. SHA-256 values:

| File | SHA-256 |
|---|---|
| `evidence/frozen-before-2026_08_ARI_DAL.plays.jsonl.gz` | `8fc909b94a5e1e673ee7c358e98c05c3f9112ab1bf61db16044d2b5b3f91960e` |
| `evidence/frozen-before-2026_08_ATL_TB.plays.jsonl.gz` | `d0fbac5cb42554df958a25964115a371fa2f1ba92218d9426d6d16be51d1f93c` |
| `evidence/frozen-after-2026_08_ARI_DAL.plays.jsonl.gz` | `3796b70a00062e2609c56dcd2e0ff97dd1c738141e91623f9f2ebf285091f358` |
| `evidence/frozen-after-2026_08_ATL_TB.plays.jsonl.gz` | `84b1ec9e1b182e16d32ac2127392513db37c87bc6a492bc3aace356e4a225cc5` |

“Before” and “after” distinguish the baseline and rejected weights-off diagnostic arms; no engine correction is represented by “after.”
