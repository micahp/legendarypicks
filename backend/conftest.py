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


@pytest.fixture(autouse=True)
def _restore_db_path_env():
    """Reset LP_DB_PATH to the session's value before each test."""
    if _SESSION_DB_PATH is None:
        os.environ.pop("LP_DB_PATH", None)
    else:
        os.environ["LP_DB_PATH"] = _SESSION_DB_PATH
    yield
