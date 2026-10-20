"""Focused tests for FBS matchup identity and true kickoff propagation."""
import datetime as dt
from unittest.mock import patch

import pandas as pd
import pytest

import fbs_model_runner as runner
import fbs_model_service as service


def _frame():
    return pd.DataFrame([
        dict(game_id="old", season=2026, fbs_game=True,
             home_team_id="1", away_team_id="2",
             home_conference="SEC", away_conference="Big 12"),
        dict(game_id="older", season=2025, fbs_game=True,
             home_team_id="1", away_team_id="2",
             home_conference="Big 12", away_conference="SEC"),
    ])


def test_current_season_conference_does_not_inherit_prior_season():
    assert runner._current_fbs_team_conferences(_frame(), 2026) == {
        "1": "SEC", "2": "Big 12"
    }


def test_conflicting_current_season_membership_fails_closed():
    frame = _frame()
    frame.loc[len(frame)] = dict(game_id="dup", season=2026, fbs_game=True,
                                 home_team_id="1", away_team_id="2",
                                 home_conference="ACC", away_conference="Big 12")
    with pytest.raises(service.FBSModelError, match="conflicting"):
        runner._current_fbs_team_conferences(frame, 2026)


def test_slate_identity_and_precise_kickoff_preserved():
    kickoff = pd.Timestamp("2026-10-24T19:30:00Z")
    slate = pd.DataFrame([{
        "game_id": "new-game", "home_team_id": "1", "away_team_id": "2",
        "home_team": "Texas", "away_team": "Baylor",
        "neutral_site": True, "kickoff_utc": kickoff, "week": 9,
    }])
    events = pd.DataFrame([{
        "game_id": "old", "fbs_participant": True, "evaluation_population": True,
        "season": 2026, "home_conference": "WRONG",
        "away_conference": "WRONG", "kickoff_utc": dt.datetime(2026, 10, 17,
                                                               tzinfo=dt.timezone.utc),
    }])
    captured = {}

    def fake_predict(combined, first_evaluation_season):
        row = combined.loc[combined.game_id == "new-game"].iloc[0]
        captured.update(row.to_dict())
        return pd.DataFrame([{"game_id": "new-game", "elo_home_prob": .61}])

    with patch.object(runner.base, "load_events",
                      return_value=(events, None, None, None)), \
         patch.object(runner.base, "make_predictions", side_effect=fake_predict):
        out = runner.g2_for_slate(_frame(), slate)

    assert captured["home_conference"] == "SEC"
    assert captured["away_conference"] == "Big 12"
    assert captured["neutral_site"] is True
    assert captured["kickoff_utc"] == kickoff.to_pydatetime()
    assert out.iloc[0].p_g2 == .61


def test_non_fbs_or_unverified_team_excluded():
    slate = pd.DataFrame([{
        "game_id": "fcs", "home_team_id": "1", "away_team_id": "999",
        "home_team": "Texas", "away_team": "Unknown",
        "neutral_site": False,
        "kickoff_utc": pd.Timestamp("2026-10-24T19:30:00Z"),
    }])
    with patch.object(runner.base, "load_events",
                      return_value=(pd.DataFrame(), None, None, None)):
        with pytest.raises(service.FBSModelError, match="no verified"):
            runner.g2_for_slate(_frame(), slate)
