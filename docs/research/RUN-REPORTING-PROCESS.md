# Run reporting process

Use this for every simulation run: a single game, a slate, or a sweep. Raw outputs take the most space. Save the insights and the key data first. Then archive or delete the raw files.

## Before the run

1. Check free space on the fast host and on this machine.
2. Estimate output size. A 1,000-seed game with box scores is about 1 GB. A slate is many games.
3. Export only what the report needs. Use box scores only when a report needs player or game detail. Skip play-level exports unless a specific audit needs them.
4. Write the run folder name as `<scope>-<model>-<date>`, for example `week11-he-2026-11-22`.
5. Record the command, input file checksums, code commit, and seed range before starting.

## During the run

- Log progress and errors to a file in the run folder.
- Do not start a second run that writes to the same folder.

## After the run (required before any deletion)

1. Write the report: `docs/research/<scope>/REPORT.md`. Include the question, the result, the validation status, and what it does not show.
2. Save the manifest: `manifest.json`. Include the command, code commit, input checksums, seed list, validation counts, and missing outputs.
3. Save the small key data: a summary JSON and one line per game (teams, final score, key stats). These files are kept in the repo.
4. Grade the run against the actual results if they exist. Save the grades in the repo.
5. Commit the report, manifest, summary, and grades. Push when the user asks.

## Raw outputs

1. Compress raw box scores, seed files, and logs into one archive per run.
2. Check the archive: test it, count the files, and compare file sizes.
3. Keep one copy on this machine (about 43 GB free). The fast host keeps only the active run.
4. Delete the raw files on the fast host only after the report is pushed, the archive checks out, and the user says yes.

## Deletion rule

Never delete raw outputs without the user's OK. Never delete the walk-forward or frozen databases without the user's OK.
