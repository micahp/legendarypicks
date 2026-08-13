"""Which leagues a database is willing to offer, and the search gate built on it.

The bug this pins: having data for a league is not the same as offering it.
Production held 11,914 NCAAF players and 56,577 NCAAF game logs while the hub
offered only mlb/nba/nfl/nhl — and `/api/players/search?q=Bates` returned 4 NFL
players and 7 NCAAF players, each linking to a working player page. The league
was hidden from the surface that had a gate and reachable from the one that
didn't.
"""
import sqlite3

import pytest

from conftest import real_db
from league_offering import ALWAYS_OFFERED, offered_leagues, sql_league_filter


def _db(rows=()):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE team_stats_coverage(league TEXT, season INT, status TEXT)")
    con.executemany("INSERT INTO team_stats_coverage VALUES(?,?,?)", rows)
    return con


class TestOfferedLeagues:
    def test_vouched_statuses_are_offered(self):
        con = _db([("nfl", 2025, "complete"), ("mlb", 2026, "in_progress")])
        assert {"nfl", "mlb"} <= offered_leagues(con)

    def test_unvouched_status_is_not_offered(self):
        # The exact production shape: ncaaf has rows everywhere but no vouched
        # coverage row, so it must not be offered.
        con = _db([("nfl", 2025, "complete"), ("ncaaf", 2025, "unverified")])
        assert "ncaaf" not in offered_leagues(con)

    def test_a_league_absent_from_coverage_is_not_offered(self):
        con = _db([("nfl", 2025, "complete")])
        assert "ncaaf" not in offered_leagues(con)
        assert "mls" not in offered_leagues(con)

    def test_ufc_and_wc_are_offered_without_a_coverage_row(self):
        # Shape, not permission: they are not team-stats leagues and will never
        # have a row. Gating them on one would hide two leagues that ship today.
        assert ALWAYS_OFFERED <= offered_leagues(_db())

    def test_missing_registry_fails_closed(self):
        # No table at all. "Could not check" must not open the players table.
        con = sqlite3.connect(":memory:")
        assert offered_leagues(con) == frozenset(ALWAYS_OFFERED)

    def test_case_is_normalised(self):
        assert "nfl" in offered_leagues(_db([("NFL", 2025, "complete")]))

    def test_turns_on_when_a_row_is_promoted(self):
        # The self-correcting property: no league list to remember. mls appears
        # the moment its coverage row lands, and not before.
        assert "mls" not in offered_leagues(_db([("nfl", 2025, "complete")]))
        assert "mls" in offered_leagues(
            _db([("nfl", 2025, "complete"), ("mls", 2025, "complete")])
        )


class TestSqlLeagueFilter:
    def test_binds_names_as_parameters(self):
        sql, params = sql_league_filter(["nfl", "mlb"])
        assert "?" in sql and "nfl" not in sql
        assert params == ["mlb", "nfl"]

    def test_empty_set_yields_a_false_predicate_not_an_open_one(self):
        # An empty IN () is a syntax error and no filter at all returns
        # everything — the failure this module exists to prevent.
        sql, params = sql_league_filter([])
        assert sql == " AND 0"
        assert params == []

    def test_blank_names_are_dropped(self):
        sql, params = sql_league_filter(["nfl", "", None])
        assert params == ["nfl"]


class TestSearchAgainstTheRealDatabases:
    """The regression itself, against the files that had it."""

    @pytest.mark.parametrize("name", ["picks.db", "picks.dev.db"])
    def test_search_never_returns_an_unoffered_league(self, name):
        path = real_db(name)
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            pytest.skip(f"{path} not present")
        con.row_factory = sqlite3.Row
        try:
            offered = offered_leagues(con)
            league_sql, league_params = sql_league_filter(offered)
            rows = con.execute(
                "SELECT DISTINCT LOWER(p.league) AS lg FROM players p WHERE 1" + league_sql,
                league_params,
            ).fetchall()
        finally:
            con.close()
        # An empty result set satisfies "no league leaked" without having looked
        # at anything. This test's subject is the real file, so say so: a stub
        # standing in for the database must fail here, not pass quietly.
        assert rows, f"{path} returned no players — that is not a passing gate"
        leaked = {r["lg"] for r in rows} - offered
        assert not leaked, f"{path} would serve unoffered leagues: {leaked}"
