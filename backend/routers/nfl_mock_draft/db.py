"""Database connection and initialization for the NFL mock-draft package."""

import sqlite3
import sys


def _conn():
    """Open the database named by the PACKAGE, resolved at call time.

    `from .constants import _DB` binds a copy at import, and the tests redirect
    the database by rebinding `nfl_mock_draft._DB` on the package. Against a
    copy that assignment does nothing: every connection still opens the real
    file. Measured 2026-08-18, right after the split, 36 mock-draft tests
    errored with `no such table: player_game_logs` because they were pointed at
    a fixture and silently reading production instead. Resolving through the
    package is what makes the redirection real -- the same call-time lookup the
    other split packages use for their patched names.
    """
    from . import constants
    package = sys.modules[__package__]
    # `constants` is the fallback only for the window during package import,
    # before `__init__` has rebound the name. It is never the value a test set.
    connection = sqlite3.connect(getattr(package, "_DB", constants._DB))
    connection.row_factory = sqlite3.Row
    return connection


def _init_db():
    """Create the mock-draft tables defensively.

    A table-init failure must not prevent the sports API from starting
    (same pattern as ``ufc_picks.py``).
    """
    try:
        connection = _conn()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS nfl_mock_drafts (
                    id          TEXT PRIMARY KEY,
                    device_id   TEXT    NOT NULL,
                    user_id     INTEGER,
                    season      INTEGER NOT NULL,
                    seat        INTEGER NOT NULL,
                    teams       INTEGER NOT NULL DEFAULT 12,
                    rounds      INTEGER NOT NULL DEFAULT 15,
                    seed        INTEGER NOT NULL,
                    status      TEXT    NOT NULL,
                    created_at  INTEGER NOT NULL,
                    updated_at  INTEGER NOT NULL,
                    completed_at INTEGER
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS nfl_mock_draft_picks (
                    draft_id   TEXT    NOT NULL,
                    pick_no    INTEGER NOT NULL,
                    team_no    INTEGER NOT NULL,
                    player_id  INTEGER NOT NULL,
                    auto       INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (draft_id, pick_no)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_mock_drafts_device "
                "ON nfl_mock_drafts(device_id, season)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_mock_draft_picks_draft "
                "ON nfl_mock_draft_picks(draft_id)"
            )
            connection.commit()
        finally:
            connection.close()
    except Exception:
        # A table-init failure must not prevent the sports API from starting.
        pass


_init_db()