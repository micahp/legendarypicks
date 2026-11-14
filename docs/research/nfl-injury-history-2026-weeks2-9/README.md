# 2026 NFL injury-report recovery, Weeks 2–9

Candidate historical injury rows: **2639**.
Only a separately captured, hash-verified file observed before kickoff
can establish that a specific report was known at the time.
The latest nflverse season file contains historic weekly rows, but
its current modification time cannot backdate earlier snapshots.
Missing `date_modified` stays missing; no fake timestamp is generated.

## Evidence classes

| Class | Report rows |
|---|---:|
| pre_kickoff_archived_capture | 0 |
| source_modified_before_kickoff_not_observed | 0 |
| historical_weekly_report_undated | 2639 |
| source_modified_after_kickoff | 0 |
| missing_schedule_kickoff | 0 |

## Next evidence to recover

Inspect pre-kickoff cached `injuries_2026.parquet` files,
pinned SLC snapshots, prior ingest job artifacts, or original
download manifests. Add only real observed timestamps and
SHA-256 hashes to `--capture-index`; rerun this audit.
Use the official weekly injury reports linked in the CSV for
fact-checking, but a page viewed today is not itself
proof of what the site showed before a historic kickoff.

## Finalized game-day rosters

See [FINALIZED-ROSTERS-2026-WEEKS2-9.md](FINALIZED-ROSTERS-2026-WEEKS2-9.md)
for the official gamebook roster reconstruction. It provides retrospective
actual game-day active/inactive labels, not pregame-known model inputs.
