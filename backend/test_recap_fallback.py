"""The recap fallback: when no model answers, a finished game gets its result sentence.

The sentence states only the result, from the scores and winner the writer is handed. It is final once
written, because the result cannot change, and a stored model recap is never replaced by it. A preview
that was written before the final is replaced by it, so a finished game does not keep its preview
because the model was down.
"""
import sqlite3
import urllib.request

import pytest

import core_stories
import espn_client
import matchup_context
from core_stories import _result_sentence

NAMES = {"ATL": "Atlanta United", "CHI": "Chicago Fire"}
GAME = dict(lg="mls", game_id="1001", home="ATL", away="CHI", state="post",
            start_time="2026-10-26T23:00Z")


def test_the_winner_is_named_with_the_score():
    assert _result_sentence({"ATL": 2, "CHI": 1}, "ATL", NAMES) == "Atlanta United beat Chicago Fire 2-1."


def test_the_winner_is_matched_by_side_not_by_position():
    assert _result_sentence({"ATL": 2, "CHI": 3}, "CHI", NAMES) == "Chicago Fire beat Atlanta United 3-2."


def test_a_draw_says_so():
    assert _result_sentence({"ATL": 1, "CHI": 1}, None, NAMES) == "Atlanta United and Chicago Fire drew 1-1."


def test_a_side_without_a_name_is_written_as_its_abbrev():
    assert _result_sentence({"ATL": 2, "CHI": 1}, "ATL", {}) == "ATL beat CHI 2-1."


def test_a_winner_that_is_neither_side_is_not_guessed():
    assert _result_sentence({"ATL": 2, "CHI": 1}, "NYC", NAMES) is None


def test_more_or_fewer_than_two_sides_is_not_written():
    assert _result_sentence({"ATL": 2}, "ATL", NAMES) is None
    assert _result_sentence({"ATL": 2, "CHI": 1, "NYC": 0}, "ATL", NAMES) is None


def test_a_tie_with_a_winner_was_decided_another_way_and_is_not_written():
    assert _result_sentence({"ATL": 1, "CHI": 1}, "ATL", NAMES) is None


def test_a_missing_score_is_not_written():
    assert _result_sentence({"ATL": None, "CHI": 1}, "CHI", NAMES) is None


# Through generate_game_story: a temp database, every source stubbed, and urllib blocked so that a
# call which reaches the network fails the test instead of spending the ESPN budget.

@pytest.fixture
def world(tmp_path, monkeypatch):
    path = str(tmp_path / "recap.db")
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE player_game_logs(id INTEGER PRIMARY KEY, player_id INT, league TEXT, season INT,
            game_no INT, game_date TEXT, team TEXT, stats TEXT);
        CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE prop_games(id INTEGER PRIMARY KEY, league TEXT, espn_event_id TEXT);
        CREATE TABLE props(id INTEGER PRIMARY KEY, game_id INT, player_id INT, market TEXT,
            side TEXT, line REAL);
    """)
    con.commit()
    con.close()

    def open_db():
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        return db

    world = {"path": path, "calls": {"model": 0, "espn": 0}, "reply": None, "network": [],
             "final": {"state": "post", "scores": {"ATL": 2, "CHI": 1}, "winner": "ATL", "home": "ATL"}}

    def model(system, user):
        world["calls"]["model"] += 1
        return world["reply"]

    def game_result(lg, game_id):
        world["calls"]["espn"] += 1
        return dict(world["final"])

    def no_standings(lg):
        raise RuntimeError("no standings in tests")

    def summary(lg, game_id):
        # The season type and year come from the same summary payload game_result reads in production.
        return {"header": {"season": {"type": 2, "year": 2026}}}

    def no_network(*args, **kwargs):
        world["network"].append(args)
        raise OSError("tests do not reach the network")

    records = {"ATL": {"name": "Atlanta United", "record": "10-5-3"},
               "CHI": {"name": "Chicago Fire", "record": "8-6-4"}}
    monkeypatch.setattr(core_stories, "_db", open_db)
    monkeypatch.setattr(core_stories, "_deepseek_chat", model)
    monkeypatch.setattr(core_stories, "_finished_scoreboard_records", lambda lg, game_id: records)
    monkeypatch.setattr(espn_client, "game_result", game_result)
    monkeypatch.setattr(espn_client, "team_strength_standings", no_standings)
    monkeypatch.setattr(espn_client, "summary", summary)
    monkeypatch.setattr(matchup_context, "context_lines", lambda *args, **kwargs: [])
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    return world


def _story_row(path, game_id="1001"):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    row = db.execute("SELECT story, deterministic FROM game_story WHERE league='mls' AND game_id=?",
                     (game_id,)).fetchone()
    db.close()
    return row


def test_with_no_model_a_finished_game_gets_its_result(world):
    story = core_stories.generate_game_story(**GAME)["story"]
    assert story == "Atlanta United beat Chicago Fire 2-1."
    row = _story_row(world["path"])
    assert row["story"] == story
    assert row["deterministic"] == 1
    assert [args[0].full_url for args in world["network"]] == []


def test_a_stored_fallback_recap_is_final_and_costs_nothing(world):
    core_stories.generate_game_story(**GAME)
    before = dict(world["calls"])
    again = core_stories.generate_game_story(**GAME)
    assert again["cached"] is True
    assert world["calls"] == before, "no model call and no ESPN fetch for a recap already written"


def test_a_model_recap_is_stored_as_a_model_recap(world):
    world["reply"] = "Atlanta United held on to beat Chicago Fire 2-1."
    story = core_stories.generate_game_story(**GAME)["story"]
    row = _story_row(world["path"])
    assert story == row["story"] == "Atlanta United held on to beat Chicago Fire 2-1."
    assert row["deterministic"] == 0


def test_a_preview_written_before_the_final_is_replaced_by_the_result(world):
    db = sqlite3.connect(world["path"])
    db.execute("CREATE TABLE IF NOT EXISTS game_story(league TEXT, game_id TEXT, story TEXT, "
               "generated_at TEXT, has_form INTEGER DEFAULT 0, PRIMARY KEY(league, game_id))")
    db.execute("INSERT INTO game_story(league, game_id, story, generated_at, has_form) "
               "VALUES ('mls', '1001', 'Chicago look to advance.', '2026-10-26 18:00:00', 1)")
    db.commit()
    db.close()
    story = core_stories.generate_game_story(**GAME)["story"]
    assert story == "Atlanta United beat Chicago Fire 2-1."
    assert _story_row(world["path"])["deterministic"] == 1


def test_a_winner_that_is_not_a_side_writes_nothing(world):
    world["final"]["winner"] = "NYC"
    assert core_stories.generate_game_story(**GAME)["story"] is None
    assert _story_row(world["path"]) is None
