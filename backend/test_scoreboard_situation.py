"""The football situation ESPN already sends on the scoreboard reaches the game dict.

Fixtures are trimmed copies of real scoreboard events cached 2026-10-03 (NCAAF)."""
from espn_client.scoreboard import _normalize_team_events


def _event(state, situation, home=("153", "UNC"), away=("87", "ND")):
    return {
        "id": "401", "date": "2026-10-03T16:00Z", "season": {"type": 2, "slug": "regular-season"},
        "competitions": [{
            "status": {"period": 1, "displayClock": "0:40",
                       "type": {"state": state, "completed": state == "post", "description": "In Progress",
                                "shortDetail": "0:40 - 1st"}},
            "competitors": [
                {"id": home[0], "homeAway": "home", "score": "7", "team": {"abbreviation": home[1]}},
                {"id": away[0], "homeAway": "away", "score": "0", "team": {"abbreviation": away[1]}},
            ],
            "situation": situation,
        }],
    }


ND_AT_UNC = {
    "down": 1, "distance": 5, "yardLine": 37, "downDistanceText": "1st & 5 at UNC 37",
    "shortDownDistanceText": "1st & 5", "possessionText": "UNC 37", "possession": "87",
    "isRedZone": False, "homeTimeouts": 3, "awayTimeouts": 3,
    "lastPlay": {"text": "C.Carr pass incomplete ... NO PLAY", "type": {"text": "Penalty"},
                 "team": {"id": "87"}, "scoreValue": 0,
                 "drive": {"description": "5 plays, 30 yards, 3:19", "start": {"text": "ND 23"}},
                 "probability": {"homeWinPercentage": 0.0464, "awayWinPercentage": 0.9536,
                                 "tiePercentage": 0.0}},
}


def test_live_situation_is_carried_with_sides_and_spot():
    s = _normalize_team_events([_event("in", ND_AT_UNC)])[0]["situation"]
    assert (s["down"], s["distance"], s["text"], s["ball_on"]) == (1, 5, "1st & 5 at UNC 37", "UNC 37")
    assert s["possession"] == "away" and s["last_play"]["team"] == "away"
    # yardLine counts from the home goal line; the away end zone is drawn on the left.
    assert (s["yard_line_from_home_goal"], s["field_pos_from_away_goal"]) == (37, 63)
    assert (s["home_timeouts"], s["away_timeouts"]) == (3, 3)
    assert s["drive"] == {"description": "5 plays, 30 yards, 3:19", "start": "ND 23"}
    assert s["win_probability"]["source"] == "espn" and s["win_probability"]["away"] == 0.9536


def test_home_side_spot_and_goal_to_go():
    sit = dict(ND_AT_UNC, down=1, distance=1, yardLine=99, downDistanceText="1st & Goal at MTSU 1",
               possessionText="MTSU 1", possession="2305", isRedZone=True)
    s = _normalize_team_events([_event("in", sit, home=("2305", "KU"), away=("2393", "MTSU"))])[0]["situation"]
    assert s["possession"] == "home" and s["field_pos_from_away_goal"] == 1
    assert s["goal_to_go"] is True and s["red_zone"] is True


def test_no_down_between_plays_means_no_spot():
    sit = {"down": -1, "distance": 0, "yardLine": 0, "isRedZone": True, "homeTimeouts": 3, "awayTimeouts": 2,
           "lastPlay": {"text": "K.Russell rush right for 17 yards TOUCHDOWN", "type": {"text": "Rushing Touchdown"},
                        "team": {"id": "87"}, "scoreValue": 6}}
    s = _normalize_team_events([_event("in", sit)])[0]["situation"]
    assert s["down"] is None and s["distance"] is None
    assert s["yard_line_from_home_goal"] is None and s["field_pos_from_away_goal"] is None
    assert s["last_play"]["type"] == "Rushing Touchdown" and s["last_play"]["score_value"] == 6


def test_only_live_games_carry_a_situation():
    assert "situation" not in _normalize_team_events([_event("post", ND_AT_UNC)])[0]
    assert "situation" not in _normalize_team_events([_event("pre", ND_AT_UNC)])[0]
    assert "situation" not in _normalize_team_events([_event("in", {})])[0]
