"""`game_result` says which side is HOME, using the publisher's own flag.

It returned `scores` keyed by ESPN team ABBREVIATION and nothing else, so every
caller that wanted "what did the home team score" had to supply a key — and both
callers supplied a DISPLAY NAME:

    settlement.py:554   result["scores"].get(game["home"])       # "Athletics"
    routers/games.py:919 scores.get(context["home_team"], scores.get("home"))

`.get("Athletics")` into `{"ATH": 5}` cannot hit. It does not raise, it returns
None — so `prop_games.final_home`/`final_away` were written NULL on every game
that passed through the finality gate, and the game page's `final_score` came
back empty. Measured 2026-08-11: WC had 3 of 3 games linked and 0 finals; 13
games carried settled props with no recorded score. MLB's 605 finals came from
regrade_props, which fetches its own, not from this path.

ESPN publishes `competitor.homeAway` on the same object as the score. Reading it
removes the join instead of repairing it: there is no name to normalise, no
alias map, and no vocabulary to keep in sync (published-first §3, "the join key
itself" — a wrong key does not raise, it misses).
"""
import pytest

import espn_client


def _summary(home_abbr, home_score, away_abbr, away_score, state="post"):
    return {"header": {"competitions": [{
        # `completed` decides finality, not `state` — see test_finality_gate_completed.
        "status": {"type": {"state": state, "completed": state == "post",
                            "shortDetail": "Final"}, "period": 9,
                   "displayClock": "0:00"},
        "competitors": [
            {"homeAway": "home", "score": home_score,
             "team": {"abbreviation": home_abbr, "displayName": home_abbr}},
            {"homeAway": "away", "score": away_score,
             "team": {"abbreviation": away_abbr, "displayName": away_abbr}},
        ]}]}}


@pytest.fixture
def espn(monkeypatch):
    def use(doc):
        monkeypatch.setattr(espn_client, "summary", lambda lg, gid: doc)
    return use


def test_home_and_away_come_from_the_publishers_flag(espn):
    espn(_summary("ATH", "5", "TB", "3"))
    r = espn_client.game_result("mlb", "401816477")
    assert r["home"] == "ATH" and r["away"] == "TB"
    assert r["home_score"] == 5 and r["away_score"] == 3


def test_order_of_competitors_does_not_decide_home(espn):
    """ESPN does not promise home first. The flag decides, not the position."""
    doc = _summary("ATH", "5", "TB", "3")
    doc["header"]["competitions"][0]["competitors"].reverse()
    espn(doc)
    r = espn_client.game_result("mlb", "401816477")
    assert r["home"] == "ATH" and r["home_score"] == 5


def test_the_scores_dict_is_still_keyed_by_abbrev_for_existing_callers(espn):
    """_core.py reads .keys() off it; do not break that."""
    espn(_summary("ATH", "5", "TB", "3"))
    r = espn_client.game_result("mlb", "401816477")
    assert r["scores"] == {"ATH": 5, "TB": 3}


def test_a_display_name_lookup_would_have_missed(espn):
    """The bug, stated directly, so nobody reintroduces the name-keyed lookup."""
    espn(_summary("ATH", "5", "TB", "3"))
    r = espn_client.game_result("mlb", "401816477")
    assert r["scores"].get("Athletics") is None
    assert r["home_score"] == 5


def test_a_game_in_progress_still_reports_home_and_away(espn):
    espn(_summary("ATH", "2", "TB", "1", state="in"))
    r = espn_client.game_result("mlb", "401816477")
    assert r["state"] == "in" and r["home"] == "ATH"
    assert r["winner"] is None, "nothing is final until the publisher says so"


def test_soccer_also_reports_home_and_away(monkeypatch):
    doc = {"header": {"competitions": [{
        "status": {"type": {"state": "post", "completed": True, "shortDetail": "FT"}, "period": 2,
                   "displayClock": "90'"},
        "competitors": [
            {"homeAway": "home", "score": "1", "winner": False,
             "team": {"abbreviation": "LAFC"}},
            {"homeAway": "away", "score": "2", "winner": True,
             "team": {"abbreviation": "SEA"}},
        ]}]}}
    monkeypatch.setattr(espn_client, "summary", lambda lg, gid: doc)
    r = espn_client.game_result("mls", "1")
    assert r["home"] == "LAFC" and r["away"] == "SEA"
    assert r["home_score"] == 1 and r["away_score"] == 2
    assert r["winner"] == "SEA"
