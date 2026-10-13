"""Liga MX is a first-class soccer board and game-detail league."""
from unittest import mock

import ingest_scoreboards
from espn_client.scoreboard import _games_from_payload
from routers.games import game_detail


def _summary():
    return {
        "header": {"competitions": [{
            "status": {"type": {"state": "post", "completed": True}},
        }]},
        "boxscore": {"teams": [{
            "homeAway": "home",
            "statistics": [{"name": "possessionPct", "displayValue": "55%"}],
        }]},
        "gameInfo": {"venue": {"fullName": "Estadio Test"}},
        "keyEvents": [{
            "type": {"text": "Goal"}, "clock": {"displayValue": "12'"},
            "text": "Goal", "team": {"abbreviation": "AME"},
        }],
    }


def test_ligamx_is_in_the_recurring_board_ingest():
    assert "ligamx" in ingest_scoreboards.BOARD_LEAGUES


def test_ligamx_uses_the_soccer_scoreboard_shape():
    payload = {
        "events": [{
            "id": "401877001", "date": "2026-08-24T00:00Z",
            "competitions": [{
                "status": {"type": {
                    "state": "post", "completed": True,
                    "description": "Final", "shortDetail": "FT",
                }},
                "competitors": [
                    {"homeAway": "home", "score": "2", "winner": True,
                     "team": {"abbreviation": "AME", "displayName": "América"}},
                    {"homeAway": "away", "score": "1", "winner": False,
                     "team": {"abbreviation": "PUM", "displayName": "Pumas UNAM"}},
                ],
            }],
        }],
    }
    games = _games_from_payload("ligamx", "2026-08-24", payload)
    assert len(games) == 1
    assert games[0]["status"] == "FT"
    assert games[0]["winner_abbrev"] == "AME"
    assert games[0]["is_draw"] is False


def test_ligamx_game_tabs_use_soccer_transformers():
    with mock.patch.object(game_detail.espn, "summary", return_value=_summary()), \
         mock.patch.object(game_detail.espn, "lineups", return_value=[]), \
         mock.patch.object(
             game_detail.espn, "match_events",
             return_value={"key_events": _summary()["keyEvents"], "commentary": []},
         ):
        box = game_detail.get_game_boxscore("ligamx", "401877001")
        pbp = game_detail.get_game_playbyplay("ligamx", "401877001")
        info = game_detail.get_game_gameinfo("ligamx", "401877001")

    assert box["available"] is True
    assert box["teamStats"][0]["home"] == "55%"
    assert pbp["available"] is True
    assert pbp["events"][0]["type"] == "goal"
    assert info["available"] is True
    assert info["venue"] == "Estadio Test"
