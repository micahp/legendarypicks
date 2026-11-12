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

## Follow-up: early-down dropbacks after the paired-RNG fix

An initial 10-seed ARI–DAL replay compared the label-loader change, but the two outputs recorded different reference and final snapshot hashes. Its metrics below are descriptive only; they are not a controlled before/after comparison. A controlled replay on the pulled branch is documented in the next section.

| Measure per team-game, unless a rate | Historical | Initial sample | Initial label-fix sample |
|---|---:|---:|---:|
| First-down sack rate | 5.3% | 3.1% | 2.7% |
| Second-down 6–9 dropback count | 4.25 | 4.75 | 4.75 |
| Second-down 6–9 sack rate | 6.1% | 3.2% | 3.2% |
| Third-and-3–5 situations | 3.16 | 3.70 | 4.10 |
| Third-and-10+ situations | 3.45 | 2.85 | 3.00 |
| Fourth-and-5-or-short situations | 2.95 | 4.45 | 4.55 |
| Early-down mean gain | 5.37 | 5.331 | 5.343 |
| Early-down negative plays | 4.43 | 4.00 | 4.05 |

In these initial runs, first-down dropbacks were 13.05 and 12.80 per team-game; the broad 2022–2025 clean play sample is 13.16. The second-and-6–9 dropback share was 63.3% and 60.1%, with 7.50 and 7.90 such states per team-game. Because the run hashes differ, these initial differences cannot establish a change in dropback selection. Mean early-down gain was near the historical value, while negative plays remained low.

The code audit found a real outcome-conditioning defect. Sacks have `qb_dropback=1` and `pass_attempt=0`, but the decision-label loader treated `pass_attempt` as the definition of a pass for categories G (play action), I (blitz), and N (pass rushers). Charting has these pre-snap labels for nearly all clean sacks, yet the old loader omitted them. The loader now assigns G/I/N to all dropbacks while keeping A/D/E (target role, depth, location) on pass attempts only. That prevents sack rows from being treated as unsupported for the drawn pre-snap context.

The initial samples cannot establish whether the correction improved these measures because their hashes differ. A 2025 held-out cell check found the unmodified historical source distribution predicted first-down sacks at 5.29% against 5.30% observed, and second-down 6–9 sacks at 6.06% against 5.42% observed. QB event weights changed those estimates only to 5.23% and 5.92%; formation conditioning moved them slightly upward.

## Controlled replay on the pulled branch

The comparison was rerun after pulling `slc-v1.6` through `0bf575ca`. The baseline used that commit without the local label fix; the corrected arm used the same commit plus the `decision_layer.py` change, now committed as `6df31da6`. Both used the identical frozen ARI–DAL input snapshot (`e03fb6de…`), the same read-only database, play-call artifact (`27c02afd…`), streak input (`4d3e0d71…`), V1.6 candidate settings, seeds 1–10, and paired RNG roots. Nine seeds completed full games in each arm; seed 1 hit `playcall_no_run_outcomes_in_cell:(4, '4-6', '80-99')` in both. Metrics below use the matched nine complete seeds (18 team-games per arm). Reference hashes differ because the label-loader code differs, as expected; the raw data and all other run inputs were held fixed.

| Measure per team-game, unless a rate | Historical | Pulled branch, label bug | Pulled branch, corrected labels |
|---|---:|---:|---:|
| First-down sacks / dropbacks | 5.3% | 11 / 262 (4.2%) | 10 / 263 (3.8%) |
| Second-down 6–9 sacks / dropbacks | 6.1% | 5 / 98 (5.1%) | 7 / 102 (6.9%) |
| Third-and-3–5 situations | 3.16 | 3.83 | 4.11 |
| Third-and-10+ situations | 3.45 | 2.61 | 2.94 |
| Fourth-and-5-or-short situations | 2.95 | 3.28 | 3.78 |
| Early-down mean gain | 5.37 | 5.70 | 5.51 |
| Early-down negative plays | 4.43 | 4.67 | 4.83 |

The correction moved second-down 6–9 sack rate toward the historical rate, but first-down sack rate moved slightly away; the progression measures were mixed and mostly farther from the historical counts. This small one-matchup sample does not establish a stable effect. It does confirm the label fix changes sampled outcomes under controlled inputs, so V1.6 remains open pending a larger targeted evaluation and the release gate.

### Reproduction inputs

The exact frozen input snapshot is [`evidence/frozen-ari-dal-input-snapshot.json`](evidence/frozen-ari-dal-input-snapshot.json) (13,094 bytes; file SHA-256 `be2f329cb2a9db6974a384d4413896a51e2442b423e553ee4a17a5c02947bdb9`; embedded snapshot SHA-256 `e03fb6de4c54e53ed04d6a1ae2113db5e1a7986e9d8693a57cea6d9eab5eadc9`). Other pinned inputs:

| Input | Identity |
|---|---|
| Read-only database `/root/legendarypicks/backend/data/picks.dev.db` | 3,966,197,760 bytes; SHA-256 `a26164c4bb0dea3575bad182f398e7662d90725702d468d9804f169ba774264f` |
| Play-call artifact `docs/research/SLC-PLAYCALL-ARTIFACT-v1.json` | Model artifact SHA-256 `27c02afd6d9f6f80a38b3bc7ae278b1efebcc7caa5664688c64c55bc0c698ac7` |
| Pregame streak input `docs/research/slc-week8-2026/wl-streaks-2026-10-29.json` | File SHA-256 `4d3e0d712134396ea91d1d9d8bca11ce9d6089674d9d6e2360696f44e311af5c` |
| Baseline / corrected source | `0bf575ca` / `6df31da6` |

Both runs used `--slc-profile v1_6_candidate --playcall-pass-label-mode conditional --games 10 --seed-start 1 --paired-randomness --export-plays`, with the three inputs above. The per-arm reference hashes were `7f062790771f4538ff27909fca2f3241d9e648a6f1fd0b5afefc9e37a83d3438` (baseline) and `5f0fc4417c4ff7cd15fab42094fc4b36cf9a798c0a827a0f3ede354116e13fc8` (corrected); the RNG roots matched for every seed. The outputs were `pulled-unfixed.json` and `pulled-fixed.json` under `/tmp/slc-v16-earlydropback-2026-11-12/`.
