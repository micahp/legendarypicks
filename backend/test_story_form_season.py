"""The form section must not present last season's logs as this season's form.

player_form labels its block with the season it read, and the writer kept
stripping the label — measured on game 761719: "Kelvin Yeboah ... no goals in
his last five matches", where those five are 2025-09-14..2025-11-25, nine months
before a preview of the 2026 MLS season. The label is not the guard; suppression
is. A preview with no form line is honest; one with last year's form presented
as this year's is the thing honest-data-ui exists to prevent.
"""
import sqlite3

import pytest

from conftest import real_db
from core_stories import _logs_predate_season, _season_year_from_name


def _open(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _form_test_db(tmp_path):
    """A temp file DB with the tables generate_game_story touches, plus mls logs.

    A fresh connection per call, matching _core._db() — generate_game_story closes
    the connection it opens, so a shared in-memory connection would die on the
    first `with closing(_db())`.
    """
    path = str(tmp_path / "form.db")
    con = _open(path)
    con.execute("CREATE TABLE player_game_logs("
                "player_id INT, league TEXT, season INT, team TEXT, game_date TEXT, "
                "game_no INT, stats TEXT)")
    con.execute("CREATE TABLE players(id INT, name TEXT)")
    con.execute("CREATE TABLE props(id INT, game_id INT, player_id INT, market TEXT, side TEXT, line REAL)")
    con.execute("CREATE TABLE prop_games(id INT, league TEXT, espn_event_id TEXT)")
    con.commit()
    con.close()
    return path


def _log(con, player, league, season, team, date, no, stats):
    con.execute(
        "INSERT INTO player_game_logs(player_id, league, season, team, game_date, game_no, stats) "
        "VALUES (?,?,?,?,?,?,?)",
        (player, league, season, team, date, no, stats))
    con.commit()


def _fake_summary(season_year):
    return {"header": {"season": {"year": season_year, "name": f"{season_year} MLS, Regular Season"}}}


class TestSeasonYearFromName:
    def test_a_full_season_name_yields_its_year(self):
        assert _season_year_from_name("2026 MLS, Regular Season") == 2026

    def test_a_bare_year_yields_itself(self):
        assert _season_year_from_name("2025") == 2025

    def test_a_season_without_a_year_yields_nothing(self):
        assert _season_year_from_name("Regular Season") is None
        assert _season_year_from_name("") is None
        assert _season_year_from_name(None) is None


class TestLogsPredateSeason:
    def test_last_years_logs_in_this_years_game_are_stale(self):
        # The measured shape: mls logs stop at 2025, the preview is 2026.
        assert _logs_predate_season(2026, 2025) is True

    def test_same_season_logs_are_not_stale(self):
        assert _logs_predate_season(2026, 2026) is False

    def test_current_season_logs_for_a_prior_season_game_are_not_stale(self):
        # An NFL game in January 2026 belongs to the 2025 season.
        assert _logs_predate_season(2025, 2026) is False

    def test_unknowns_never_suppress(self):
        assert _logs_predate_season(None, 2025) is False
        assert _logs_predate_season(2026, None) is False
        assert _logs_predate_season(None, None) is False


class TestAgainstTheRealDatabases:
    """The actual data shape that broke: stale-log leagues vs current-log ones."""

    @pytest.mark.parametrize(
        "league,game_season,expect_stale",
        [
            ("mls", 2026, True),    # logs stop at 2025, 2026 games are being previewed
            ("ncaaf", 2026, True),  # logs stop at 2025, 2026 season starts Aug 29
            ("nfl", 2026, True),    # logs stop at 2025, 2026 preseason underway
            ("mlb", 2026, False),   # 2026 logs exist
            ("nba", 2026, False),   # 2026 logs exist
            ("nhl", 2026, False),   # 2026 logs exist
        ],
    )
    def test_real_log_seasons_against_a_real_game_season(self, league, game_season, expect_stale):
        path = real_db("picks.dev.db")
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            pytest.skip(f"{path} not present")
        try:
            newest = con.execute(
                "SELECT MAX(season) FROM player_game_logs WHERE league=?", (league,)).fetchone()[0]
        finally:
            con.close()
        assert _logs_predate_season(game_season, newest) is expect_stale, (
            f"{league}: newest log season {newest} vs game season {game_season}")


class TestSuppressedFormLifecycle:
    """A suppressed-form story must not be final: it flags WHY the form is missing
    and regenerates once the day the logs catch up to the game's season."""

    def _generate(self, path, monkeypatch, season_year, story_text="WRITTEN"):
        import _core
        import espn_client as espn
        from core_stories import generate_game_story

        calls = []
        monkeypatch.setattr(_core, "_db", lambda: _open(path))
        monkeypatch.setattr(_core, "_deepseek_chat",
                            lambda *a, **k: calls.append(1) or story_text)
        monkeypatch.setattr(espn, "game_result", lambda lg, gid: {})
        monkeypatch.setattr(espn, "summary", lambda lg, gid: _fake_summary(season_year))
        monkeypatch.setattr(espn, "team_strength_map", lambda lg: {})
        monkeypatch.setattr(espn, "team_strength", lambda lg: [])
        return generate_game_story("mls", "g1", home="H", away="A",
                                   state="pre", start_time="2026-08-15T23:30Z"), calls

    def _row(self, path):
        con = _open(path)
        try:
            return con.execute(
                "SELECT story, has_form, form_suppressed FROM game_story WHERE league='mls' AND game_id='g1'"
            ).fetchone()
        finally:
            con.close()

    def test_suppressed_story_is_flagged_and_does_not_loop(self, tmp_path, monkeypatch):
        path = _form_test_db(tmp_path)
        con = _open(path)
        _log(con, 1, "mls", 2025, "H", "2025-11-20", 1, '{"goals": 0}')
        con.close()
        _, calls = self._generate(path, monkeypatch, season_year=2026)
        row = self._row(path)
        # 2025 logs under a 2026 game: form suppressed, and the flag records why.
        assert row["form_suppressed"] == 1
        # Re-running while the logs are still stale writes nothing new — the
        # per-invocation call list is empty on the second run.
        _, calls2 = self._generate(path, monkeypatch, season_year=2026, story_text="SECOND")
        assert calls2 == [], "a still-stale story must not regenerate"

    def test_suppressed_story_regenerates_once_when_logs_catch_up(self, tmp_path, monkeypatch):
        path = _form_test_db(tmp_path)
        con = _open(path)
        _log(con, 1, "mls", 2025, "H", "2025-11-20", 1, '{"goals": 0}')
        con.close()
        _, calls = self._generate(path, monkeypatch, season_year=2026)
        assert len(calls) == 1
        # 2026 logs land for the home team (3+ games = real form).
        con = _open(path)
        con.execute("INSERT INTO players(id, name) VALUES (7, 'Test Striker')")
        for i, date in enumerate(["2026-03-01", "2026-03-08", "2026-03-15"]):
            _log(con, 7, "mls", 2026, "H", date, i + 1, '{"goals": 1}')
        con.close()
        _, calls2 = self._generate(path, monkeypatch, season_year=2026, story_text="WITH FORM")
        assert len(calls2) == 1, "the day logs catch up, the story regenerates once"
        row = self._row(path)
        assert row["story"] == "WITH FORM"
        assert row["form_suppressed"] == 0
        # And now it is final: a third run writes nothing.
        _, calls3 = self._generate(path, monkeypatch, season_year=2026, story_text="THIRD")
        assert calls3 == []

    def test_current_logs_write_without_the_flag(self, tmp_path, monkeypatch):
        path = _form_test_db(tmp_path)
        con = _open(path)
        _log(con, 1, "mls", 2026, "H", "2026-03-01", 1, '{"goals": 0}')
        con.close()
        self._generate(path, monkeypatch, season_year=2026)
        assert self._row(path)["form_suppressed"] == 0
