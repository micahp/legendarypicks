"""Keep LP_DB_PATH from leaking between test modules.

Several suites point LP_DB_PATH at a throwaway file before importing the app, so
that _core binds its module-level DB to a temp database instead of a real one.
That override is only needed for the duration of the import — _core resolves
``DB`` once, at import time — but none of them put the variable back, and pytest
imports every module during collection. The last one collected therefore decided
what LP_DB_PATH meant for the whole run.

The cost was real: _core's stat readers re-resolve LP_DB_PATH on every call, so
the real-database tests in test_nfl_usage ran against an empty temp file and
failed with "no such table: player_game_logs" — but only in a whole-suite run,
never when their own file was run alone. Restoring the value the session started
with makes a full run mean the same thing as a per-file run.

No suite reads LP_DB_PATH at run time to find its own fixture database; they all
capture what they need at import, so restoring it does not disturb them.
"""
import os

import pytest

_SESSION_DB_PATH = os.environ.get("LP_DB_PATH")

# The real-database suites named their targets "data/picks.dev.db" — relative to
# the working directory, not to the code. Run from backend/ that is the 357MB
# dev database; run from the repo root (`pytest backend`, which is how CI and a
# whole-suite run invoke it) it is /root/legendarypicks/data/picks.dev.db, a
# 0-byte file some script created on 2026-08-11 by opening the same relative
# path from the wrong directory. sqlite3 opens an empty file happily, so the
# "not present" guards did not fire: test_league_offering failed on "no such
# table: players", and test_team_stats_json read no columns and skipped itself
# as "not migrated yet" — a suite whose entire subject is the real database
# quietly asserting nothing. Anchoring to this file's directory makes a
# repo-root run mean the same thing as a per-file run, the same invariant the
# LP_DB_PATH fixture above exists to hold.
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))


def real_db(name):
    """Absolute path to a checked-in database, independent of the caller's cwd."""
    return os.path.join(BACKEND_DIR, "data", name)


@pytest.fixture(autouse=True)
def _restore_db_path_env():
    """Reset LP_DB_PATH to the session's value before each test."""
    if _SESSION_DB_PATH is None:
        os.environ.pop("LP_DB_PATH", None)
    else:
        os.environ["LP_DB_PATH"] = _SESSION_DB_PATH
    yield


# The app refuses to serve an un-migrated database at startup
# (sports_service._refuse_unmigrated_database). Tests point LP_DB_PATH at
# throwaway files and construct routers directly -- they are not real boots,
# so the migration check must not fire. See TASK-P1-migration-ledger.md.
os.environ.setdefault("LP_SKIP_MIGRATION_CHECK", "1")
