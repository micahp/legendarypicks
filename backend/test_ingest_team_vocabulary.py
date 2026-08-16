"""test_ingest_team_vocabulary.py — data-integrity: no non-canonical team codes in DB.

Runs against both checked-in databases. Every assertion here used to be keyed on
LP_DB_PATH, which is unset in a plain `pytest backend`, so all 15 of these
skipped on every suite run and the file reported green without opening a
database. They pass — verified 2026-08-13, 32 distinct NFL codes and 30 MLB in
each — but nothing in the suite was establishing that.

Pointing them at one database would have rebuilt half the hole. dev being green
while prod never ran is this project's most repeated failure, so the fixture is
parametrised over both files and named by where the code lives, not by an env
var or the directory pytest was invoked from.
"""
from __future__ import annotations

import sqlite3

import pytest

from conftest import real_db
from team_codes import CANONICAL

# nfl_pbp is absent from picks.db because the retained-play feature has not been
# deployed there — docs/SCHEMA-DRIFT-AUDIT-2026-07-28.md:61, "not required by
# draft readers". That is a deployment state, not an architectural split, so
# this set is a record of what is true today rather than a rule about what
# belongs where. It reads correctly either way: the exemption only applies while
# the table is missing, so the day pbp ships to prod these four go from skipped
# to enforced with no edit here.
#
# The point of naming it at all is the other branch — a table missing from a
# database that is supposed to have it is now an assertion failure naming the
# database, where before it surfaced as a raw "no such table" OperationalError.
DEV_ONLY_TABLES = {"nfl_pbp"}


class _NamedConnection(sqlite3.Connection):
    """A connection that remembers which database it is, for failure messages.

    sqlite3.Connection has no __dict__, so the name cannot simply be attached
    after connect(); which file a code came from is the whole point of a
    two-database parametrisation, so it travels with the connection.
    """

    lp_name = "?"


@pytest.fixture(scope="module", params=["picks.db", "picks.dev.db"])
def con(request):
    path = real_db(request.param)
    try:
        conn = sqlite3.connect(
            f"file:{path}?mode=ro", uri=True, factory=_NamedConnection
        )
    except sqlite3.OperationalError:
        pytest.skip(f"{path} not present")
    conn.row_factory = sqlite3.Row
    conn.lp_name = request.param
    yield conn
    conn.close()


# -- helpers ------------------------------------------------------------------


def _assert_all_canonical(
    con: sqlite3.Connection,
    league: str,
    table: str,
    column: str,
    where: str = "1=1",
) -> None:
    """Query DISTINCT values and fail if any is outside CANONICAL[league]."""
    canonical = CANONICAL.get(league)
    if canonical is None:
        pytest.skip(f"league {league!r} not in CANONICAL")

    db = con.lp_name
    if not con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone():
        if table in DEV_ONLY_TABLES and db == "picks.db":
            pytest.skip(f"{table} is not deployed to {db} yet")
        raise AssertionError(f"[{league}] {db} has no table {table}")

    rows = con.execute(
        f'SELECT DISTINCT "{column}" FROM {table} WHERE {where} AND "{column}" IS NOT NULL AND "{column}" != \'\''
    ).fetchall()

    # No rows means every code in the column is canonical the way an empty room
    # is a quiet one. These tests exist to read a vocabulary off real data, so a
    # column that yields nothing is a failed read, not a clean bill of health.
    assert rows, f"[{league}] {db}.{table}.{column} returned no values to check"

    bad = []
    for r in rows:
        val = r[column]
        if isinstance(val, bytes):
            val = val.decode("utf-8")
        val = str(val).strip().upper()
        if val not in canonical:
            bad.append(val)

    if bad:
        bad_str = ", ".join(sorted(bad))
        raise AssertionError(
            f"[{league}] {db} {table}.{column} has {len(bad)} non-canonical code(s): {bad_str}"
        )


# -- NFL ----------------------------------------------------------------------


def test_nfl_players_team(con):
    _assert_all_canonical(con, "nfl", "players", "team", "league='nfl'")


def test_nfl_player_game_logs_team(con):
    _assert_all_canonical(con, "nfl", "player_game_logs", "team", "league='nfl'")


def test_nfl_player_game_logs_opponent(con):
    _assert_all_canonical(con, "nfl", "player_game_logs", "opponent", "league='nfl'")


def test_nfl_player_stats_team(con):
    # player_stats lacks a league column — filter to rows that have an nfl_team
    _assert_all_canonical(con, "nfl", "player_stats", "team", "nfl_team IS NOT NULL")


def test_nfl_player_stats_nfl_team(con):
    _assert_all_canonical(con, "nfl", "player_stats", "nfl_team")


def test_nfl_team_game_results_team(con):
    _assert_all_canonical(con, "nfl", "team_game_results", "team", "league='nfl'")


def test_nfl_team_game_results_opponent(con):
    _assert_all_canonical(con, "nfl", "team_game_results", "opponent", "league='nfl'")


def test_nfl_schedule_home_team(con):
    _assert_all_canonical(con, "nfl", "nfl_schedule", "home_team")


def test_nfl_schedule_away_team(con):
    _assert_all_canonical(con, "nfl", "nfl_schedule", "away_team")


def test_nfl_depth_chart_team(con):
    _assert_all_canonical(con, "nfl", "nfl_depth_chart", "team")


def test_nfl_pbp_posteam(con):
    _assert_all_canonical(con, "nfl", "nfl_pbp", "posteam")


def test_nfl_pbp_defteam(con):
    _assert_all_canonical(con, "nfl", "nfl_pbp", "defteam")


def test_nfl_pbp_home_team(con):
    _assert_all_canonical(con, "nfl", "nfl_pbp", "home_team")


def test_nfl_pbp_away_team(con):
    _assert_all_canonical(con, "nfl", "nfl_pbp", "away_team")


# -- MLB / NHL: the migration was NFL-only -------------------------------------
#
# These were `@pytest.mark.skip("migration not yet applied")`. A blanket skip
# makes no claim, so it cannot go stale loudly — and two of the five had in fact
# gone stale: NHL player_game_logs.team and .opponent are clean on both
# databases and are now plain tests below.
#
# The three that really are dirty are xfail(strict), not skip. Measured
# 2026-08-13, identical on picks.db and picks.dev.db:
#
#   mlb player_game_logs.team/.opponent   AZ, CWS      (canonical: ARI, CHW)
#   nhl players.team                      LAK, TBL, UTA, and SJS on prod only
#
# The NHL codes are the NHL API's own vocabulary reaching a column that is meant
# to hold ESPN's — the vocabulary-boundary shape, not a migration that merely
# has not been run yet. strict=True means the day the migration lands these fail
# as unexpectedly passing, which is the only reason this comment ever gets read.


def test_mlb_players_team(con):
    _assert_all_canonical(con, "mlb", "players", "team", "league='mlb'")


@pytest.mark.xfail(strict=True, reason="MLB game logs carry AZ/CWS, not canonical ARI/CHW")
def test_mlb_player_game_logs_team(con):
    _assert_all_canonical(con, "mlb", "player_game_logs", "team", "league='mlb'")


@pytest.mark.xfail(strict=True, reason="MLB game logs carry AZ/CWS, not canonical ARI/CHW")
def test_mlb_player_game_logs_opponent(con):
    _assert_all_canonical(con, "mlb", "player_game_logs", "opponent", "league='mlb'")


@pytest.mark.xfail(strict=True, reason="NHL players.team carries NHL-API codes LAK/TBL/UTA (+SJS on prod)")
def test_nhl_players_team(con):
    _assert_all_canonical(con, "nhl", "players", "team", "league='nhl'")


def test_nhl_player_game_logs_team(con):
    _assert_all_canonical(con, "nhl", "player_game_logs", "team", "league='nhl'")


def test_nhl_player_game_logs_opponent(con):
    _assert_all_canonical(con, "nhl", "player_game_logs", "opponent", "league='nhl'")
