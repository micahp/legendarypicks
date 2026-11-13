# V1.6 WAS–NYG seed 20261204: sack fumble at the goal line

The 1,000-seed Washington at New York Giants batch recorded a simulation error
for seed **20261204**, rather than a valid completed game. On play 129, in Q4
with 7:54 remaining, New York had second-and-10 at its own one-yard line
(`yardline_100=99`), trailing by 16. The sampler selected `sack_fumble_lost`
with a three-yard loss, which would carry the ball past the offense's goal
line. The transition raised:

```text
FootballAssertionError: ILLEGAL_STATE: sack_fumble_lost loss -3 carries the ball past its own goal line
```

The state transition was not applied. The recorded source play was
`2025_03_LA_PHI`, play `2151`; the sampled next-snap spot was 10. The correct
football result cannot be inferred solely from these values: possession and the
location of the fumble and recovery matter. This report records the failure;
it does not claim a fix or assign a safety or touchdown.

The original compressed [failure record](failure.json.gz) includes the full
state, decision trace, sampled source and input-provenance hashes. The exact
[pregame snapshot](snapshot.json), [capture manifest](snapshot-manifest.json),
and [streak input](streaks.json) are included here.

## Recorded inputs

- V1.6 producer commit: `58e7eee04decb7e4d1ffc3f47f28bb49f47b5b87`.
- Game: `2026_10_WAS_NYG`; model: `SLC_v1_6_candidate`; seed: `20261204`.
- Model configuration hash: `ff1377c150a1683598cb5b65086f0fe84f49934152755e5ba3cf30ddca56ed73`.
- Reference hash recorded by the model: `85359ff96b6a8a1cc002762a6dc496024ac493e61bdafa4c8e26b82bbbb4aed9`.
- Snapshot file SHA-256: `fdc71aeb316e7dc10294c3d6581e1c331fe49637ab68fc71b9b406c55a8449b4`; model's canonical snapshot hash: `2963b30acfda8d84835a27e889f94f81e83fabcfab429acd5bc028a0dac970df`.
- Streak file SHA-256: `991bd41ee471dd0d306019d9b0cb7bf288ea79d922a79463e1c54698075496bc`.
- Play-call artifact file SHA-256: `c8f16540931f6fddc61b6e62797ecd71dfff11897c393c531033eef623328ce5`.
- Historical database `/root/legendarypicks/backend/data/picks.dev.db` SHA-256: `4a782007fc6c04a8e9df6c2e3110f7cdd404a4afe841da29a2e001f56087b05e`; opened read-only.
- Materialized history `/root/.cache/legendarypicks/slc-history.sqlite` SHA-256: `e32b2b1c0717767bf2e167441f728e89a79590b2078038585685571b70a4ea0a`.
- Current-season PBP `/root/lp-snapshots/nfl-backfill-2026-11-03/raw/pbp/play_by_play_2026.parquet` SHA-256: `6555b925b9507d3f803092f20b06f2c015588e6562918d37027cd386d2607cc3`.
- Original failure record SHA-256: `541558c6aa52c9028fba9f08407cc250bf36a3f3ed5f9cf1bd3bc573d0635fa4`.

The database, materialized history and source parquet are large external inputs;
they are not included in this repository. Exact replay requires those bytes and
the other source files referenced by the snapshot and model manifests. The
included snapshot was captured after the roster-finalization window opened,
but the roster feeds did not provide a verified official inactive list.

## Replay on the fast host

With the checkout at the producer commit and the original pinned files in place,
the following reproduces the same settings and single seed. Use a fresh output
path; this command does not overwrite the original batch:

```bash
cd /root/lp-slc-v2
/usr/bin/python3 -u scripts/nfl_sequence/simulate_pregame_batch.py \
  --snapshot-file /root/slc-was-nyg-tnf-2026-11-12-final-0013Z/snapshot.json \
  --db /root/legendarypicks/backend/data/picks.dev.db \
  --slc-profile v1_6_candidate \
  --slc-materialized-history /root/.cache/legendarypicks/slc-history.sqlite \
  --playcall-artifact docs/research/SLC-PLAYCALL-ARTIFACT-v1.json \
  --playcall-streak-file /root/slc-was-nyg-tnf-2026-11-12-final-0013Z/run-inputs/wl-streaks-through-week9.json \
  --playcall-pass-label-mode conditional --playcall-decision \
  --slc-fg-ordinary-cutoff 60.0 --games 1 --seed-start 20261204 --progress-every 1 \
  --out /root/slc-was-nyg-tnf-2026-11-12-final-0013Z/runs/v1.6-replay-20261204/simulation.json \
  --export-boxscores --export-plays \
  --slc-blocker-fix run_scramble_backoff \
  --slc-blocker-fix long_field_goal_feasibility \
  --slc-blocker-fix blocked_kick_source_audit \
  --slc-blocker-fix blocked_kick_geometry \
  --slc-blocker-fix safety_free_kick_boundaries
```

The five listed blocker fixes were enabled in the original batch. This seed
uses the branch's default unpaired RNG protocol, not the V2 RNG protocol.

## Replay result

A single-seed replay on the fast host reproduced the same assertion and reported
one simulation error and zero valid games. Its compressed failure record had
SHA-256 `541558c6aa52c9028fba9f08407cc250bf36a3f3ed5f9cf1bd3bc573d0635fa4`,
byte-for-byte identical to the original failure artifact. The 1,000-seed batch
continued independently during the replay.
