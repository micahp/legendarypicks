# Washington at New York Giants: SLC-v2 single-game run

Run date: November 11, 2026  
Scheduled kickoff: Thursday, November 12, 2026, 7:15 PM CT  
Game: `2026_10_WAS_NYG`  
Seed: `20261112`

## Run result

**Washington 19, New York Giants 35.** The simulator completed one regulation game. It reported 1/1 valid games, zero simulation or validation errors, strict box-score reconciliation passed, and clock reconciliation passed. The play export contains 134 ordered plays. Model load and reference construction took 147.0 seconds; game generation took 1.9 seconds.

This is one Monte Carlo outcome. Its score is not a calibrated score distribution or win probability.

## Configuration

- SLC-v2 profile (`v1_full_stack` plus `--slc-v2`), RNG protocol v2.
- Conditional pass-label model enabled.
- SLC-v2 season adaptation enabled; no separate experimental workload-estimator override was supplied.
- Box-score and ordered-play exports enabled.
- Blocker fixes: scramble backoff, long field-goal feasibility, blocked-kick source audit, blocked-kick geometry, and safety free-kick boundaries.
- Full command and hashes are in [`run-manifest.json`](run-manifest.json).

## Snapshot and data provenance

The forecast snapshot was captured at **November 11, 2026, 5:31 PM CT**. The roster-finalization window opens **November 12 at 5:45 PM CT**. The snapshot is therefore a valid snapshot taken before final rosters were available; it is not a finalized roster. It remains classified as `prospective_forecast`.

The captured weekly roster identifies one active kicker for each team. The team-kicker table assigns WAS `00-0041182` and NYG `00-0041145` from that frozen roster; its full hash is in the manifest.

The snapshot summary's recorded database hash does not match the available database copy. The run used `/root/legendarypicks/backend/data/picks.db`, opened read-only. The snapshot summary hash matched neither available database copy. The database file hash also changed between the earlier pre-run probe and the post-run measurement, so the exact bytes opened during simulation were not pinned. The run manifest records both observed hashes and this limitation. The captured roster/source hashes are unchanged.

The simulator reports roster and game-day eligibility as **unknown for all 125 selected players**. This does not invalidate the prefinalization snapshot or the completed game; it means this run does not claim verified individual active-roster or game-day status.

## Files

- [`simulation.json`](simulation.json): full report and ordered play data.
- [`simulation.boxscores.jsonl`](simulation.boxscores.jsonl): box-score and ordered-play sidecar.
- [`simulation.seeds.jsonl`](simulation.seeds.jsonl): seed ledger and RNG/model identity.
- [`snapshot.json`](snapshot.json) and the capture directory: frozen prefinalization inputs.
