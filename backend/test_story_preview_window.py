"""A preview is written for the game about to be played, from facts true of it.

NBA 401902644 (Raptors at Heat, preseason, 2026-10-03) carried a preview written on
2026-08-17 from last season's final records, streaks and form, framed as a standings
race, and cached as final. Three rules close it: no preview more than
PREVIEW_HORIZON_HOURS before tip (and a cached one written earlier is not served),
no records/form when the standings are another season's, and a preseason game is
grounded as an exhibition with no stakes.
"""
import datetime as dt
import sqlite3

import pytest

import core_stories as cs

NOW = dt.datetime(2026, 10, 2, 20, 0, tzinfo=dt.timezone.utc)


def test_too_early_beyond_the_horizon():
    assert cs._too_early_for_preview("2026-10-08T23:30:00Z", now=NOW) is True
    assert cs._too_early_for_preview("2026-10-03T23:30:00Z", now=NOW) is False
    assert cs._too_early_for_preview(None, now=NOW) is False
    assert cs._too_early_for_preview("garbage", now=NOW) is False


def test_preview_written_seven_weeks_early_is_not_final():
    assert cs._preview_written_too_early("2026-08-17 14:02:11", "2026-10-03T23:30Z") is True
    assert cs._preview_written_too_early("2026-10-03 09:00:00", "2026-10-03T23:30Z") is False
    assert cs._preview_written_too_early(None, "2026-10-03T23:30Z") is False


def test_standings_from_another_season():
    assert cs._standings_out_of_season(2026, 2027) is True
    assert cs._standings_out_of_season(2026, 2026) is False
    assert cs._standings_out_of_season(None, 2027) is False


def _db(tmp_path):
    path = str(tmp_path / "s.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE player_game_logs(player_id INT, league TEXT, season INT, team TEXT, "
                "game_date TEXT, game_no INT, stats TEXT)")
    con.execute("CREATE TABLE players(id INT, name TEXT)")
    con.execute("CREATE TABLE props(id INT, game_id INT, player_id INT, market TEXT, side TEXT, line REAL)")
    con.execute("CREATE TABLE prop_games(id INT, league TEXT, espn_event_id TEXT)")
    con.commit()
    con.close()
    return path


def _open(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


@pytest.fixture
def harness(tmp_path, monkeypatch):
    import _core
    import espn_client as espn
    import stakes
    path = _db(tmp_path)
    seen = {"grounding": [], "stakes": 0}
    monkeypatch.setattr(_core, "_db", lambda: _open(path))
    monkeypatch.setattr(_core, "_deepseek_chat",
                        lambda system, grounding: seen["grounding"].append(grounding) or "STORY")
    monkeypatch.setattr(espn, "game_result", lambda lg, gid: {"state": "pre", "home": "MIA"})
    monkeypatch.setattr(espn, "summary", lambda lg, gid: {
        "header": {"season": {"year": 2027, "type": seen.get("type", 1), "name": "2026-27 Preseason"}},
        "lastFiveGames": [{"team": {"displayName": "Miami Heat"},
                           "events": [{"gameResult": "W", "score": "110-100", "gameDate": "2026-04-12T23:00Z",
                                       "opponent": {"abbreviation": "ORL"}}]}]})
    monkeypatch.setattr(espn, "team_strength_standings", lambda lg, season=None: {
        "season": seen.get("standings_season", 2026),
        "teams": [{"abbrev": "MIA", "name": "Miami Heat", "wins": 37, "losses": 45, "win_pct": 0.451,
                   "streak": "W1", "last10": "5-5", "differential": -1.2}]})
    monkeypatch.setattr(stakes, "for_matchup",
                        lambda *a: seen.__setitem__("stakes", seen["stakes"] + 1) or ["race line"])
    return path, seen


def _gen(start, state="pre"):
    return cs.generate_game_story("nba", "401902644", home="MIA", away="TOR", state=state, start_time=start)


def _soon():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=20)).strftime("%Y-%m-%dT%H:%MZ")


def _far():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10)).strftime("%Y-%m-%dT%H:%MZ")


def test_no_preview_written_beyond_the_horizon(harness):
    path, seen = harness
    out = _gen(_far())
    assert out["story"] is None and seen["grounding"] == []


def test_preseason_preview_has_no_last_season_records_form_or_stakes(harness):
    path, seen = harness
    _gen(_soon())
    g = seen["grounding"][-1]
    assert "37-45" not in g and "W1" not in g and "ORL" not in g
    assert "no games played yet this season" in g
    assert "PRESEASON EXHIBITION" in g
    assert seen["stakes"] == 0


def test_in_season_records_still_flow(harness):
    path, seen = harness
    seen["type"], seen["standings_season"] = 2, 2027
    _gen(_soon())
    g = seen["grounding"][-1]
    assert "37-45" in g and "PRESEASON" not in g


def test_preview_cached_seven_weeks_early_is_rewritten_inside_the_window(harness):
    path, seen = harness
    con = _open(path)
    con.execute("CREATE TABLE game_story(league TEXT, game_id TEXT, story TEXT, generated_at TEXT, "
                "has_form INTEGER DEFAULT 0, has_stakes INTEGER DEFAULT 0, form_suppressed INTEGER DEFAULT 0, "
                "PRIMARY KEY(league, game_id))")
    con.execute("INSERT INTO game_story VALUES ('nba','401902644','OLD STANDINGS RACE','2026-08-17 14:02:11',1,1,0)")
    con.commit()
    con.close()
    out = _gen(_soon())
    assert out["story"] == "STORY" and len(seen["grounding"]) == 1


def test_preview_cached_too_early_is_not_served_while_still_too_early(harness):
    path, seen = harness
    con = _open(path)
    con.execute("CREATE TABLE game_story(league TEXT, game_id TEXT, story TEXT, generated_at TEXT, "
                "has_form INTEGER DEFAULT 0, has_stakes INTEGER DEFAULT 0, form_suppressed INTEGER DEFAULT 0, "
                "PRIMARY KEY(league, game_id))")
    con.execute("INSERT INTO game_story VALUES ('nba','401902644','OLD STANDINGS RACE','2026-08-17 14:02:11',1,1,0)")
    con.commit()
    con.close()
    out = _gen(_far())
    assert out["story"] is None and seen["grounding"] == []


def test_kick_skips_games_beyond_the_horizon(monkeypatch, harness):
    started = []
    monkeypatch.setattr(cs._threading, "Thread", lambda target, daemon: started.append(target) or type(
        "T", (), {"start": lambda self: None})())
    cs.kick_game_stories("nba", [
        {"game_id": "far", "home": {"abbrev": "MIA"}, "away": {"abbrev": "TOR"}, "state": "pre", "date": _far()},
        {"game_id": "soon", "home": {"abbrev": "MIA"}, "away": {"abbrev": "TOR"}, "state": "pre", "date": _soon()},
    ])
    assert len(started) == 1
