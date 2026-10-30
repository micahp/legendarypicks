# Backups kept, and why

Each entry names one backup file, what it is for, and when it was made. Keep a named backup until its purpose is closed.
This list is the reason it is kept. Do not delete an entry on a file name alone.

## Kept

| File | Where | Made | Purpose | Keep until |
|---|---|---|---|---|
| `picks.db.bak-pre-unbind-20261027` (2.9 GB) | `/root/legendarypicks/backend/data/` | 2026-10-27, incident | Production before the 2026-10-27 identity unbind. Pinned in `docs/incidents/2026-10-27-identity.md` | Never by this list. Pinned |
| `picks.db.bak-pre-thayllon-20261027` (2.9 GB) | `/root/legendarypicks/backend/data/` | 2026-10-27, incident | Production before the Thayllon identity change. Pinned in `docs/incidents/2026-10-27-identity.md` | Never by this list. Pinned |
| `picks.db.bak-premigrate-ufc-roster-20261025-232329` (2.9 GB) | `/root/legendarypicks/backend/data/` | 2026-10-25 23:23 | Production before the UFC roster migration. The pinned UFC copy in `docs/incidents/2026-10-27-identity.md` | Never by this list. Pinned |

## Not kept by this work, and not decided here

These are job-made copies. This work did not make them, and no one has decided whether to keep them.

| File | Made by | Note |
|---|---|---|
| `picks.db.bak-premigrate-ufc-roster-20261027-232324` (2.8 GB) | A scheduled job, 2026-10-27 23:23 | Newest UFC copy. Not named in any doc. Needs an owner decision before deletion |
| `picks.db.bak-premigrate-mlb-history-timer-20261028-052524` (2.8 GB) | The MLB history job, 2026-10-28 05:25 | The job writes a new copy each morning and prunes the old one. Do not delete by hand |

## Deleted by this work, 2026-10-28

For the record. These were scratch copies and sidecars this work created, and no document pinned them.

- `/root/mls-snapshot-check/cutover/`: `debug_copy.db`, `evidence_copy.db`, `migrated_copy.db` (about 36 MB each)
- `/root/mls-snapshot-check/integrate/shadow_copy.db` (36 MB)
- `/root/mls-snapshot-check/shadow-2026-10-28/`: `base_live.db`, `base_prior.db`, `scope.db`
- Orphan `-shm` and `-wal` sidecars whose main files were already deleted: `picks.db.bak-pre-delete-roster-315191673-20261027`,
  `picks.db.bak-pre-rebind-540256-20261027`, `picks.db.bak-pre-unbind-315191673-20261027`

Not deleted: the three pinned incident backups above, the two job-made copies, and the backup folders that belong to other
sessions outside this repository. Measured with `du` on 2026-10-28: `/root/lp-backups` 3.4 GiB, `/root/lp-db-backups` 3.0 GiB,
`/root/lp-archive` 1.2 GiB, `/root/backups` 2.6 GiB, `/root/lp-discrete-eval-artifacts` 2.9 GiB, `/root/lp-sport-first-nav`
3.9 GiB (a project tree that holds backups among other files), `/root/lp-release-v097` 0.8 GiB. Total about 18 GiB. Their owners
decide. An earlier draft of this list also counted `/root/.codex` and `/root/.hermes`. Those are not backup folders and are
not counted here.

## Deleted by owner, 2026-10-30

- `/root/legendarypicks/backend/data/picks.dev.db.bak-pre-mls-identity-closure-20261028-1812` (3.05 GiB), made with
  `VACUUM INTO` and verified with `quick_check`. Deleted at the owner's request. This was the dev database restore point
  made before the MLS identity closure work.

## Naming

`<database>.bak-<purpose>-<yyyymmdd>[-<hhmm>]`. The purpose says what the backup protects against, so a later decision to delete
can be checked against this file.
