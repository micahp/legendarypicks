# Backup policy — Legendary Picks databases

**Find the tool here:** `backend/prune_backups.py`
**Find the rule here:** this file.

Applies to every persistent SQLite database in `backend/data/` — primarily
`picks.db` (prod) and `picks.dev.db` (dev), plus JSON caches that carry `.bak`
siblings.

## The one rule that overrides all others

**Back up with `VACUUM INTO`, never `cp`.**

A plain `cp` of a live database races writers and produces a torn snapshot.
Proved 2026-08-05: a hand-taken `cp` reported `database disk image is
malformed` while the source passed a full `integrity_check`, and every `.bak`
taken by hand that night had the same defect. None of them were trustworthy.

`VACUUM INTO 'dest'` from a read-only connection yields a consistent snapshot
in both `delete` and `wal` journal modes, and the resulting file is verified
with `PRAGMA quick_check` before the operation proceeds. This is what
`backend/migrate_schema.py::create_verified_backup` does — every migration
runner (`migrate_all.py`, `migrate_schema.py`, `migrate_player_stats.py`,
`migrate_roster_snapshots.py`, `scripts/merge_nba_identities.py`) uses it.

## Retention

`backend/prune_backups.py` enforces **keep the N most recent per prefix**
(default `--keep 10`). A prefix is the database file name before the first
backup marker: `picks.db.pre-schema-...bak` and `picks.db.bak-...` both group
under `picks.db`; `picks.dev.db.*` under `picks.dev.db`; JSON caches under
their own name.

Run it by hand when convenient, or wire it into a nightly cron. Dry run by
default; `--apply` deletes:

```bash
cd backend
venv/bin/python prune_backups.py            # what would go
venv/bin/python prune_backups.py --apply    # do it
```

### Exceptions

A backup explicitly named in `docs/*.md` is **never pruned**. Documents rot
toward "we can't", so a baseline a doc still points at stays until the doc
stops pointing at it. `prune_backups.py` scans `docs/` for named backups and
also hard-codes the historical baselines (`picks.db.bak-20260615-182333`,
`picks.db.bak-20260624`, `picks.db.bak-20260624-m6`,
`picks.db.bak-premigrate-20260710-032413`, `picks.dev.db.bak-predupe-123501`).

`-wal` / `-shm` siblings of a pruned backup are pruned with it.

## Why this exists

`backend/data/` reached 15GB across ~95 `.bak` files with no policy. That cost
once already: a bare `*.bak` pattern in `.dockerignore` does not cross a `/`,
so 7.7GB of backups were baked into the production image (`c6b2728`). The
backend `.dockerignore` now names `data/` explicitly; this retention rule
keeps the directory from becoming a second incident.
