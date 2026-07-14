#!/usr/bin/env python3
"""migrate_team_stats.py — create a fresh proof database with the canonical schema.

Mandatory flags: --db-path, --report, --create-new, --min-available-mib.
No defaults for paths.  Rejects protected substrings, existing paths, symlinks,
hardlinks, and anything outside /tmp.  Creates the file with O_CREAT|O_EXCL|
O_NOFOLLOW mode 0600, verifies inode identity, and runs the schema in one
transaction followed by integrity_check.  The report is also created with
exclusive no-follow semantics.  Never deletes or overwrites an existing file.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from team_stats_schema import DDL, SCHEMA_VERSION  # noqa: E402

PROTECTED_SUBSTRINGS = [
    "legendarypicks",
    "lp-pick-desk",
    "picks.db",
    "picks.dev.db",
]

REQUIRED_PARENT = "/tmp"


# ---------------------------------------------------------------------------
# path validation helpers
# ---------------------------------------------------------------------------

def _parent_is_exactly_tmp(abspath: str) -> bool:
    parent = os.path.realpath(os.path.dirname(abspath))
    return parent == REQUIRED_PARENT


def _validate_db_path(db_path: str) -> str:
    """Return the resolved absolute path or exit with code 2."""
    if not os.path.isabs(db_path):
        print(f"REJECTED: db_path must be absolute, got {db_path}", file=sys.stderr)
        sys.exit(2)

    resolved = os.path.realpath(os.path.dirname(db_path))
    if resolved != REQUIRED_PARENT:
        print(f"REJECTED: db_path parent must be exactly /tmp, "
              f"resolved to {resolved}", file=sys.stderr)
        sys.exit(2)

    lower = db_path.lower()
    for bad in PROTECTED_SUBSTRINGS:
        if bad in lower:
            print(f"REJECTED: db_path contains protected substring '{bad}'",
                  file=sys.stderr)
            sys.exit(2)

    if os.path.lexists(db_path):
        if os.path.islink(db_path):
            print(f"REJECTED: {db_path} is a symlink", file=sys.stderr)
            sys.exit(2)
        if not os.path.isfile(db_path):
            print(f"REJECTED: {db_path} is not a regular file", file=sys.stderr)
            sys.exit(2)
        st = os.stat(db_path)
        if st.st_nlink != 1:
            print(f"REJECTED: {db_path} st_nlink={st.st_nlink}, expected 1",
                  file=sys.stderr)
            sys.exit(2)
        if st.st_uid != os.getuid():
            print(f"REJECTED: {db_path} owned by uid={st.st_uid}, "
                  f"expected {os.getuid()}", file=sys.stderr)
            sys.exit(2)
        print(f"REJECTED: {db_path} already exists", file=sys.stderr)
        sys.exit(2)

    return db_path


def _report_path_error(report_path: str) -> str | None:
    """Return a rejection reason if the report path is unusable, else None.

    Pure predicate so callers (create_database) can convert a bad report path
    into a success=False report; _validate_report_path keeps the exit-on-reject
    contract for direct callers/tests.
    """
    if not os.path.isabs(report_path):
        return f"report path must be absolute, got {report_path}"
    if os.path.lexists(report_path):
        return f"report path already exists: {report_path}"
    return None


def _validate_report_path(report_path: str) -> str:
    reason = _report_path_error(report_path)
    if reason is not None:
        print(f"REJECTED: {reason}", file=sys.stderr)
        sys.exit(2)
    return report_path


# ---------------------------------------------------------------------------
# memory guard
# ---------------------------------------------------------------------------

def _check_memory(min_mib: int) -> None:
    """Abort if MemAvailable < min_mib MiB."""
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    if kb < min_mib * 1024:
                        print(f"HARD ABORT: MemAvailable={kb // 1024} MiB < "
                              f"{min_mib} MiB", file=sys.stderr)
                        sys.exit(3)
                    return
    except Exception:
        pass
    print("WARNING: could not read /proc/meminfo, proceeding", file=sys.stderr)


# ---------------------------------------------------------------------------
# file creation
# ---------------------------------------------------------------------------

def _create_exclusive_nofollow(path: str, mode: int = 0o600) -> int:
    """Create *path* with O_CREAT|O_EXCL|O_NOFOLLOW.  Returns the fd."""
    try:
        flags = os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_RDWR
    except AttributeError:
        flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
    fd = os.open(path, flags, mode)
    return fd


def _create_db_file(db_path: str) -> tuple[int, int]:
    """Create the db file.  Returns (fd, inode)."""
    fd = _create_exclusive_nofollow(db_path, 0o600)
    try:
        st = os.fstat(fd)
        inode = st.st_ino
        if st.st_nlink != 1:
            os.close(fd)
            print(f"REJECTED: after creation st_nlink={st.st_nlink}",
                  file=sys.stderr)
            sys.exit(2)
        if st.st_uid != os.getuid():
            os.close(fd)
            print(f"REJECTED: owner uid={st.st_uid} != {os.getuid()}",
                  file=sys.stderr)
            sys.exit(2)
    except Exception:
        os.close(fd)
        raise
    return fd, inode


# ---------------------------------------------------------------------------
# main logic
# ---------------------------------------------------------------------------

def create_database(db_path: str, report_path: str, min_available_mib: int) -> dict:
    """Validate, create, migrate, and report.  Returns the report dict."""
    _validate_db_path(db_path)
    report_err = _report_path_error(report_path)
    if report_err is not None:
        print(f"REJECTED: {report_err}", file=sys.stderr)
        return {
            "action": "migrate",
            "db_path": db_path,
            "report_path": report_path,
            "schema_version": SCHEMA_VERSION,
            "success": False,
            "integrity_check": None,
            "error": report_err,
        }
    _check_memory(min_available_mib)

    # --- create db file ---
    fd, inode = _create_db_file(db_path)
    os.close(fd)

    # --- verify inode stable, then open ---
    st = os.stat(db_path)
    if st.st_ino != inode:
        print(f"REJECTED: inode changed before open "
              f"({inode} -> {st.st_ino})", file=sys.stderr)
        sys.exit(2)
    if st.st_nlink != 1:
        print(f"REJECTED: st_nlink={st.st_nlink} at open", file=sys.stderr)
        sys.exit(2)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    report = {
        "action": "migrate",
        "db_path": db_path,
        "report_path": report_path,
        "schema_version": SCHEMA_VERSION,
        "success": False,
        "integrity_check": None,
        "error": None,
    }

    try:
        # --- verify inode still matches after sqlite3 opens ---
        st2 = os.stat(db_path)
        if st2.st_ino != inode:
            report["error"] = f"inode changed after open ({inode} -> {st2.st_ino})"
            return report

        # --- run DDL in one transaction ---
        connection.execute("BEGIN")
        try:
            connection.executescript(DDL)
            connection.execute(
                "INSERT INTO schema_migrations(version) VALUES(?)",
                (SCHEMA_VERSION,),
            )
        except Exception:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.commit()

        # --- integrity check ---
        ok = connection.execute("PRAGMA integrity_check").fetchone()[0]
        report["integrity_check"] = ok
        if ok != "ok":
            report["error"] = f"integrity_check: {ok}"
            return report

        report["success"] = True

    except Exception as exc:
        report["error"] = str(exc)
        return report
    finally:
        connection.close()

    # --- verify st_nlink post-close ---
    st3 = os.stat(db_path)
    if st3.st_nlink != 1:
        report["error"] = f"post-close st_nlink={st3.st_nlink}"
        report["success"] = False

    # --- write report as exclusive new file ---
    import json
    rfd = _create_exclusive_nofollow(report_path, 0o600)
    try:
        os.write(rfd, json.dumps(report, indent=2).encode("utf-8"))
    finally:
        os.close(rfd)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a fresh proof database with the canonical team-stats schema.")
    parser.add_argument(
        "--db-path", required=True,
        help="Absolute path for the new SQLite DB (parent must be /tmp).")
    parser.add_argument(
        "--report", required=True,
        help="Absolute path for the JSON report (must not exist).")
    parser.add_argument(
        "--create-new", required=True,
        help="Confirmation flag — must be exactly 'yes' to proceed.")
    parser.add_argument(
        "--min-available-mib", required=True, type=int,
        help="Minimum MemAvailable in MiB; hard-abort below this threshold.")
    args = parser.parse_args()

    if args.create_new != "yes":
        print("ERROR: --create-new must be 'yes' to confirm database creation",
              file=sys.stderr)
        sys.exit(2)

    report = create_database(args.db_path, args.report, args.min_available_mib)

    if report["success"]:
        print(f"OK: database created at {args.db_path}")
        print(f"    integrity_check: {report['integrity_check']}")
        print(f"    report: {args.report}")
        sys.exit(0)
    else:
        print(f"FAILED: {report.get('error', 'unknown error')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
