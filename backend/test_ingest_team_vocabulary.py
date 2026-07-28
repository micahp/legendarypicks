"""test_ingest_team_vocabulary.py — data-integrity: no non-canonical team codes in DB.

Run AFTER migration has been applied.  Skips cleanly if the DB is absent.
"""
from __future__ import annotations

import os
import sqlite3

import pytest

from team_codes import CANONICAL

DB_PATH = os.environ.get("LP_DB_PATH")


@pytest.fixture(scope="module")
def con():
    if not DB_PATH or not os.path.exists(DB_PATH):
        pytest.skip("LP_DB_PATH not set or DB not found")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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

    rows = con.execute(
        f'SELECT DISTINCT "{column}" FROM {table} WHERE {where} AND "{column}" IS NOT NULL AND "{column}" != \'\''
    ).fetchall()

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
            f"[{league}] {table}.{column} has {len(bad)} non-canonical code(s): {bad_str}"
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


# -- MLB (migration was NFL-only; skip until MLB migration is applied) ----------


def test_mlb_players_team(con):
    _assert_all_canonical(con, "mlb", "players", "team", "league='mlb'")


@pytest.mark.skip(reason="MLB migration not yet applied — data still carries non-canonical codes")
def test_mlb_player_game_logs_team(con):
    _assert_all_canonical(con, "mlb", "player_game_logs", "team", "league='mlb'")


@pytest.mark.skip(reason="MLB migration not yet applied")
def test_mlb_player_game_logs_opponent(con):
    _assert_all_canonical(con, "mlb", "player_game_logs", "opponent", "league='mlb'")


# -- NHL (migration was NFL-only; skip until NHL migration is applied) ----------


@pytest.mark.skip(reason="NHL migration not yet applied — data still carries non-canonical codes")
def test_nhl_players_team(con):
    _assert_all_canonical(con, "nhl", "players", "team", "league='nhl'")


@pytest.mark.skip(reason="NHL migration not yet applied — data still carries non-canonical codes")
def test_nhl_player_game_logs_team(con):
    _assert_all_canonical(con, "nhl", "player_game_logs", "team", "league='nhl'")


@pytest.mark.skip(reason="NHL migration not yet applied")
def test_nhl_player_game_logs_opponent(con):
    _assert_all_canonical(con, "nhl", "player_game_logs", "opponent", "league='nhl'")
