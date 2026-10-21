# Full-frame artifact storage and reproduction

## Artifact locations

The full-frame response bodies and generated tables are not Git artifacts.
Store them under `/root/lp-data/nhl-fullframe-event-audit-2026-10-21/`.

- Raw PBP: `raw/pbp/{game_id}.json.gz` and matching `.meta.json`.
- Raw shifts: `raw/shifts/{game_id}.json.gz` and matching `.meta.json`.
- This hardened run's separate source game lists, manifests, and run reports:
  `manifests/hardened-v1/`.
- Its derived event dispositions, player shift dispositions, target
  reconciliations, issue ledger, game metrics, and audit JSON:
  `derived/hardened-v1/`.
- Earlier/interim fetch manifests and logs remain in the parent `manifests/`
  and `logs/` directories and are not replaced by the hardened outputs.

Each source body is compressed independently. Its sidecar and manifest row record
the source URL, HTTP status, content type, game ID, payload row count, compressed
and decompressed byte lengths and SHA-256 hashes, and retrieval time. Request
timing is recorded for new hardened imports; it is marked unavailable when an
older cached body has no timing metadata. The 300 sample bodies retain their
cache-copy origin, original event-manifest SHA-256, and pinned audit commit.

The importer writes atomic `.progress.csv` checkpoints while a source run is in
progress. It publishes or replaces the final source manifest only after all
4,876 bodies verify. An access refusal or request failure leaves the previous
final manifest byte-for-byte intact; the report and progress manifest identify
the interruption. Resume verifies the raw cache first, so valid bodies are not
downloaded again.

The artifact directory is outside the repository, but this environment has no
mounted off-host or separate-volume backup target configured: `/root/lp-data`
and the checkout both reside on `/dev/sda3`. Therefore the host-local copy is
not a durable backup, and the storage requirement remains open until the
directory is copied to an organization-managed artifact volume. To create that
backup, copy the directory without changing its contents:

**Follow-up note:** arrange a second copy on a different disk or host, then
verify it against the manifests. No independent backup has been made yet.

```sh
rsync -a --checksum \
  /root/lp-data/nhl-fullframe-event-audit-2026-10-21/ \
  /path/to/durable-artifact-volume/nhl-fullframe-event-audit-2026-10-21/
```

To restore, copy that saved directory back to the same artifact root:

```sh
rsync -a --checksum \
  /path/to/durable-artifact-volume/nhl-fullframe-event-audit-2026-10-21/ \
  /root/lp-data/nhl-fullframe-event-audit-2026-10-21/
```

After restoring, run the manifest/body verifier before analysis. It checks both
hashes, byte counts, source URL and game identity, JSON shape, payload row count,
and sidecar-to-manifest agreement. It then rechecks body hashes while loading one
game at a time for audit. Derived CSV gzip files use fixed gzip timestamps, so
identical inputs produce identical table bytes. A body that fails any check is
excluded and listed by ID and reason code.

## Recreate source-specific game lists

From the repository root:

```sh
/root/legendarypicks/backend/venv/bin/python \
  research/nhl/fullframe-event-audit-2026-10-21/select_source_lists.py \
  --pbp-out /root/lp-data/nhl-fullframe-event-audit-2026-10-21/manifests/hardened-v1/pbp_games.csv \
  --shift-out /root/lp-data/nhl-fullframe-event-audit-2026-10-21/manifests/hardened-v1/shift_games.csv \
  --summary-out /root/lp-data/nhl-fullframe-event-audit-2026-10-21/manifests/hardened-v1/source_lists.summary.json
```

The command verifies the derived 4,876-game list against its pinned SHA-256 and
season counts, then atomically writes the separate source lists.

## Resume the import

The importer verifies existing local bodies and supplied cache directories before
requesting a body. It resumes from valid bodies after interruption, will not
overwrite an existing body, writes manifests through an atomic replacement, and
stops on source refusal or rate limiting. Following a prior refusal, resume with
`--resume-after-refusal` only after access has been restored.

```sh
/root/legendarypicks/backend/venv/bin/python \
  research/nhl/fullframe-event-audit-2026-10-21/import_full_frame.py \
  --pbp-games /root/lp-data/nhl-fullframe-event-audit-2026-10-21/manifests/hardened-v1/pbp_games.csv \
  --shift-games /root/lp-data/nhl-fullframe-event-audit-2026-10-21/manifests/hardened-v1/shift_games.csv \
  --raw-dir /root/lp-data/nhl-fullframe-event-audit-2026-10-21/raw \
  --pbp-manifest /root/lp-data/nhl-fullframe-event-audit-2026-10-21/manifests/hardened-v1/pbp_verified_manifest.csv \
  --shift-manifest /root/lp-data/nhl-fullframe-event-audit-2026-10-21/manifests/hardened-v1/shifts_verified_manifest.csv \
  --pbp-report /root/lp-data/nhl-fullframe-event-audit-2026-10-21/manifests/hardened-v1/pbp_import_report.json \
  --shift-report /root/lp-data/nhl-fullframe-event-audit-2026-10-21/manifests/hardened-v1/shifts_import_report.json \
  --pbp-reuse-raw-dir /root/lp-data/nhl-event-data-audit-2026-10-20/raw \
  --shift-reuse-raw-dir /root/lp-data/nhl-event-data-audit-2026-10-20/raw \
  --pause 0.9 --retries 2 --flush-every 10
```

The source lists, manifests, reports, and reuse directories are independent CLI
arguments; no module constants need editing. Requests are serial. The estimate
uses the actual configured pre-request pause plus measured response and retry
time. The run report gives the observed seconds per new body and the projected
remaining sequential duration at that observed mean. A pause-only figure is a
lower bound, not a total request duration.

An earlier hardened measurement recorded 31.327 seconds for 27 new PBP bodies
with a 0.9-second pre-request pause: 1.1603 seconds per body including pacing.
At that observed mean, 4,576 remaining bodies project to 5,309.5 seconds (88.5
minutes) per source, or about 177 minutes if fetched sequentially. The pause-only
lower bound is 68.6 minutes per source. This is a 27-request projection, not the
final run duration. Use the legacy batch logs for cumulative network time and
the hardened import reports for verified/reused body counts and any requests
the hardened importer itself needs to make.

## Recreate the full-frame audit

```sh
/root/legendarypicks/backend/venv/bin/python \
  research/nhl/fullframe-event-audit-2026-10-21/audit_full_frame.py \
  --frame research/nhl/official-outcome-backfill-2026-10-20/canonical_frame.csv \
  --full-frame-games research/nhl/fullframe-event-audit-2026-10-21/full_frame_games.csv \
  --pbp-games /root/lp-data/nhl-fullframe-event-audit-2026-10-21/manifests/hardened-v1/pbp_games.csv \
  --shift-games /root/lp-data/nhl-fullframe-event-audit-2026-10-21/manifests/hardened-v1/shift_games.csv \
  --raw-root /root/lp-data/nhl-fullframe-event-audit-2026-10-21/raw \
  --pbp-manifest /root/lp-data/nhl-fullframe-event-audit-2026-10-21/manifests/hardened-v1/pbp_verified_manifest.csv \
  --shift-manifest /root/lp-data/nhl-fullframe-event-audit-2026-10-21/manifests/hardened-v1/shifts_verified_manifest.csv \
  --prior-pbp-manifest /root/lp-data/nhl-fullframe-event-audit-2026-10-21/manifests/pbp_evidence_manifest.csv \
  --prior-shift-manifest /root/lp-data/nhl-fullframe-event-audit-2026-10-21/manifests/shifts_evidence_manifest.csv \
  --label-csv /root/lp-data/nhl-official-outcome-quality-adjudication-2026-10-20/research_label_quality.csv \
  --derived-out /root/lp-data/nhl-fullframe-event-audit-2026-10-21/derived/hardened-v1 \
  --report-out /root/lp-data/nhl-fullframe-event-audit-2026-10-21/derived/hardened-v1/fullframe_audit.json
```

The default run fails closed on missing or inconsistent source evidence and
compares each hardened manifest row to the earlier full-frame manifest. Use
`--allow-incomplete` only for a clearly marked interim coverage report. Do not
use an interim report to train or evaluate a model.

The deterministic failure-injection suite is:

```sh
/root/legendarypicks/backend/venv/bin/python \
  research/nhl/fullframe-event-audit-2026-10-21/test_fullframe_event_pipeline.py
```
