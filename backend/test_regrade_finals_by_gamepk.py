"""A doubleheader's two halves have two different finals.

`regrade_props.finals_for(date)` built a dict keyed `(home_name, away_name)` for a
whole date. A doubleheader publishes two games with identical teams on one date, so
the dict kept whichever landed last and **both halves took the same final** — 4
groups in the dev DB. The same key also missed entirely across the UTC shift: a
22:15 ET first pitch belongs to the next calendar day in the schedule, so a game
that had been played read as "not final" and its results were purged.

The gamePk is the exact key, and settlement already resolves it by first pitch and
refuses anything not Final. Reading the score off the game we resolved makes the
two problems the same problem, already solved once.
"""
import pytest

import regrade_props
import settlement
# Patched on the SUBMODULE, which is where the function now lives. Before the
# package split `settlement._mlb_schedule` and `settlement.mlb_api._mlb_schedule`
# were the same object; they are two namespaces now, and rebinding the package
# alias leaves the caller inside `mlb_api` calling the real MLB Stats API. The
# instant-resolution tests already patch the submodule -- both files must aim at
# the same object or one of them is testing the network.
import settlement.mlb_api


ATL, SF = "Atlanta Braves", "San Francisco Giants"


def _sched(pk, iso, home_score, away_score, state="Final"):
    return {"dates": [{"games": [{
        "gamePk": pk, "gameDate": iso,
        "status": {"abstractGameState": state},
        "teams": {"home": {"team": {"name": ATL, "abbreviation": "ATL"}, "score": home_score},
                  "away": {"team": {"name": SF, "abbreviation": "SF"}, "score": away_score}},
    }]}]}


GAME_1 = _sched(824912, "2026-06-17T18:00:00Z", 2, 7)
GAME_2 = _sched(824913, "2026-06-17T23:15:00Z", 5, 7)


@pytest.fixture
def mlb(monkeypatch):
    """Both halves on one date, plus a per-gamePk score lookup."""
    day = {"dates": [{"games": GAME_1["dates"][0]["games"] + GAME_2["dates"][0]["games"]}]}
    monkeypatch.setattr(settlement.mlb_api, "_mlb_schedule",
                        lambda d: day if d == "2026-06-17" else {"dates": []})
    by_pk = {824912: (2, 7), 824913: (5, 7)}
    monkeypatch.setattr(settlement, "_fetch_mlb_final", lambda pk: by_pk.get(pk))


def _row(start_time):
    return {"id": 1, "date": "2026-06-17", "home": ATL, "away": SF, "start_time": start_time}


def test_each_half_of_a_doubleheader_gets_its_own_final(mlb):
    assert regrade_props.final_for(_row("2026-06-17T18:00:00+00:00")) == (2, 7)
    assert regrade_props.final_for(_row("2026-06-17T23:15:00+00:00")) == (5, 7)


def test_an_unresolvable_row_is_not_given_a_final(mlb):
    """No instant and two candidates: refuse rather than hand both the same score."""
    assert regrade_props.final_for(_row(None)) is None


def test_a_game_on_the_other_side_of_the_utc_shift_is_found(monkeypatch):
    """prop_games says 2026-08-11; the schedule files it under 2026-08-10."""
    played = _sched(825048, "2026-08-11T01:40:00Z", 9, 0)
    monkeypatch.setattr(settlement.mlb_api, "_mlb_schedule",
                        lambda d: played if d == "2026-08-10" else {"dates": []})
    monkeypatch.setattr(settlement, "_fetch_mlb_final", lambda pk: (9, 0) if pk == 825048 else None)
    assert regrade_props.final_for(
        {"date": "2026-08-11", "home": ATL, "away": SF,
         "start_time": "2026-08-11T01:40:00+00:00"}) == (9, 0)


def test_a_game_that_is_not_final_has_no_final(monkeypatch):
    preview = _sched(825046, "2026-08-12T01:40:00Z", 0, 0, state="Preview")
    monkeypatch.setattr(settlement.mlb_api, "_mlb_schedule",
                        lambda d: preview if d == "2026-08-12" else {"dates": []})
    monkeypatch.setattr(settlement, "_fetch_mlb_final", lambda pk: None)
    assert regrade_props.final_for(
        {"date": "2026-08-12", "home": ATL, "away": SF,
         "start_time": "2026-08-12T01:40:00+00:00"}) is None
