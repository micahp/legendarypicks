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


def test_forecast_is_not_locked_before_the_t90_window(con):
    report = store.lock_forecasts(con, [_row()], now=KICKOFF - dt.timedelta(hours=10))
    assert report["not_due"] == 1
    assert con.execute("SELECT COUNT(*) FROM fbs_forecasts").fetchone()[0] == 0


def test_lock_inside_window_is_labelled_and_immutable(con):
    inside = KICKOFF - dt.timedelta(minutes=45)
    _scheduled(con)
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
    _scheduled(con)
    store.lock_forecasts(con, [_row(model=m) for m in store.MODEL_IDS], now=inside)
    payload = store.export_payload(con, 2026)
    game = payload["games"][0]
    assert game["status"] == "locked"
    assert game["locked_at_utc"] == inside.isoformat()
    assert game["models"]["g2h"]["locked_at_utc"] == inside.isoformat()
    assert payload["records"]["g2h"]["forecasts"] == 1  # one official g2h forecast, not yet graded
    assert payload["records"]["g2h"]["graded"] == 0


def test_legacy_rows_are_labelled_and_kept_out_of_the_record(con):
    # Shape of a row written before the protocol: midnight kickoff, labelled legacy.
    con.execute("INSERT INTO fbs_forecasts(game_id,model,season,kickoff_utc,home_team,away_team,"
                "model_version,p_home,created_at_utc,locked_at_utc,late,lock_protocol) "
                "VALUES('1','g2h',2026,'2026-10-20T00:00:00+00:00','A','B','fbs-g2h-x',0.7,"
                "'2026-10-20T21:26:35+00:00',NULL,1,'legacy')")
    payload = store.export_payload(con, 2026)
    assert payload["games"][0]["status"] == "legacy"
    assert payload["records"]["g2h"]["forecasts"] == 0
    assert payload["records"]["g2h"]["legacy"] == 1
    assert payload["records"]["g2h"]["late"] == 1


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
    store.lock_forecasts(con, [_row(game_id="g1"), _row(game_id="g1", model="g2")], now=KICKOFF - dt.timedelta(hours=1))
    assert store.pending_grades(con, KICKOFF - dt.timedelta(minutes=5)) == []
    assert [g for g, _ in store.pending_grades(con, KICKOFF + dt.timedelta(minutes=5))] == ["g1"]
    store.grade_forecasts(con, {"g1": {"home_score": 24, "away_score": 20}}, now=KICKOFF + dt.timedelta(hours=3))
    assert store.pending_grades(con, KICKOFF + dt.timedelta(hours=4)) == []


def test_legacy_rows_are_never_pending_for_grading(con):
    con.execute("INSERT INTO fbs_forecasts(game_id,model,season,kickoff_utc,home_team,away_team,"
                "model_version,p_home,created_at_utc,locked_at_utc,late,lock_protocol) "
                "VALUES('legacy','g2h',2026,'2026-10-20T00:00:00+00:00','A','B','v',0.7,'x',NULL,1,'legacy')")
    assert store.pending_grades(con, KICKOFF + dt.timedelta(days=1)) == []
