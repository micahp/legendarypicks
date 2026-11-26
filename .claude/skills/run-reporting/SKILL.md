---
name: run-reporting
description: MUST load before starting, reporting on, archiving, or deleting any simulation run (single game, slate, or sweep), and before deleting any run output folder on the fast host or this machine. Saves the insights, manifest, summary, and grades first; archives raw outputs; deletes only with the user's OK.
---

# Run reporting and storage

Raw run outputs take most of the space. Save what we need first. Then archive, then delete.

The full runbook is `docs/research/RUN-REPORTING-PROCESS.md`. Follow it.

## Before a run

1. Check free space on the fast host and this machine.
2. Estimate size. A 1,000-seed game with box scores is about 1 GB. A slate is many games.
3. Export only what the report needs. Skip play-level exports unless an audit needs them.
4. Name the run folder `<scope>-<model>-<date>`.
5. Record the command, input checksums, code commit, and seed range before starting.

## After a run (before any deletion)

1. Write `docs/research/<scope>/REPORT.md`: question, result, validation, and what it does not show.
2. Save `manifest.json`: command, code commit, input checksums, seed list, validation counts, missing outputs.
3. Save a summary JSON and one line per game (teams, final score, key stats).
4. Grade against the actual result, if it exists.
5. Commit the report, manifest, summary, and grades. Push only when the user asks.

## Raw outputs

1. Archive raw box scores, seed files, and logs as one `.tar.gz` per run, on this machine.
2. Verify the archive: `gzip -t`, file count against the host, and file sizes.
3. Keep the local copy. The fast host keeps only the active run.
4. Delete host copies only after the report is pushed, the archive checks out, and the user says yes.

## Never

- Delete raw outputs without the user's OK.
- Delete the walk-forward or frozen databases without the user's OK.
- Run two jobs that write to the same folder.
