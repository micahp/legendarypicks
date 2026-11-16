"""Focused tests for FBS matchup identity, true kickoffs, T-90 locks and the parity gate."""
import datetime as dt
import json
import os
import sqlite3
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

import fbs_model_runner as runner
import fbs_model_service as service
import fbs_model_store as store


def open_scratch(path):
    """A scratch database at the current schema: created new if absent, otherwise opened. Never migrated."""
    if not os.path.exists(path):
        store.initialize_new_db(path).close()
    return store.open_db(path)

NOW = dt.datetime(2026, 10, 20, 17, 0, tzinfo=dt.timezone.utc)
# Real ESPN kickoff for event 401871055 (scoreboard, 2026-10-20). Not midnight.
KICKOFF = dt.datetime(2026, 10, 20, 23, 0, tzinfo=dt.timezone.utc)
REAL_EVENT = {
    "id": "401871055", "date": "2026-10-20T23:00Z", "week": {"number": 8},
    "season": {"year": 2026, "type": 2},
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
        "neutral_site": True, "kickoff_utc": kickoff, "week": 9, "season": 2026, "season_type": 2,
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
        "neutral_site": False, "season": 2026, "season_type": 2,
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
    connection = open_scratch(str(tmp_path / "fbs-model.sqlite3"))
    yield connection
    connection.close()


def _scheduled(con, game_id="401871055", kickoff=None, observed=None, lifecycle="scheduled"):
    """Record a fixture revision and a live status, as the forecast step does before any lock."""
    kickoff = kickoff or KICKOFF
    observed = observed or (kickoff - dt.timedelta(hours=10))
    rec = dict(game_id=game_id, season=2026, kickoff_utc=kickoff.isoformat(),
               home_team="Florida International Panthers", away_team="Middle Tennessee Blue Raiders",
               home_team_id="2229", away_team_id="2393", neutral_site=False)
    obs = store.observe_fixture(con, rec, observed, "test")
    store.set_game_status(con, game_id, 2026, obs["revision"], lifecycle, "STATUS_SCHEDULED",
                          observed.isoformat(), "test", "pending")
    return obs


def project(con, now, models=None, kickoff=None, p_home=0.6, game_id="401871055"):
    """Store the latest pregame projection for each model, as a run does before the cutoff."""
    rows = [_row(game_id=game_id, model=m, kickoff=kickoff or KICKOFF, p_home=p_home)
            for m in (models or store.MODEL_IDS)]
    return store.upsert_projections(con, rows, now=now)


def test_a_projection_is_stored_before_its_cutoff_and_each_run_replaces_it(con):
    before = KICKOFF - dt.timedelta(hours=10)
    assert project(con, before, p_home=0.55) == 3
    assert project(con, before + dt.timedelta(hours=1), p_home=0.61) == 3
    row = con.execute("SELECT p_home, projected_at_utc FROM fbs_projections WHERE model = 'g2h'").fetchone()
    assert row[0] == 0.61 and row[1] == (before + dt.timedelta(hours=1)).isoformat()
    cutoff = KICKOFF - store.LOCK_LEAD
    assert project(con, cutoff, p_home=0.9) == 0                       # at the cutoff: nothing new is stored
    assert project(con, KICKOFF - dt.timedelta(minutes=30), p_home=0.9) == 0
    assert con.execute("SELECT p_home FROM fbs_projections WHERE model = 'g2h'").fetchone()[0] == 0.61


def test_nothing_is_frozen_before_the_cutoff(con):
    _scheduled(con, observed=KICKOFF - dt.timedelta(hours=10))
    project(con, KICKOFF - dt.timedelta(hours=10))
    report = store.freeze_projections(con, now=KICKOFF - dt.timedelta(hours=2))
    assert report["not_due"] == 3 and report["frozen"] == 0
    assert con.execute("SELECT COUNT(*) FROM fbs_forecasts").fetchone()[0] == 0


def test_a_projection_freezes_exactly_at_the_cutoff_and_not_a_second_before(con):
    _scheduled(con, observed=KICKOFF - dt.timedelta(hours=10))
    project(con, KICKOFF - dt.timedelta(hours=10))
    cutoff = KICKOFF - store.LOCK_LEAD
    assert store.freeze_projections(con, now=cutoff - dt.timedelta(seconds=1))["not_due"] == 3
    assert store.freeze_projections(con, now=cutoff)["frozen"] == 3


def test_a_frozen_projection_is_the_stored_one_with_its_timestamps_and_never_changes(con):
    before = KICKOFF - dt.timedelta(hours=10)
    _scheduled(con, observed=before)
    project(con, before, p_home=0.61)
    cutoff = KICKOFF - store.LOCK_LEAD
    frozen_at = cutoff + dt.timedelta(minutes=1)
    assert store.freeze_projections(con, now=frozen_at)["frozen"] == 3
    row = con.execute("SELECT * FROM fbs_forecasts WHERE model = 'g2h'").fetchone()
    assert row["p_home"] == 0.61                                       # copied from the stored projection
    assert row["projected_at_utc"] == before.isoformat()
    assert row["cutoff_utc"] == cutoff.isoformat()
    assert row["locked_at_utc"] == frozen_at.isoformat()
    assert row["lock_protocol"] == store.LOCK_PROTOCOL and row["late"] == 0
    assert store.freeze_projections(con, now=frozen_at + dt.timedelta(minutes=1))["already_frozen"] == 3
    for statement in ("UPDATE fbs_forecasts SET p_home = 0.9", "UPDATE fbs_forecasts SET cutoff_utc = 'x'",
                      "DELETE FROM fbs_forecasts"):
        with pytest.raises(sqlite3.Error):
            con.execute(statement)


def test_a_later_run_after_the_freeze_cannot_change_a_frozen_projection(con):
    before = KICKOFF - dt.timedelta(hours=10)
    _scheduled(con, observed=before)
    project(con, before, p_home=0.61)
    store.freeze_projections(con, now=KICKOFF - store.LOCK_LEAD)
    assert project(con, KICKOFF - dt.timedelta(minutes=60), p_home=0.9) == 0
    assert con.execute("SELECT p_home FROM fbs_forecasts WHERE model = 'g2h'").fetchone()[0] == 0.61


def test_nothing_freezes_after_kickoff_and_the_missed_cutoff_is_recorded_once(con):
    _scheduled(con, observed=KICKOFF - dt.timedelta(hours=10))
    project(con, KICKOFF - dt.timedelta(hours=10))
    after = KICKOFF + dt.timedelta(minutes=5)
    assert store.freeze_projections(con, now=after)["after_kickoff"] == 3
    assert con.execute("SELECT COUNT(*) FROM fbs_forecasts").fetchone()[0] == 0
    assert store.record_missed_windows(con, now=after)["missed_t90_window"] == 3
    assert store.record_missed_windows(con, now=after + dt.timedelta(minutes=1))["missed_t90_window"] == 0


def test_a_game_whose_pregame_status_is_unverified_at_the_cutoff_is_not_frozen(con):
    before = KICKOFF - dt.timedelta(hours=10)
    _scheduled(con, observed=before, lifecycle="unknown")
    project(con, before)
    report = store.freeze_projections(con, now=KICKOFF - store.LOCK_LEAD + dt.timedelta(minutes=1))
    assert report["blocked_status"] == 3 and report["frozen"] == 0
    assert store.record_missed_windows(con, now=KICKOFF + dt.timedelta(minutes=1))["blocked_unverified_at_cutoff"] == 3


def test_a_projection_card_carries_no_status_label_and_no_frozen_record(con):
    project(con, KICKOFF - dt.timedelta(hours=10))
    payload = store.export_payload(con, 2026)
    game = payload["games"][0]
    assert "status" not in game and "locked_at_utc" not in game
    assert game["models"]["g2h"]["p_home"] == 0.6 and game["models"]["g2h"]["frozen_at_utc"] is None
    assert game["result"] is None
    assert payload["records"]["g2h"]["frozen"] == 0 and payload["records"]["g2h"]["graded"] == 0
    assert payload["state"] == "available" and payload["diagnostics"]["frozen_rows"] == 0


def test_a_frozen_projection_keeps_its_freeze_time_and_is_graded_once_from_a_verified_final(con):
    _scheduled(con, observed=KICKOFF - dt.timedelta(hours=10))
    project(con, KICKOFF - dt.timedelta(hours=10), p_home=0.7)
    cutoff = KICKOFF - store.LOCK_LEAD
    store.freeze_projections(con, now=cutoff)
    with pytest.raises(ValueError, match="unverified"):
        store.grade_forecasts(con, {"401871055": {"home_score": 24, "away_score": 20}}, now=KICKOFF + dt.timedelta(hours=3))
    store.grade_forecasts(con, {"401871055": {"home_score": 24, "away_score": 20, "verified": True}},
                          now=KICKOFF + dt.timedelta(hours=3))
    with pytest.raises(sqlite3.Error):
        con.execute("UPDATE fbs_forecasts SET result = 0")              # a result is written once
    payload = store.export_payload(con, 2026)
    game = payload["games"][0]
    assert game["result"] == {"home_score": 24, "away_score": 20, "home_win": True}
    assert game["models"]["g2h"]["frozen_at_utc"] == cutoff.isoformat()
    record = payload["records"]["g2h"]
    assert record["frozen"] == 1 and record["graded"] == 1 and record["accuracy"] == 1.0
    history = record["history"][0]
    assert history["graded"] == 1 and history["home_win"] is True
    assert history["home_team"] == "Florida International Panthers"
    assert history["away_team"] == "Middle Tennessee Blue Raiders"
    assert (history["home_score"], history["away_score"]) == (24, 20)


def test_legacy_rows_are_graded_and_counted_in_the_record_but_not_shown_as_cards(con):
    # Shape of a row written before the protocol: midnight kickoff, labelled legacy.
    con.execute("INSERT INTO fbs_forecasts(game_id,model,season,kickoff_utc,home_team,away_team,"
                "model_version,p_home,created_at_utc,locked_at_utc,late,lock_protocol) "
                "VALUES('1','g2h',2026,'2026-10-20T00:00:00+00:00','A','B','fbs-g2h-x',0.7,"
                "'2026-10-20T21:26:35+00:00',NULL,1,'legacy')")
    assert store.export_payload(con, 2026)["games"] == []
    assert store.grade_forecasts(con, {"1": {"home_score": 20, "away_score": 10, "verified": True}}, now=NOW) == 1
    payload = store.export_payload(con, 2026)
    record = payload["records"]["g2h"]
    assert record["frozen"] == 1 and record["graded"] == 1 and record["accuracy"] == 1.0
    assert [h["game_id"] for h in record["history"]] == ["1"]
    assert payload["diagnostics"]["legacy_rows"] == 1


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
    store.migrate(path, str(tmp_path / "backups"))
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


def test_c2_forecast_path_reproduces_research_walk_forward_block():
    # The forecasting estimator must be the adopted research C2 estimator, block for block.
    from fbs_phase3_increment import walk_forward
    rng = np.random.default_rng(20261020)
    n = 480
    frame = pd.DataFrame({
        "game_id": [str(i) for i in range(n)], "season": 2026,
        "utc_date": pd.Timestamp("2026-01-01") + pd.to_timedelta(np.arange(n) // 8, unit="D"),
    })
    for col in service.FEATURES_C:
        frame[col] = rng.normal(size=n)
    frame["p_g2"] = rng.uniform(0.3, 0.7, n)
    signal = 0.8 * frame["points_per_drive_diff"] + rng.normal(size=n)
    frame["y"] = (rng.uniform(size=n) < 1 / (1 + np.exp(-signal))).astype(float)
    wf = walk_forward(frame.copy(), service.FEATURES_C).set_index("game_id")
    fitted = wf[wf["n_train"] >= service.MIN_TRAIN_GAMES]
    block = fitted["block"].iloc[0]
    cutoff = wf.loc[wf["block"] == block, "utc_date"].min()
    train = frame[frame["utc_date"] < cutoff].dropna(subset=["p_g2", "y"] + service.FEATURES_C)
    rows = frame[frame["game_id"].isin(wf.index[wf["block"] == block])]
    p = service.predict_c2(service.fit_c2(train), rows)
    np.testing.assert_allclose(p, wf.loc[rows["game_id"], "p_b2"].to_numpy(), rtol=0, atol=1e-9)


# ------------------------------------------------------- cfbfastR coverage: identity and eligibility

def _sched(rows):
    frame = pd.DataFrame(rows)
    frame["start_date_utc"] = pd.to_datetime(frame["start_date"], utc=True)
    frame["completed"] = frame["completed"].astype(bool)
    frame["game_id"] = frame["game_id"].astype(str)
    return frame


def _pbp(rows):
    frame = pd.DataFrame(rows)
    frame["start_date_utc"] = pd.to_datetime(frame["start_date"], utc=True)
    frame["game_id"] = frame["game_id"].astype(str)
    return frame


def test_coverage_statuses_follow_source_rows_and_identity():
    import fbs_cfbfastr_coverage as cov
    schedule = _sched([
        dict(game_id="1", start_date="2025-09-06T16:00:00Z", home_team="Texas", away_team="Baylor", completed=True),
        dict(game_id="2", start_date="2025-09-06T16:00:00Z", home_team="Ohio", away_team="Akron", completed=True),
        dict(game_id="3", start_date="2025-09-06T16:00:00Z", home_team="Iowa", away_team="Kansas", completed=True),
        dict(game_id="4", start_date="2025-09-06T16:00:00Z", home_team="Duke", away_team="Vermont", completed=True),
        dict(game_id="5", start_date="2025-09-13T16:00:00Z", home_team="Utah", away_team="Oregon", completed=False),
        dict(game_id="6", start_date="2025-09-13T16:00:00Z", home_team="Ohio State", away_team="Penn State", completed=True),
    ])
    pbp = _pbp([
        dict(game_id="1", start_date="2025-09-06T16:00:00Z", pos_team="Texas", home_team="Texas", away_team="Baylor"),
        dict(game_id="1", start_date="2025-09-06T16:00:00Z", pos_team="Baylor", home_team="Texas", away_team="Baylor"),
        dict(game_id="2", start_date=None, pos_team="Ohio", home_team="Ohio", away_team="Akron"),
        dict(game_id="2", start_date=None, pos_team="Akron", home_team="Ohio", away_team="Akron"),
        dict(game_id="3", start_date="2025-09-06T16:00:00Z", pos_team="Iowa", home_team="Iowa", away_team="Iowa State"),
        # Game 6 has play rows although the schedule snapshot predates its result: source rows win.
        dict(game_id="6", start_date="2025-09-13T16:00:00Z", pos_team="Ohio State", home_team="Ohio State", away_team="Penn State"),
        dict(game_id="6", start_date="2025-09-13T16:00:00Z", pos_team="Penn State", home_team="Ohio State", away_team="Penn State"),
        dict(game_id="99", start_date="2025-09-06T16:00:00Z", pos_team="Nobody", home_team="A", away_team="B"),
    ])
    rows = {r["game_id"]: r for r in cov.coverage_rows(2025, schedule, pbp, "abc")}
    assert rows["1"]["coverage_status"] == "has_plays" and rows["1"]["identity_check"] == "teams_and_date"
    assert rows["2"]["coverage_status"] == "has_plays" and rows["2"]["identity_check"] == "teams_only_source_date_missing"
    assert rows["3"]["coverage_status"] == "unknown_source_or_identity" and rows["3"]["identity_check"] == "failed_teams"
    assert rows["4"]["coverage_status"] == "no_plays_in_complete_snapshot"
    assert rows["5"]["coverage_status"] == "not_completed"
    assert rows["6"]["coverage_status"] == "has_plays"
    assert rows["99"]["coverage_status"] == "unknown_source_or_identity"
    assert rows["99"]["identity_check"] == "orphan_play_by_play_id"


def _coverage(rows):
    return pd.DataFrame(rows, columns=["season", "game_id", "coverage_status"])


def test_completed_games_without_plays_are_the_only_exclusions():
    frame = pd.DataFrame({"season": [2025, 2025, 2025, 2026], "game_id": ["a", "b", "c", "d"],
                          "y": [1.0, 0.0, 1.0, np.nan], "home_team": ["H"] * 4, "away_team": ["A"] * 4})
    table = _coverage([(2025, "a", "has_plays"), (2025, "b", "no_plays_in_complete_snapshot"),
                       (2025, "c", "has_plays"), (2026, "d", "not_completed")])
    kept, excluded = service.apply_pbp_eligibility(frame, table)
    assert kept["game_id"].tolist() == ["a", "c", "d"]
    assert excluded["game_id"].tolist() == ["b"]


def test_upcoming_game_without_any_coverage_row_is_kept():
    frame = pd.DataFrame({"season": [2026], "game_id": ["upcoming"], "y": [np.nan],
                          "home_team": ["H"], "away_team": ["A"]})
    kept, excluded = service.apply_pbp_eligibility(frame, _coverage([]))
    assert kept["game_id"].tolist() == ["upcoming"] and len(excluded) == 0


@pytest.mark.parametrize("status", ["unknown_source_or_identity", None])
def test_completed_game_without_verified_coverage_halts(status):
    frame = pd.DataFrame({"season": [2025], "game_id": ["x"], "y": [1.0], "home_team": ["H"], "away_team": ["A"]})
    table = _coverage([] if status is None else [(2025, "x", status)])
    with pytest.raises(service.FBSModelError, match="lack verified cfbfastR coverage"):
        service.apply_pbp_eligibility(frame, table)


def test_coverage_loader_rejects_a_table_that_does_not_match_its_manifest(tmp_path):
    import json
    (tmp_path / "table.csv").write_text("season,game_id,coverage_status\n2025,a,has_plays\n")
    (tmp_path / service.COVERAGE_MANIFEST).write_text(json.dumps({"csv": "table.csv", "csv_sha256": "0" * 64}))
    with pytest.raises(service.FBSModelError, match="does not match its manifest"):
        service.load_coverage(str(tmp_path))


def test_certificate_is_bound_to_the_coverage_manifest(tmp_path, monkeypatch):
    coverage_dir = tmp_path / "cov"
    coverage_dir.mkdir()
    (coverage_dir / service.COVERAGE_MANIFEST).write_text('{"csv": "t.csv", "csv_sha256": "x"}')
    monkeypatch.setattr(service, "COVERAGE_DIR", str(coverage_dir))
    ledger = tmp_path / "ledger.csv"
    ledger.write_text("game_id,season\n1,2023\n")
    monkeypatch.setattr(runner, "PARITY_LEDGER", str(ledger))
    db = str(tmp_path / "fbs.sqlite3")
    runner.write_certificate({"ok": True, "models": {}}, db, NOW)
    assert runner.parity_certified(db)[0] is True
    (coverage_dir / service.COVERAGE_MANIFEST).write_text('{"csv": "t.csv", "csv_sha256": "y"}')
    certified, reason = runner.parity_certified(db)
    assert not certified and "coverage manifest changed" in reason


def test_check_parity_scores_through_service_fit_and_predict(tmp_path, monkeypatch):
    rng = np.random.default_rng(3)
    n = 300
    frame = pd.DataFrame({
        "game_id": [str(i) for i in range(n)],
        "season": [2022] * 150 + [2023] * 150,
        "utc_date": pd.Timestamp("2022-08-01") + pd.to_timedelta(np.arange(n) // 2, unit="D"),
        "y": rng.integers(0, 2, n).astype(float),
        "p_g2": rng.uniform(0.3, 0.7, n),
    })
    for col in service.FEATURES_C:
        frame[col] = 0.0
    ledger = frame[frame["season"] == 2023][["game_id", "season", "y", "p_g2"]].copy()
    ledger["p_g1"] = ledger["p_g2"]
    ledger["p_c2"] = ledger["p_g2"]
    ledger["p_g2h"] = ledger["p_g2"]
    ledger_path = tmp_path / "ledger.csv"
    ledger.to_csv(ledger_path, index=False)

    calls = {"fit": 0, "predict": 0}

    class _Hier:
        grad_norm = 1e-6

    def fake_fit(frame_arg, as_of):
        calls["fit"] += 1
        return {"g2h": _Hier()}

    def fake_predict(frame_arg, state, rows):
        calls["predict"] += 1
        out = rows.copy()
        out["p_c2"] = out["p_g2"]
        out["p_g2h"] = out["p_g2"]
        return out

    monkeypatch.setattr(service, "fit", fake_fit)
    monkeypatch.setattr(service, "predict", fake_predict)
    result = runner.check_parity(frame, str(ledger_path))
    assert calls["fit"] > 0 and calls["predict"] == calls["fit"]
    assert result["estimator"].startswith("service.fit/predict")
    assert result["games"] == 150 and result["ok"] is True


def test_coverage_directory_is_resolved_at_call_time(tmp_path, monkeypatch):
    import json
    (tmp_path / "t.csv").write_text("season,game_id,coverage_status\n2025,a,has_plays\n")
    import hashlib
    digest = hashlib.sha256((tmp_path / "t.csv").read_bytes()).hexdigest()
    (tmp_path / service.COVERAGE_MANIFEST).write_text(json.dumps({"csv": "t.csv", "csv_sha256": digest}))
    monkeypatch.setattr(service, "COVERAGE_DIR", str(tmp_path))
    assert service.load_coverage()["table"]["game_id"].tolist() == ["a"]


def test_results_are_graded_only_from_verified_coverage():
    frame = pd.DataFrame({"season": [2025, 2025], "game_id": ["a", "b"], "y": [1.0, 0.0],
                          "home_team": ["H", "H"], "away_team": ["A", "A"]})
    table = _coverage([(2025, "a", "has_plays"), (2025, "b", "has_plays")])
    kept, _ = service.apply_pbp_eligibility(frame, table)
    assert kept["coverage_status"].tolist() == ["has_plays", "has_plays"]


# -------------------------------------------------------------------------- authoritative grading

class _Board:
    def __init__(self, body):
        self._body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _board_event(event_id, completed, home, away):
    return {"id": event_id, "date": "2022-12-17T05:30Z", "season": {"year": 2022},
            "competitions": [{"status": {"type": {"completed": completed}},
                              "competitors": [{"homeAway": "home", "score": str(home)},
                                              {"homeAway": "away", "score": str(away)}]}]}








def test_archive_and_espn_score_disagreement_halts():
    with pytest.raises(service.FBSModelError, match="disagree"):
        runner.reconcile_final_scores({"10": {"home_score": 24, "away_score": 20}}, {"10": (24, 21)})
    runner.reconcile_final_scores({"10": {"home_score": 24, "away_score": 20}}, {"10": (24, 20)})


def test_pending_grades_are_unpaid_games_whose_kickoff_has_passed(con):
    _scheduled(con, game_id="g1")
    project(con, KICKOFF - dt.timedelta(hours=10), models=("g2h", "g2"), game_id="g1")
    store.freeze_projections(con, now=KICKOFF - store.LOCK_LEAD)
    assert store.pending_grades(con, KICKOFF - dt.timedelta(minutes=5)) == []
    assert [g for g, _ in store.pending_grades(con, KICKOFF + dt.timedelta(minutes=5))] == ["g1"]
    store.grade_forecasts(con, {"g1": {"home_score": 24, "away_score": 20, "verified": True}},
                          now=KICKOFF + dt.timedelta(hours=3))
    assert store.pending_grades(con, KICKOFF + dt.timedelta(hours=4)) == []


def test_legacy_rows_are_pending_a_day_after_their_date_only_stamp(con):
    con.execute("INSERT INTO fbs_forecasts(game_id,model,season,kickoff_utc,home_team,away_team,"
                "model_version,p_home,created_at_utc,locked_at_utc,late,lock_protocol) "
                "VALUES('legacy','g2h',2026,'2026-10-20T00:00:00+00:00','A','B','v',0.7,'x',NULL,1,'legacy')")
    stamp = dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc)
    assert store.pending_grades(con, stamp + dt.timedelta(hours=23)) == []      # the game may not have been played
    assert store.pending_grades(con, stamp + dt.timedelta(days=1, minutes=1)) == [
        ("legacy", "2026-10-20T00:00:00+00:00")]


def _snapshot_db(path, rows):
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE scoreboard_snapshots(league TEXT, game_id TEXT, state TEXT, payload TEXT, fetched_at TEXT)")
    for game_id, payload in rows:
        raw.execute("INSERT INTO scoreboard_snapshots VALUES('ncaaf',?,?,?,'t')",
                    (game_id, payload.get("state", "post"), json.dumps(payload)))
    raw.commit(); raw.close()


def test_scoreboard_snapshots_grade_legacy_and_frozen_rows_without_espn(con, tmp_path):
    live = str(tmp_path / "live.db")
    final = {"status": "Final", "completed": True, "state": "post", "date": "2026-10-20T23:00Z",
             "home": {"score": 23.0}, "away": {"score": 26.0}}
    _snapshot_db(live, [("legacy", final)])
    con.execute("INSERT INTO fbs_forecasts(game_id,model,season,kickoff_utc,home_team,away_team,"
                "model_version,p_home,created_at_utc,locked_at_utc,late,lock_protocol) "
                "VALUES('legacy','g2h',2026,'2026-10-20T00:00:00+00:00','A','B','v',0.79,'x',NULL,1,'legacy')")
    con.commit()
    db = con.execute("PRAGMA database_list").fetchone()[2]
    with patch.object(runner, "board_for_pending", side_effect=AssertionError("ESPN must not be called")):
        result = runner.grade_step(db, dt.datetime(2026, 10, 22, tzinfo=dt.timezone.utc), None,
                                   facts_for=lambda pending: runner.snapshot_facts(pending, live))
    assert result["status"] == "ok" and result["graded"] == 1
    row = con.execute("SELECT result, home_score, away_score FROM fbs_forecasts WHERE game_id='legacy'").fetchone()
    assert tuple(row) == (0, 23, 26)


def test_snapshot_grading_refuses_anything_that_is_not_a_completed_final(tmp_path):
    live = str(tmp_path / "live.db")
    base = {"state": "post", "date": "2026-10-20T23:00Z", "home": {"score": 3.0}, "away": {"score": 0.0}}
    _snapshot_db(live, [
        ("scheduled", {**base, "status": "Scheduled", "completed": False, "state": "pre"}),
        ("live", {**base, "status": "In Progress", "completed": False}),
        ("odd", {**base, "status": "Final", "completed": False}),            # name and flag disagree
        ("postponed", {**base, "status": "Postponed", "completed": False}),
        ("final", {**base, "status": "Final", "completed": True}),
    ])
    pending = [(g, "2026-10-20T00:00:00+00:00") for g in ("scheduled", "live", "odd", "postponed", "final", "missing")]
    facts = runner.snapshot_facts(pending, live)
    plan = {p["game_id"]: p["action"] for p in runner.plan_grades(pending, facts, {})}
    assert plan == {"scheduled": "unresolved", "live": "unresolved", "odd": "unresolved",
                    "postponed": "hold", "final": "grade", "missing": "unresolved"}


# ---------------------------------------------------------------------- explicit schema: open, init, migrate

LEGACY_FORECASTS = """
CREATE TABLE fbs_forecasts (
    game_id TEXT NOT NULL, model TEXT NOT NULL, season INTEGER NOT NULL, kickoff_utc TEXT NOT NULL,
    home_team TEXT NOT NULL, away_team TEXT NOT NULL, home_team_id TEXT, away_team_id TEXT,
    model_version TEXT NOT NULL, p_home REAL NOT NULL, fair_home INTEGER, fair_away INTEGER,
    fitted_through TEXT, created_at_utc TEXT NOT NULL, locked_at_utc TEXT, late INTEGER NOT NULL DEFAULT 0,
    result INTEGER, home_score INTEGER, away_score INTEGER, graded_at_utc TEXT,
    PRIMARY KEY (game_id, model));
CREATE TABLE fbs_model_meta (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO fbs_model_meta VALUES ('train_games', '2901');
INSERT INTO fbs_forecasts VALUES ('1', 'g2h', 2025, '2025-09-06T16:00:00+00:00', 'A', 'B', '10', '11',
    'fbs-g2h-old', 0.61, 60, -150, '2025-09-05', '2025-09-05T10:00:00+00:00', '2025-09-05T10:00:00+00:00',
    0, 1, 31, 24, '2025-09-07T05:00:00+00:00');
INSERT INTO fbs_forecasts VALUES ('2', 'g2', 2025, '2025-09-06T20:00:00+00:00', 'C', 'D', '12', '13',
    'fbs-g2-old', 0.44, NULL, NULL, '2025-09-05', '2025-09-05T10:00:00+00:00', NULL, 0, NULL, NULL, NULL, NULL);
"""
LEGACY_COLUMNS = ["game_id", "model", "season", "kickoff_utc", "home_team", "away_team", "home_team_id",
                  "away_team_id", "model_version", "p_home", "fair_home", "fair_away", "fitted_through",
                  "created_at_utc", "locked_at_utc", "late", "result", "home_score", "away_score", "graded_at_utc"]


def _legacy_db(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(LEGACY_FORECASTS)
    con.commit()
    con.close()


def _rows(path, columns=LEGACY_COLUMNS):
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        return con.execute("SELECT %s FROM fbs_forecasts ORDER BY game_id, model" % ", ".join(columns)).fetchall()
    finally:
        con.close()


def _bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def test_a_writable_open_of_a_legacy_database_fails_closed_and_changes_no_byte(tmp_path):
    db = str(tmp_path / "legacy" / "fbs-model.dev.sqlite3")
    _legacy_db(db)
    before = _bytes(db)
    with pytest.raises(store.SchemaError, match="migration_required") as caught:
        store.open_db(db)
    assert caught.value.code == "migration_required"
    assert _bytes(db) == before


def test_an_empty_or_missing_file_is_not_initialized_and_is_not_created_by_open(tmp_path):
    missing = str(tmp_path / "nothing" / "fbs-model.dev.sqlite3")
    with pytest.raises(store.SchemaError, match="not_initialized"):
        store.open_db(missing)
    assert not os.path.exists(missing)


def test_initialize_creates_a_current_database_and_refuses_an_existing_one(tmp_path):
    db = str(tmp_path / "new" / "scratch.sqlite3")
    store.initialize_new_db(db).close()
    con = store.open_db(db)
    assert con.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
    con.close()
    with pytest.raises(store.SchemaError, match="migration_required"):
        store.initialize_new_db(db)


def test_migrating_a_legacy_copy_keeps_every_existing_row_and_then_opens(tmp_path):
    db = str(tmp_path / "legacy" / "fbs-model.dev.sqlite3")
    _legacy_db(db)
    before = _rows(db)
    evidence = store.migrate(db, str(tmp_path / "backups"))

    assert evidence["action"] == "migrated"
    assert evidence["tables"]["fbs_forecasts"]["rows"] == 2
    assert evidence["lock_protocols"] == {"legacy": 2}
    assert {"fbs_game_status", "fbs_projections", "fbs_unresolved", "fbs_window_outcomes"} <= set(evidence["tables_added"])
    assert _rows(evidence["backup"]) == before                    # the backup is the original, byte-for-byte rows
    assert _rows(db) == before                                    # the original columns are unchanged
    store.open_db(db).close()                                     # now opens: it is at SCHEMA_VERSION


def test_a_second_migration_is_a_no_op_and_writes_no_backup(tmp_path):
    db = str(tmp_path / "legacy" / "fbs-model.dev.sqlite3")
    _legacy_db(db)
    store.migrate(db, str(tmp_path / "backups"))
    again = store.migrate(db, str(tmp_path / "backups"))
    assert again == {"action": "none", "path": db, "schema_version": store.SCHEMA_VERSION}
    assert len(list((tmp_path / "backups").iterdir())) == 1


def test_a_migration_that_would_change_an_existing_row_commits_nothing(tmp_path, monkeypatch):
    db = str(tmp_path / "legacy-2" / "fbs-model.dev.sqlite3")
    _legacy_db(db)
    before = _bytes(db)
    real_upgrade = store._upgrade_statements

    def upgrade_then_damage(con):
        real_upgrade(con)
        for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'fbs_forecasts'").fetchall():
            con.execute('DROP TRIGGER "%s"' % name)                 # the write the immutability guard would stop
        con.execute("UPDATE fbs_forecasts SET p_home = 0.99 WHERE game_id = '1'")
    monkeypatch.setattr(store, "_upgrade_statements", upgrade_then_damage)

    with pytest.raises(RuntimeError, match="would change existing rows"):
        store.migrate(db, str(tmp_path / "backups-2"))
    assert _bytes(db) == before                                   # rolled back: the file is still the legacy one
    backups = list((tmp_path / "backups-2").iterdir())
    assert len(backups) == 1 and _rows(str(backups[0])) == _rows(db)


def test_a_backup_is_never_overwritten(tmp_path, monkeypatch):
    import types
    frozen = type("Frozen", (dt.datetime,), {"now": classmethod(
        lambda cls, tz=None: cls(2026, 10, 21, 12, 0, 0, tzinfo=dt.timezone.utc))})
    monkeypatch.setattr(store, "dt", types.SimpleNamespace(datetime=frozen, timezone=dt.timezone,
                                                           timedelta=dt.timedelta))
    monkeypatch.setattr(store.uuid, "uuid4", lambda: types.SimpleNamespace(hex="00000000deadbeef"))
    first, second = tmp_path / "a" / "fbs-model.dev.sqlite3", tmp_path / "b" / "fbs-model.dev.sqlite3"
    _legacy_db(str(first))
    _legacy_db(str(second))
    backups = str(tmp_path / "backups")
    kept = store.migrate(str(first), backups)["backup"]
    kept_bytes = _bytes(kept)
    with pytest.raises(FileExistsError):
        store.migrate(str(second), backups)
    assert _bytes(kept) == kept_bytes


# ------------------------------------- postseason holds: the store refuses official locks on its own

def _partial_v2(path):
    """A file at SCHEMA_VERSION with every table and trigger, but without fbs_forecasts.cutoff_utc: neither the
    column nor the trigger clause that names it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    partial_schema = store.SCHEMA.replace("    cutoff_utc TEXT,\n", "")
    partial_triggers = store.TRIGGERS.replace(" projected_at_utc, cutoff_utc,", " projected_at_utc,")
    assert partial_schema != store.SCHEMA and partial_triggers != store.TRIGGERS
    raw = sqlite3.connect(path)
    raw.executescript(partial_schema + partial_triggers)
    raw.execute("PRAGMA user_version = %d" % store.SCHEMA_VERSION)
    raw.execute("INSERT INTO fbs_game_status(game_id,season,revision,lifecycle,observed_utc,source,grading_state)"
                " VALUES('1',2026,1,'scheduled','2026-10-20T00:00:00+00:00','test','pending')")
    raw.commit()
    raw.close()


def test_a_version_two_file_missing_a_required_column_is_migration_required_and_unchanged(tmp_path):
    db = str(tmp_path / "partial" / "fbs-model.dev.sqlite3")
    _partial_v2(db)
    before = _bytes(db)
    probe = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    assert store.schema_state(probe) == "legacy"
    probe.close()
    with pytest.raises(store.SchemaError, match="migration_required"):
        store.open_db(db)
    assert _bytes(db) == before
    report = runner.audit(db)
    assert report["schema_status"] == "migration_required" and report["schema_version"] == store.SCHEMA_VERSION
    assert {(u.get("table"), u.get("column")) for u in report["unavailable"]} == {("fbs_forecasts", "cutoff_utc")}
    assert _bytes(db) == before


def test_explicit_migration_recovers_an_incomplete_version_two_copy_and_refreshes_its_triggers(tmp_path):
    db = str(tmp_path / "partial-copy" / "fbs-model.dev.sqlite3")
    _partial_v2(db)
    evidence = store.migrate(db, str(tmp_path / "backups"))
    assert evidence["action"] == "migrated"
    con = store.open_db(db)
    assert "cutoff_utc" in store.table_columns(con, "fbs_forecasts")
    assert tuple(con.execute("SELECT game_id, season, revision, lifecycle, grading_state FROM fbs_game_status").fetchone()) \
        == ("1", 2026, 1, "scheduled", "pending")
    trigger_sql = con.execute("SELECT sql FROM sqlite_master WHERE name = 'fbs_forecast_lock_immutable'").fetchone()[0]
    assert "cutoff_utc" in trigger_sql
    con.close()
    assert store.migrate(db, str(tmp_path / "backups"))["action"] == "none"
    assert runner.audit(db)["schema_status"] == "current"


def test_midnight_kickoffs_show_the_scoreboard_time_and_leave_unknown_games_alone(tmp_path):
    live = str(tmp_path / "live.db")
    raw = sqlite3.connect(live)
    raw.execute("CREATE TABLE scoreboard_snapshots(league TEXT, game_id TEXT, state TEXT, payload TEXT, fetched_at TEXT)")
    raw.execute("INSERT INTO scoreboard_snapshots VALUES('ncaaf','1','post',?,'t')",
                (json.dumps({"date": "2026-10-20T23:00Z"}),))
    raw.commit(); raw.close()
    games = [{"game_id": "1", "kickoff_utc": "2026-10-20T00:00:00+00:00"},
             {"game_id": "2", "kickoff_utc": "2026-10-22T00:00:00+00:00"},
             {"game_id": "3", "kickoff_utc": "2026-10-21T18:30:00+00:00"}]
    out = store.apply_scoreboard_details({"games": games}, live)["games"]
    by_id = {g["game_id"]: g["kickoff_utc"] for g in out}
    assert by_id["1"] == "2026-10-20T23:00:00+00:00"
    assert by_id["2"] == "2026-10-22T00:00:00+00:00"
    assert by_id["3"] == "2026-10-21T18:30:00+00:00"


def test_records_go_into_the_game_not_after_it(tmp_path):
    live = str(tmp_path / "live2.db")
    raw = sqlite3.connect(live)
    raw.execute("CREATE TABLE scoreboard_snapshots(league TEXT, game_id TEXT, state TEXT, payload TEXT, fetched_at TEXT)")
    final = {"date": "2026-10-20T23:00Z", "completed": True,
             "home": {"score": 20.0, "record": "4-3"}, "away": {"score": 13.0, "record": "4-3"}}
    ahead = {"date": "2026-10-22T23:00Z", "completed": False,
             "home": {"score": None, "record": "5-2"}, "away": {"score": None, "record": "3-3"}}
    raw.execute("INSERT INTO scoreboard_snapshots VALUES('ncaaf','1','post',?,'t')", (json.dumps(final),))
    raw.execute("INSERT INTO scoreboard_snapshots VALUES('ncaaf','2','pre',?,'t')", (json.dumps(ahead),))
    raw.commit(); raw.close()
    games = [{"game_id": "1", "kickoff_utc": "2026-10-20T00:00:00+00:00"},
             {"game_id": "2", "kickoff_utc": "2026-10-22T00:00:00+00:00"},
             {"game_id": "3", "kickoff_utc": "2026-10-23T00:00:00+00:00"}]
    out = {g["game_id"]: g for g in store.apply_scoreboard_details({"games": games}, live)["games"]}
    assert (out["1"]["home_record"], out["1"]["away_record"]) == ("3-3", "4-2")  # home won, away lost
    assert (out["2"]["home_record"], out["2"]["away_record"]) == ("5-2", "3-3")
    assert (out["3"]["home_record"], out["3"]["away_record"]) == (None, None)
