"""A preview is written for the game about to be played, from facts true of it.

NBA 401902644 (Heat at Raptors in Quebec City, preseason, 2026-10-03) carried a preview written on
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
    con.execute("CREATE TABLE scoreboard_snapshots(league TEXT, game_id TEXT, state TEXT, "
                "payload TEXT, fetched_at TEXT)")
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


def test_preseason_with_nothing_to_say_writes_nothing(harness):
    path, seen = harness
    out = _gen(_soon())
    assert out["story"] is None and seen["grounding"] == [] and seen["stakes"] == 0


def test_preseason_grounding_drops_last_season_but_keeps_current_form(harness, monkeypatch):
    import player_form
    path, seen = harness
    monkeypatch.setattr(player_form, "lines", lambda *a, **k: ["Bam Adebayo: 18 pts Oct 1"])
    monkeypatch.setattr(cs, "_logs_predate_season", lambda *a: False)
    _gen(_soon())
    g = seen["grounding"][-1]
    assert "37-45" not in g and "W1" not in g and "ORL" not in g
    assert "no games played yet this season" in g and "PRESEASON EXHIBITION" in g
    assert seen["stakes"] == 0


def test_rolled_over_table_of_zeros_is_no_record(harness, monkeypatch):
    import espn_client as espn
    path, seen = harness
    seen["standings_season"] = 2027
    monkeypatch.setattr(espn, "team_strength_standings", lambda lg, season=None: {
        "season": 2027, "teams": [{"abbrev": ab, "name": ab, "wins": 0, "losses": 0, "win_pct": 0}
                                  for ab in ("ATL", "BOS", "MIA", "TOR")]})
    out = _gen(_soon())
    assert out["story"] is None and seen["grounding"] == []


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
    seen["type"], seen["standings_season"] = 2, 2027
    out = _gen(_soon())
    assert out["story"] == "STORY" and len(seen["grounding"]) == 1


def test_stored_preview_with_nothing_behind_it_is_dropped(harness):
    path, seen = harness
    con = _open(path)
    con.execute("CREATE TABLE game_story(league TEXT, game_id TEXT, story TEXT, generated_at TEXT, "
                "has_form INTEGER DEFAULT 0, has_stakes INTEGER DEFAULT 0, form_suppressed INTEGER DEFAULT 0, "
                "PRIMARY KEY(league, game_id))")
    con.execute("INSERT INTO game_story VALUES ('nba','401902644','RANKED SEVENTH','2026-10-03 01:10:11',1,0,1)")
    con.commit()
    con.close()
    out = cs.generate_game_story("nba", "401902644", refresh=True, home="MIA", away="TOR",
                                 state="pre", start_time=_soon())
    assert out["story"] is None
    assert _open(path).execute("SELECT COUNT(*) FROM game_story").fetchone()[0] == 0


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


def test_unreadable_standings_cite_no_record(harness, monkeypatch):
    import espn_client as espn
    path, seen = harness

    def refused(lg, season=None):
        raise OSError("HTTP Error 403: Forbidden")
    monkeypatch.setattr(espn, "team_strength_standings", refused)
    seen["type"] = 2
    out = _gen(_soon())
    assert out["story"] is None and seen["grounding"] == []


def test_team_missing_from_the_table_gets_no_invented_record(harness):
    path, seen = harness
    seen["type"], seen["standings_season"] = 2, 2027
    _gen(_soon())
    g = seen["grounding"][-1]
    assert "None-None" not in g and "TOR: no published record" in g


def test_finished_nfl_story_uses_postgame_scoreboard_record(harness, monkeypatch):
    import json
    import espn_client as espn
    import matchup_context
    path, seen = harness
    con = _open(path)
    con.execute(
        "INSERT INTO scoreboard_snapshots VALUES (?,?,?,?,?)",
        ("nfl", "401872967", "post", json.dumps({
            "completed": True,
            "away": {"abbrev": "DAL", "name": "Dallas Cowboys", "record": "2-2"},
            "home": {"abbrev": "HOU", "name": "Houston Texans", "record": "0-4"},
        }), "2026-10-04T20:14:00Z"),
    )
    con.commit()
    con.close()
    monkeypatch.setattr(espn, "game_result", lambda lg, gid: {
        "state": "post", "home": "HOU", "winner": "DAL",
        "scores": {"DAL": 34.0, "HOU": 30.0}})
    monkeypatch.setattr(espn, "summary", lambda lg, gid: {
        "header": {"season": {"year": 2026, "type": 2,
                                "name": "2026 Regular Season"}}})
    monkeypatch.setattr(espn, "team_strength_standings", lambda lg, season=None: {
        "season": 2026, "teams": [
            {"abbrev": "DAL", "name": "Dallas Cowboys", "wins": 1, "losses": 2,
             "win_pct": .333, "streak": "L1", "last10": "1-2", "differential": -2},
            {"abbrev": "HOU", "name": "Houston Texans", "wins": 0, "losses": 3,
             "win_pct": 0, "streak": "L3", "last10": "0-3", "differential": -4},
        ]})
    monkeypatch.setattr(matchup_context, "context_lines", lambda *a, **k: [])

    out = cs.generate_game_story(
        "nfl", "401872967", refresh=True, home="HOU", away="DAL",
        state="post", start_time="2026-10-04T17:00:00Z")
    grounding = seen["grounding"][-1]
    assert out["story"] == "STORY"
    assert "Dallas Cowboys (DAL): post-game record 2-2" in grounding
    assert "Houston Texans (HOU): post-game record 0-4" in grounding
    assert "0-3" not in grounding and "1-2" not in grounding
    assert "quality rank" not in grounding


def test_post_scoreboard_row_must_be_completed(harness):
    import json
    path, _ = harness
    con = _open(path)
    con.execute(
        "INSERT INTO scoreboard_snapshots VALUES (?,?,?,?,?)",
        ("nfl", "postponed", "post", json.dumps({
            "completed": False,
            "away": {"abbrev": "DAL", "record": "2-2"},
            "home": {"abbrev": "HOU", "record": "0-4"},
        }), "2026-10-04T20:14:00Z"),
    )
    con.commit()
    con.close()

    assert cs._finished_scoreboard_records("nfl", "postponed") == {}
