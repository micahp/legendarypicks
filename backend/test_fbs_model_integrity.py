"""Focused tests for FBS matchup identity, true kickoffs, T-90 locks and the parity gate."""
import datetime as dt
import json
import sqlite3
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

import fbs_model_runner as runner
import fbs_model_service as service
import fbs_model_store as store

NOW = dt.datetime(2026, 10, 20, 17, 0, tzinfo=dt.timezone.utc)
# Real ESPN kickoff for event 401871055 (scoreboard, 2026-10-20). Not midnight.
KICKOFF = dt.datetime(2026, 10, 20, 23, 0, tzinfo=dt.timezone.utc)
REAL_EVENT = {
    "id": "401871055", "date": "2026-10-20T23:00Z", "week": {"number": 8},
    "competitions": [{
        "neutralSite": False, "status": {"type": {"completed": False}},
        "competitors": [
            {"homeAway": "home", "score": "0", "team": {
                "id": "2229", "displayName": "Florida International Panthers",
                "shortDisplayName": "FIU"}},
            {"homeAway": "away", "score": "0", "team": {
                "id": "2393", "displayName": "Middle Tennessee Blue Raiders",
                "shortDisplayName": "Middle Tennessee"}},
        ],
    }],
}


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


# ----------------------------------------------------------------------------- store: locks

def _row(game_id="401871055", model="g2h", p_home=0.6, kickoff=KICKOFF):
    return {"game_id": game_id, "model": model, "season": 2026,
            "kickoff_utc": kickoff.isoformat(), "home_team": "Florida International Panthers",
            "away_team": "Middle Tennessee Blue Raiders", "home_team_id": "2229",
            "away_team_id": "2393", "model_version": "fbs-%s-20261017" % model,
            "p_home": p_home, "fitted_through": "2026-10-17"}


@pytest.fixture
def con(tmp_path):
    connection = store.open_db(str(tmp_path / "fbs-model.sqlite3"))
    yield connection
    connection.close()


def test_forecast_is_not_locked_before_the_t90_window(con):
    report = store.lock_forecasts(con, [_row()], now=KICKOFF - dt.timedelta(hours=10))
    assert report["not_due"] == 1
    assert con.execute("SELECT COUNT(*) FROM fbs_forecasts").fetchone()[0] == 0


def test_lock_inside_window_is_labelled_and_immutable(con):
    inside = KICKOFF - dt.timedelta(minutes=45)
    store.lock_forecasts(con, [_row()], now=inside)
    row = con.execute("SELECT * FROM fbs_forecasts").fetchone()
    assert row["lock_protocol"] == store.LOCK_PROTOCOL
    assert row["locked_at_utc"] == inside.isoformat()
    assert row["late"] == 0
    with pytest.raises(sqlite3.Error):
        con.execute("UPDATE fbs_forecasts SET p_home = 0.9")
    with pytest.raises(sqlite3.Error):
        con.execute("DELETE FROM fbs_forecasts")


def test_nothing_locks_after_kickoff_and_the_missed_window_is_recorded_once(con):
    store.upsert_previews(con, [_row()], now=KICKOFF - dt.timedelta(hours=10))
    after = KICKOFF + dt.timedelta(minutes=5)
    report = store.lock_forecasts(con, [_row()], now=after)
    assert report["after_kickoff"] == 1
    assert con.execute("SELECT COUNT(*) FROM fbs_forecasts").fetchone()[0] == 0
    assert store.record_missed_windows(con, now=after) == 1
    assert store.record_missed_windows(con, now=after + dt.timedelta(minutes=1)) == 0


def test_previews_are_replaced_and_never_lock(con):
    store.upsert_previews(con, [_row(p_home=0.55)], now=KICKOFF - dt.timedelta(hours=10))
    store.upsert_previews(con, [_row(p_home=0.61)], now=KICKOFF - dt.timedelta(hours=9))
    assert con.execute("SELECT p_home FROM fbs_previews").fetchone()[0] == 0.61
    assert con.execute("SELECT COUNT(*) FROM fbs_forecasts").fetchone()[0] == 0
    # Inside the lock window a preview is still written, so an untaken lock stays visible.
    assert store.upsert_previews(con, [_row()], now=KICKOFF - dt.timedelta(hours=1)) == 1
    assert con.execute("SELECT COUNT(*) FROM fbs_forecasts").fetchone()[0] == 0
    # After kickoff nothing is written.
    assert store.upsert_previews(con, [_row()], now=KICKOFF) == 0


def test_export_reports_preview_status_and_no_official_record(con):
    store.upsert_previews(con, [_row(model=m) for m in store.MODEL_IDS],
                          now=KICKOFF - dt.timedelta(hours=10))
    payload = store.export_payload(con, 2026)
    game = payload["games"][0]
    assert game["status"] == "preview"
    assert game["models"]["g2h"]["previewed_at_utc"]
    assert payload["records"]["g2h"]["forecasts"] == 0


def test_export_reports_a_taken_lock_as_locked_with_its_freeze_time(con):
    inside = KICKOFF - dt.timedelta(minutes=45)
    store.lock_forecasts(con, [_row(model=m) for m in store.MODEL_IDS], now=inside)
    payload = store.export_payload(con, 2026)
    game = payload["games"][0]
    assert game["status"] == "locked"
    assert game["locked_at_utc"] == inside.isoformat()
    assert game["models"]["g2h"]["locked_at_utc"] == inside.isoformat()
    assert payload["records"]["g2h"]["forecasts"] == 1  # one official g2h forecast, not yet graded
    assert payload["records"]["g2h"]["graded"] == 0


def test_legacy_rows_are_counted_in_the_record_once_graded(con):
    # Shape of a row written before the protocol: midnight kickoff, no lock time.
    con.execute("INSERT INTO fbs_forecasts(game_id,model,season,kickoff_utc,home_team,away_team,"
                "model_version,p_home,created_at_utc,locked_at_utc,late,lock_protocol) "
                "VALUES('1','g2h',2026,'2026-10-20T00:00:00+00:00','A','B','fbs-g2h-x',0.7,"
                "'2026-10-20T21:26:35+00:00',NULL,1,'legacy')")
    assert store.grade_forecasts(con, {"1": {"home_score": 20, "away_score": 10}}) == 1
    payload = store.export_payload(con, 2026)
    assert payload["records"]["g2h"]["forecasts"] == 1
    assert payload["records"]["g2h"]["graded"] == 1
    assert payload["records"]["g2h"]["accuracy"] == 1.0


def test_scoreboard_finals_grade_stored_forecasts(con, tmp_path):
    live = str(tmp_path / "live.db")
    raw = sqlite3.connect(live)
    raw.execute("CREATE TABLE scoreboard_snapshots(league TEXT, game_id TEXT, state TEXT, payload TEXT)")
    done = {"completed": True, "home": {"score": 20.0}, "away": {"score": 10.0}}
    live_game = {"completed": False, "home": {"score": 3.0}, "away": {"score": 0.0}}
    raw.execute("INSERT INTO scoreboard_snapshots VALUES('ncaaf','1','post',?)", (json.dumps(done),))
    raw.execute("INSERT INTO scoreboard_snapshots VALUES('ncaaf','2','post',?)", (json.dumps(live_game),))
    raw.execute("INSERT INTO scoreboard_snapshots VALUES('nfl','3','post',?)", (json.dumps(done),))
    raw.commit(); raw.close()
    assert runner.scoreboard_results(live) == {"1": {"home_score": 20, "away_score": 10}}


def test_old_database_is_migrated_and_its_rows_are_labelled_legacy(tmp_path):
    path = str(tmp_path / "old.sqlite3")
    raw = sqlite3.connect(path)
    raw.executescript(
        "CREATE TABLE fbs_forecasts (game_id TEXT NOT NULL, model TEXT NOT NULL,"
        " season INTEGER NOT NULL, kickoff_utc TEXT NOT NULL, home_team TEXT NOT NULL,"
        " away_team TEXT NOT NULL, home_team_id TEXT, away_team_id TEXT,"
        " model_version TEXT NOT NULL, p_home REAL NOT NULL, fair_home INTEGER,"
        " fair_away INTEGER, fitted_through TEXT, created_at_utc TEXT NOT NULL,"
        " locked_at_utc TEXT, late INTEGER NOT NULL DEFAULT 0, result INTEGER,"
        " home_score INTEGER, away_score INTEGER, graded_at_utc TEXT,"
        " PRIMARY KEY (game_id, model));")
    raw.execute("INSERT INTO fbs_forecasts(game_id,model,season,kickoff_utc,home_team,away_team,"
                "model_version,p_home,created_at_utc,locked_at_utc,late) "
                "VALUES('1','g2h',2026,'2026-10-20T00:00:00+00:00','A','B','v',0.7,'x','x',0)")
    raw.commit()
    raw.close()
    con = store.open_db(path)
    try:
        assert con.execute("SELECT lock_protocol FROM fbs_forecasts").fetchone()[0] == store.LEGACY_PROTOCOL
        with pytest.raises(sqlite3.Error):
            con.execute("UPDATE fbs_forecasts SET p_home = 0.1")
    finally:
        con.close()


# ------------------------------------------------------------- runner: parity and fetch

def test_locks_require_a_certificate_for_the_current_code_and_ledger(tmp_path, monkeypatch):
    db = str(tmp_path / "fbs-model.sqlite3")
    ledger = tmp_path / "ledger.csv"
    ledger.write_text("game_id,season\n1,2023\n")
    monkeypatch.setattr(runner, "PARITY_LEDGER", str(ledger))
    certified, reason = runner.parity_certified(db)
    assert not certified and "no parity certificate" in reason

    passing = {"ok": True, "games": 2397, "ledger_games": 2397, "models": {}}
    runner.write_certificate(passing, db, NOW)
    assert runner.parity_certified(db)[0] is True

    ledger.write_text("changed\n")
    assert runner.parity_certified(db)[0] is False
    ledger.write_text("game_id,season\n1,2023\n")

    runner.write_certificate({"ok": False, "models": {}}, db, NOW)
    assert runner.parity_certified(db)[0] is False

    runner.write_certificate(passing, db, NOW)
    monkeypatch.setattr(runner, "code_fingerprint", lambda: "different-code")
    certified, reason = runner.parity_certified(db)
    assert not certified and "different code" in reason


class _Response:
    def __init__(self, body):
        self._body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def test_slate_keeps_the_real_espn_kickoff(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda url, timeout: _Response({"events": [REAL_EVENT]}))
    slate = runner.fetch_slate(days=0, now=NOW)
    assert slate.iloc[0].kickoff_utc == pd.Timestamp("2026-10-20T23:00Z")
    assert slate.iloc[0].week == 8


def test_unreachable_scoreboard_date_stops_the_slate(monkeypatch):
    def refuse(url, timeout):
        raise OSError("connection reset")

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    with pytest.raises(service.FBSModelError, match="slate incomplete"):
        runner.fetch_slate(days=1, now=NOW)


class _Hierarchy:
    conf_index = {"SEC": 0}
    m = [0.0]
    ts_index = {(2026, "1"): 0, (2026, "2"): 1}
    u = [0.1, -0.1]


def test_games_used_counts_completed_games_only():
    frame = pd.DataFrame([
        dict(game_id="g1", season=2026, utc_date=pd.Timestamp("2026-08-29"),
             home_team_id="1", away_team_id="2", home_team="Texas", away_team="Baylor",
             home_conference="SEC", away_conference="Big 12", y=1.0),
        dict(game_id="g2", season=2026, utc_date=pd.Timestamp("2026-10-24"),
             home_team_id="1", away_team_id="2", home_team="Texas", away_team="Baylor",
             home_conference="SEC", away_conference="Big 12", y=np.nan),
    ])
    by_id = {r["team_id"]: r for r in runner.team_ratings({"g2h": _Hierarchy()}, frame, 2026)}
    assert by_id["1"]["games_used"] == 1
    assert by_id["1"]["team"] == "Texas"
    assert by_id["1"]["conference"] == "SEC"
