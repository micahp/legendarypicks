#!/usr/bin/env python3
"""Retention policy for SQLite database backups in backend/data/.

Policy (documented for the next person in docs/BACKUP-POLICY.md):

- Every backup is taken with ``VACUUM INTO`` (see
  ``migrate_schema.create_verified_backup``) -- never ``cp``. A plain copy of
  a live database races writers and produces a torn snapshot (proved
  2026-08-05: the copy reported ``database disk image is malformed`` while the
  source passed ``integrity_check``).
- Keep the N most recent backups per database prefix (default 10). A prefix
  is the database file name before the first ``.`` -- e.g. ``picks.db``,
  ``picks.dev.db``, ``esports_results.json``.
- Never delete a backup that a checked-in document names. Documents rot toward
  "we can't", so a named baseline stays until the doc stops naming it.
- ``-wal`` / ``-shm`` siblings of a pruned backup are pruned with it.

Dry run by default; pass ``--apply`` to delete.

Usage:
  cd backend && venv/bin/python prune_backups.py             # what would go
  venv/bin/python prune_backups.py --apply                   # do it
  venv/bin/python prune_backups.py --keep 5 --apply          # tighter
  venv/bin/python prune_backups.py --dry-run --verbose
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DOCS_DIR = HERE.parent / "docs"

DEFAULT_KEEP = 10
# Files explicitly named in docs (checked below too); these baselines must
# survive pruning even if the doc reference scan misses a pattern.
PROTECTED = {
    "picks.db.bak-20260615-182333",
    "picks.db.bak-20260624",
    "picks.db.bak-20260624-m6",
    "picks.db.bak-premigrate-20260710-032413",
    "picks.dev.db.bak-predupe-123501",
}


def _documented_backups() -> set[str]:
    """Every backup filename mentioned in docs/*.md, verbatim."""
    names: set[str] = set()
    if not DOCS_DIR.is_dir():
        return names
    pattern = re.compile(
        r"(?<![\w.-])([A-Za-z0-9_.-]+\.(?:db|json)\.(?:bak|pre-)[A-Za-z0-9_.-]*)"
    )
    for path in DOCS_DIR.glob("*.md"):
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for match in pattern.finditer(text):
            candidate = match.group(1)
            # Only filenames that could actually be backups in data/.
            if candidate.startswith(("picks.", "esports_")) and (
                ".bak" in candidate or ".pre-" in candidate
            ):
                names.add(candidate)
    return names


def _prefix(name: str) -> str:
    """Database prefix: everything before the earliest backup marker.

    ``picks.db.pre-schema-...bak`` -> ``picks.db``
    ``picks.db.bak-20260624``      -> ``picks.db``
    ``esports_results.json.bak-1`` -> ``esports_results.json``
    """
    markers = (".bak", ".pre-", ".v0.")
    positions = [name.find(marker) for marker in markers]
    positions = [p for p in positions if p != -1]
    if not positions:
        return name
    return name[: min(positions)]


def _sort_key(path: Path):
    return path.stat().st_mtime


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP,
                        help=f"keep N most recent per prefix (default {DEFAULT_KEEP})")
    parser.add_argument("--apply", action="store_true",
                        help="actually delete (default: dry run)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if not DATA_DIR.is_dir():
        print(f"prune_backups: no data dir at {DATA_DIR}", file=sys.stderr)
        return 2

    documented = _documented_backups()
    protected = PROTECTED | documented

    backups = sorted(
        [p for p in DATA_DIR.iterdir() if p.is_file() and (".bak" in p.name or ".pre-" in p.name)],
        key=_sort_key,
    )
    # group by prefix, keep newest last
    by_prefix: dict[str, list[Path]] = {}
    for path in backups:
        by_prefix.setdefault(_prefix(path.name), []).append(path)

    to_delete: list[Path] = []
    kept: list[Path] = []
    for prefix, files in sorted(by_prefix.items()):
        files_sorted = sorted(files, key=_sort_key)
        keep_n = max(1, args.keep)
        for path in files_sorted[:-keep_n]:
            if path.name in protected:
                if args.verbose:
                    print(f"  protect {path.name} (named in docs)")
                kept.append(path)
                continue
            to_delete.append(path)
        kept.extend(files_sorted[-keep_n:])

    # wal/shm siblings of anything being deleted
    sibling_exts = ("-wal", "-shm")
    for path in list(to_delete):
        for ext in sibling_exts:
            sibling = DATA_DIR / (path.name + ext)
            if sibling.exists():
                to_delete.append(sibling)

    if not to_delete:
        print("no backups to prune: within retention")
        return 0

    print(f"would prune {len(to_delete)} file(s) "
          f"({sum(p.stat().st_size for p in to_delete) / 1e6:.0f} MB):")
    for path in sorted(to_delete, key=lambda p: p.name):
        print(f"  {path.name}")

    if not args.apply:
        print("\ndry run -- pass --apply to delete")
        return 0

    freed = 0
    for path in to_delete:
        try:
            size = path.stat().st_size
            path.unlink()
            freed += size
            if args.verbose:
                print(f"  deleted {path.name}")
        except OSError as exc:
            print(f"  ERROR deleting {path.name}: {exc}", file=sys.stderr)
            return 1
    print(f"pruned {len(to_delete)} file(s), freed {freed / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
