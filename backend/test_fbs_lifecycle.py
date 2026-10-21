"""Lifecycle of the NCAAF forecasting operation: status, grading, locks, revisions, outages and voids.

Boards are stubbed at ESPN's scoreboard boundary (runner.read_scoreboard), so the real parsing,
classification, planning and writes all run. The forecast tests fit and predict with the real
service on a synthetic frame. Locks are allowed only where a test stubs the parity certificate;
no real certificate is used here.
"""
import datetime as dt
import os
import math
import sqlite3

import numpy as np
import pandas as pd
import pytest

import fbs_lifecycle as life
import fbs_model_runner as runner
import fbs_model_service as service
import fbs_model_store as store


def open_scratch(path):
    """A scratch database at the current schema: created new if absent, otherwise opened. Never migrated."""
    if not os.path.exists(path):
        store.initialize_new_db(path).close()
    return store.open_db(path)
from fbs_phase3_features_c import FEATURE_NAMES_C as FEATS

KICK = dt.datetime(2026, 10, 24, 16, 0, tzinfo=dt.timezone.utc)      # 12:00 ET, 2026-10-24
NOW_EARLY = KICK - dt.timedelta(hours=10)
NOW_WINDOW = KICK - dt.timedelta(minutes=60)                         # inside T-90
GAME = "9001"
HOME = ("2229", "Florida International")
AWAY = ("2393", "Middle Tennessee")


# ------------------------------------------------------------------------------------ helpers

def board_event(game_id, kickoff, name, completed, home_score=None, away_score=None, home=HOME, away=AWAY,
                season=2026, neutral=False, season_type=2):
    def comp(side, team, score):
        return {"homeAway": side, "score": None if score is None else str(score),
                "team": {"id": team[0], "location": team[1], "displayName": team[1] + " Team"}}
    state = "post" if completed else "pre"
    return {"id": game_id, "date": kickoff, "season": {"year": season, "type": season_type}, "week": {"number": 8},
            "competitions": [{"neutralSite": neutral,
                              "status": {"type": {"name": name, "state": state, "completed": completed}},
                              "competitors": [comp("home", home, home_score), comp("away", away, away_score)]}]}


@pytest.fixture
def con(tmp_path):
    connection = open_scratch(str(tmp_path / "fbs-model.dev.sqlite3"))
    yield connection
    connection.close()


@pytest.fixture
def boards(monkeypatch):
    """date (YYYYMMDD) -> list of events. A date not present raises, as an unreadable board does."""
    by_date = {}

    def read(date):
        if date not in by_date:
            raise runner.SlateUnavailable("ESPN scoreboard %s unreadable (test: not stubbed)" % date)
        return {"events": list(by_date[date])}

    monkeypatch.setattr(runner, "read_scoreboard", read)
    monkeypatch.setattr(runner, "BOARD_PACE_SECONDS", 0)
    return by_date


def put_board(boards, when_utc, events):
    for day in life.eastern_dates(when_utc):
        boards.setdefault(day, [])
    boards[life.eastern_dates(when_utc)[0]] = list(events)


def observe(con, game_id, kickoff, now, lifecycle="scheduled", status_name="STATUS_SCHEDULED",
            home=HOME, away=AWAY, season=2026, neutral=False):
    rec = dict(game_id=game_id, season=season, kickoff_utc=kickoff.isoformat(),
               home_team="Florida International", away_team="Middle Tennessee",
               home_team_id=home[0], away_team_id=away[0], neutral_site=neutral)
    obs = store.observe_fixture(con, rec, now, "test")
    grading = "void" if lifecycle in life.VOID_LIFECYCLES else "pending"
    reason = lifecycle if lifecycle in life.NO_WINDOW_LIFECYCLES else None
    store.set_game_status(con, game_id, season, obs["revision"], lifecycle, status_name, now.isoformat(),
                          "test", grading, reason)
    return obs


def lock_row(game_id, kickoff, model="g2h", p=0.62, home=HOME, away=AWAY):
    return {"game_id": game_id, "model": model, "season": 2026, "kickoff_utc": kickoff.isoformat(),
            "home_team": "Florida International", "away_team": "Middle Tennessee",
            "home_team_id": home[0], "away_team_id": away[0], "model_version": "fbs-g2h-test",
            "p_home": p, "fitted_through": "2026-10-17"}


def lock(con, game_id, kickoff, now, models=("g2h",), p=0.62):
    rows = [lock_row(game_id, kickoff, model=m, p=p) for m in models]
    return store.lock_forecasts(con, rows, now=now)


# --------------------------------------------------------------------------- pure lifecycle rules

@pytest.mark.parametrize("name, completed, expected", [
    ("STATUS_SCHEDULED", False, "scheduled"),
    ("STATUS_IN_PROGRESS", False, "in_progress"),
    ("STATUS_HALFTIME", False, "in_progress"),
    ("STATUS_FINAL", True, "completed"),
    ("STATUS_FINAL", False, "unknown"),          # name says final, flag says not: contradiction
    ("STATUS_SCHEDULED", True, "unknown"),       # name says scheduled, flag says done: contradiction
    ("STATUS_POSTPONED", False, "postponed"),
    ("STATUS_DELAYED", False, "delayed"),
    ("STATUS_SUSPENDED", False, "suspended"),
    ("STATUS_CANCELED", False, "cancelled"),
    ("STATUS_ABANDONED", False, "abandoned"),
    ("STATUS_FORFEIT", False, "forfeit"),
    ("STATUS_NO_CONTEST", False, "no_contest"),
    ("STATUS_SOMETHING_NEW", False, "unknown"),
    (None, False, "unknown"),
])
def test_status_names_map_to_lifecycle_and_contradictions_are_unknown(name, completed, expected):
    assert life.classify_status(name, completed) == expected


def test_only_a_scheduled_game_before_kickoff_can_lock():
    assert life.is_lockable("scheduled", KICK, NOW_WINDOW)
    assert not life.is_lockable("scheduled", KICK, KICK)              # started: never locks
    for lifecycle in ("in_progress", "postponed", "delayed", "suspended", "cancelled", "unknown", "completed"):
        assert not life.is_lockable(lifecycle, KICK, NOW_WINDOW), lifecycle


def test_a_midnight_utc_reschedule_is_still_found_on_its_eastern_date():
    midnight = dt.datetime(2026, 10, 25, 0, 30, tzinfo=dt.timezone.utc)   # 20:30 ET on 24 Oct
    dates = life.eastern_dates(midnight)
    assert dates[0] == "20261024" and "20261025" in dates and "20261023" in dates
    assert len(dates) == len(set(dates))


def test_retries_back_off_within_a_cap_and_alert_after_the_sla():
    now = KICK
    assert life.next_attempt(0, now) == now + dt.timedelta(minutes=15)
    assert life.next_attempt(1, now) == now + dt.timedelta(minutes=30)
    assert life.next_attempt(30, now) == now + life.RETRY_CAP
    assert not life.alert_due(KICK, KICK + dt.timedelta(hours=23))
    assert life.alert_due(KICK, KICK + dt.timedelta(hours=24))


def test_grading_plan_decides_each_lifecycle_and_never_grades_an_absent_game():
    pending = [("a", str(KICK)), ("b", str(KICK)), ("c", str(KICK)), ("d", str(KICK)), ("e", str(KICK)),
               ("f", str(KICK)), ("g", str(KICK))]
    facts = {
        "a": {"lifecycle": "completed", "status_name": "STATUS_FINAL", "season": 2026, "home_score": 24, "away_score": 20},
        "b": {"lifecycle": "cancelled", "status_name": "STATUS_CANCELED", "season": 2026, "home_score": None, "away_score": None},
        "c": {"lifecycle": "postponed", "status_name": "STATUS_POSTPONED", "season": 2026, "home_score": None, "away_score": None},
        "d": {"lifecycle": "completed", "status_name": "STATUS_FINAL", "season": 2026, "home_score": 10, "away_score": 17},
        "e": {"lifecycle": "completed", "status_name": "STATUS_FINAL", "season": 2026, "home_score": None, "away_score": None},
        "f": {"lifecycle": "in_progress", "status_name": "STATUS_IN_PROGRESS", "season": 2026, "home_score": 3, "away_score": 0},
        "g": None,
    }
    archive = {"d": (10, 14)}     # archive disagrees with ESPN for d
    plan = {p["game_id"]: p for p in runner.plan_grades(pending, facts, archive)}
    assert plan["a"]["action"] == "grade" and plan["a"]["home_score"] == 24
    assert plan["b"]["action"] == "void" and plan["b"]["reason"] == "cancelled"
    assert plan["c"]["action"] == "hold" and plan["c"]["reason"] == "schedule_unresolved_postponed"
    assert plan["d"]["action"] == "quarantine" and plan["d"]["reason"] == "archive_espn_score_mismatch"
    assert plan["e"]["action"] == "unresolved" and plan["e"]["reason"] == "completed_without_scores"
    assert plan["f"]["action"] == "unresolved" and plan["f"]["reason"] == "status_in_progress"
    assert plan["g"]["action"] == "unresolved" and plan["g"]["reason"] == "absent_from_board"


# ------------------------------------------------------------------------------- store lifecycle

def test_locks_are_refused_for_postponed_cancelled_and_unknown_games(con):
    for status in ("postponed", "cancelled", "unknown"):
        gid = "x-" + status
        observe(con, gid, KICK, NOW_EARLY, lifecycle=status)
        report = store.lock_forecasts(con, [lock_row(gid, KICK)], now=NOW_WINDOW)
        assert report["inserted"] == 0 and report["blocked_status"] == 1, status
    assert con.execute("SELECT COUNT(*) FROM fbs_forecasts").fetchone()[0] == 0


def test_a_lock_is_refused_when_its_kickoff_is_not_the_current_revision(con):
    observe(con, GAME, KICK, NOW_EARLY)
    moved = KICK + dt.timedelta(hours=2)
    observe(con, GAME, moved, NOW_EARLY + dt.timedelta(hours=1))           # schedule revision 2
    report = store.lock_forecasts(con, [lock_row(GAME, KICK)], now=NOW_WINDOW)
    assert report["blocked_revision"] == 1 and report["inserted"] == 0


def test_a_rescheduled_game_locks_at_its_new_revision_when_nothing_was_locked(con):
    observe(con, GAME, KICK, NOW_EARLY)
    moved = KICK + dt.timedelta(hours=2)
    observe(con, GAME, moved, NOW_EARLY + dt.timedelta(hours=1))
    now = moved - dt.timedelta(minutes=60)
    report = store.lock_forecasts(con, [lock_row(GAME, moved)], now=now)
    assert report["inserted"] == 1
    row = con.execute("SELECT kickoff_utc, kickoff_revision FROM fbs_forecasts").fetchone()
    assert parse(row[0]) == moved and row[1] == 2


def parse(text):
    return store.parse_time(text)


def test_an_existing_lock_survives_a_reschedule_unchanged(con):
    observe(con, GAME, KICK, NOW_EARLY)
    lock(con, GAME, KICK, NOW_WINDOW, p=0.62)
    before = con.execute("SELECT kickoff_utc, p_home, locked_at_utc, kickoff_revision FROM fbs_forecasts").fetchone()
    moved = KICK + dt.timedelta(hours=3)
    observe(con, GAME, moved, NOW_WINDOW + dt.timedelta(minutes=5))
    report = store.lock_forecasts(con, [lock_row(GAME, moved, p=0.41)], now=moved - dt.timedelta(minutes=30))
    assert report["existing"] == 1 and report["inserted"] == 0          # no second official lock
    after = con.execute("SELECT kickoff_utc, p_home, locked_at_utc, kickoff_revision FROM fbs_forecasts").fetchone()
    assert tuple(after) == tuple(before)
    with pytest.raises(sqlite3.Error):
        con.execute("UPDATE fbs_forecasts SET kickoff_utc = ?", (moved.isoformat(),))
    with pytest.raises(sqlite3.Error):
        con.execute("UPDATE fbs_forecasts SET p_home = 0.9")


def test_a_lock_that_becomes_cancelled_is_void_and_outside_win_loss_and_brier(con):
    observe(con, GAME, KICK, NOW_EARLY)
    lock(con, GAME, KICK, NOW_WINDOW, p=0.62)
    observe(con, GAME, KICK, KICK - dt.timedelta(minutes=5), lifecycle="cancelled", status_name="STATUS_CANCELED")
    payload = store.export_payload(con, 2026)
    g2h = payload["records"]["g2h"]
    assert g2h["graded"] == 0 and g2h["brier"] is None and g2h["forecasts"] == 0 and g2h["void"] == 1
    assert con.execute("SELECT p_home FROM fbs_forecasts").fetchone()[0] == 0.62
    assert payload["games"][0]["grading_state"] == "void"


def test_a_missed_window_is_classified_three_ways_and_uses_the_current_kickoff(con):
    # 1. verified scheduled before kickoff, no lock: a genuine missed window
    observe(con, GAME, KICK, NOW_EARLY)
    store.upsert_previews(con, [lock_row(GAME, KICK)], now=NOW_EARLY)
    counts = store.record_missed_windows(con, now=KICK + dt.timedelta(hours=1))
    assert counts["missed_t90_window"] == 1 and counts["blocked_unverified_at_cutoff"] == 0
    # 2. a postponement before kickoff is not eligible, even when a later lock could not happen
    other = "9100"
    observe(con, other, KICK, NOW_EARLY)
    store.upsert_previews(con, [lock_row(other, KICK)], now=NOW_EARLY)
    observe(con, other, KICK, NOW_EARLY + dt.timedelta(hours=1), lifecycle="postponed", status_name="STATUS_POSTPONED")
    counts = store.record_missed_windows(con, now=KICK + dt.timedelta(hours=1))
    assert counts["window_not_eligible"] == 1 and counts["missed_t90_window"] == 0
    # 3. a previewed game with no verified pregame status was never eligible to lock
    unverified = "9101"
    store.upsert_previews(con, [lock_row(unverified, KICK)], now=NOW_EARLY)
    counts = store.record_missed_windows(con, now=KICK + dt.timedelta(hours=1))
    assert counts["blocked_unverified_at_cutoff"] == 1 and counts["missed_t90_window"] == 0
    # outcomes are recorded once; a moved game is not missed at the old kickoff
    assert store.record_missed_windows(con, now=KICK + dt.timedelta(hours=2)) == {
        "missed_t90_window": 0, "blocked_unverified_at_cutoff": 0, "window_not_eligible": 0}
    moved = KICK + dt.timedelta(days=1)
    observe(con, "9102", KICK, NOW_EARLY)
    store.upsert_previews(con, [lock_row("9102", KICK)], now=NOW_EARLY)
    observe(con, "9102", moved, KICK + dt.timedelta(hours=2))
    assert store.record_missed_windows(con, now=KICK + dt.timedelta(hours=3))["missed_t90_window"] == 0
    # re-verified as scheduled at its new kickoff, with no lock written in that window: a genuine miss
    assert store.record_missed_windows(con, now=moved + dt.timedelta(minutes=1))["missed_t90_window"] == 1


def test_an_absent_or_changed_opponent_is_never_the_same_fixture(con):
    observe(con, GAME, KICK, NOW_EARLY)
    other = ("9999", "Some Other School")
    obs = store.observe_fixture(con, dict(game_id=GAME, season=2026, kickoff_utc=KICK.isoformat(),
                                          home_team="x", away_team="y", home_team_id=HOME[0],
                                          away_team_id=other[0], neutral_site=False), NOW_WINDOW, "test")
    assert obs["identity_changed"] is True and obs["revision"] == 1
    report = store.lock_forecasts(con, [lock_row(GAME, KICK, away=other)], now=NOW_WINDOW)
    assert report["inserted"] == 0 and report["blocked_status"] == 1


# ----------------------------------------------------------------------------- grading and outages

def test_a_grade_board_outage_writes_nothing(tmp_path, boards):
    db = str(tmp_path / "grade-outage.sqlite3")
    con = open_scratch(db)
    observe(con, GAME, KICK, NOW_EARLY)
    lock(con, GAME, KICK, NOW_WINDOW)
    con.close()
    now = KICK + dt.timedelta(hours=4)
    report = runner.grade_step(db, now)
    assert report["status"] == "grade_source_unavailable"
    con = store.open_db(db, readonly=True)
    assert con.execute("SELECT result FROM fbs_forecasts").fetchone()[0] is None
    con.close()


def test_a_score_mismatch_quarantines_only_the_affected_game(tmp_path, boards):
    db = str(tmp_path / "grade.sqlite3")
    con = open_scratch(db)
    other = "9002"
    observe(con, GAME, KICK, NOW_EARLY)
    observe(con, other, KICK, NOW_EARLY)
    lock(con, GAME, KICK, NOW_WINDOW)
    lock(con, other, KICK, NOW_WINDOW)
    con.close()
    now = KICK + dt.timedelta(hours=4)
    put_board(boards, KICK, [board_event(GAME, KICK.isoformat(), "STATUS_FINAL", True, 24, 20),
                             board_event(other, KICK.isoformat(), "STATUS_FINAL", True, 17, 10)])
    frame = pd.DataFrame({"game_id": [GAME, other], "season": [2026, 2026], "y": [1.0, 1.0],
                          "coverage_status": ["has_plays", "has_plays"],
                          "home_score": [24, 17], "away_score": [14, 10]})     # archive disagrees on GAME
    report = runner.grade_step(db, now, frame)
    assert report["graded"] == 1 and report["quarantine"] == 1
    con = store.open_db(db, readonly=True)
    rows = dict(con.execute("SELECT game_id, result FROM fbs_forecasts").fetchall())
    states = dict(con.execute("SELECT game_id, grading_state FROM fbs_game_status").fetchall())
    con.close()
    assert rows[GAME] is None and states[GAME] == "quarantined"
    assert rows[other] == 1 and states[other] == "graded"


def test_absent_games_are_retried_on_backoff_then_resolved_from_a_later_board(tmp_path, boards):
    db = str(tmp_path / "absent.sqlite3")
    con = open_scratch(db)
    observe(con, GAME, KICK, NOW_EARLY)
    lock(con, GAME, KICK, NOW_WINDOW)
    con.close()
    first = KICK + dt.timedelta(hours=1)
    put_board(boards, KICK, [])                                       # absent from every board
    report = runner.grade_step(db, first)
    assert report["unresolved"] == 1 and report["graded"] == 0
    con = store.open_db(db, readonly=True)
    row = con.execute("SELECT attempts, next_attempt_utc, alert_state, resolved_utc FROM fbs_unresolved").fetchone()
    con.close()
    assert row[0] == 1 and row[2] == "none" and row[3] is None
    assert runner.grade_step(db, first + dt.timedelta(minutes=5))["status"] == "nothing_due"
    alert_time = KICK + dt.timedelta(hours=25)
    report = runner.grade_step(db, alert_time)
    assert report["unresolved"] == 1
    con = store.open_db(db, readonly=True)
    assert con.execute("SELECT alert_state FROM fbs_unresolved").fetchone()[0] == "alerted"
    con.close()
    put_board(boards, KICK, [board_event(GAME, KICK.isoformat(), "STATUS_FINAL", True, 24, 20)])
    report = runner.grade_step(db, alert_time + dt.timedelta(hours=7))
    assert report["graded"] == 1
    con = store.open_db(db, readonly=True)
    assert con.execute("SELECT resolved_utc FROM fbs_unresolved").fetchone()[0] is not None
    con.close()


def test_a_cancelled_board_voids_without_grading_and_leaves_the_forecast_alone(tmp_path, boards):
    db = str(tmp_path / "void.sqlite3")
    con = open_scratch(db)
    observe(con, GAME, KICK, NOW_EARLY)
    lock(con, GAME, KICK, NOW_WINDOW, p=0.7)
    con.close()
    put_board(boards, KICK, [board_event(GAME, KICK.isoformat(), "STATUS_CANCELED", False)])
    report = runner.grade_step(db, KICK + dt.timedelta(hours=4))
    assert report["void"] == 1 and report["graded"] == 0
    con = store.open_db(db, readonly=True)
    assert tuple(con.execute("SELECT result, p_home FROM fbs_forecasts").fetchone()) == (None, 0.7)
    con.close()


# --------------------------------------------------------------------------- end-to-end forecast

def synthetic_frame(season=2025, n=300, seed=7):
    rng = np.random.default_rng(seed)
    teams = [(str(100 + i), "Team %d" % i, "SEC" if i % 2 else "Big 12") for i in range(12)]
    rows = []
    for i in range(n):
        h, a = teams[i % 12], teams[(i * 5 + 3) % 12]
        if h == a:
            a = teams[(i + 1) % 12]
        rows.append(dict(game_id="t%d" % i, season=season, fbs_game=True,
                         utc_date=pd.Timestamp("%d-08-20" % season) + pd.to_timedelta(i // 4, unit="D"),
                         home_team_id=h[0], away_team_id=a[0], home_team=h[1], away_team=a[1],
                         home_conference=h[2], away_conference=a[2], neutral_site=False,
                         y=float(rng.integers(0, 2)), p_g2=float(rng.uniform(0.35, 0.65))))
    frame = pd.DataFrame(rows)
    frame["coverage_status"] = "has_plays"
    frame["home_score"] = 1
    frame["away_score"] = 0
    for col in FEATS:
        frame[col] = rng.normal(size=n)
    return frame


@pytest.fixture
def forecast_env(monkeypatch, boards):
    frame = synthetic_frame()
    monkeypatch.setattr(service, "build_frame", lambda *a, **k: (frame, pd.DataFrame()))

    def fake_g2(frame_arg, slate):
        out = slate.copy()
        out["season"] = 2026
        out["p_g2"] = 0.6
        out["home_conference"] = "SEC"
        out["away_conference"] = "Big 12"
        out["neutral_site"] = out["neutral_site"].astype(bool)
        return out
    monkeypatch.setattr(runner, "g2_for_slate", fake_g2)

    def fake_features(team_games, frame_arg, candidates, now):
        out = pd.DataFrame({"game_id": candidates["game_id"].astype(str), **{c: 0.0 for c in FEATS}})
        for side in ("home", "away"):
            out[side + "_prior_season_only"] = False
            out[side + "_no_history"] = False
        return out
    monkeypatch.setattr(runner, "slate_features", fake_features)
    monkeypatch.setattr(runner, "parity_certified", lambda db_path: (True, "TEST STUB certificate"))
    return frame


def window_board(boards, now, events):
    for day in runner.scoreboard_dates(now, 10):          # exactly the boards a run reads
        boards.setdefault(day, [])
    for event in events:
        day = life.eastern_dates(pd.Timestamp(event["date"]).to_pydatetime())[0]
        boards.setdefault(day, [])
        boards[day].append(event)


def test_a_historical_grade_outage_does_not_block_a_verified_t90_lock(tmp_path, forecast_env, boards, monkeypatch):
    db = str(tmp_path / "independent.sqlite3")
    now = KICK - dt.timedelta(minutes=60)
    window_board(boards, now, [board_event(GAME, KICK.isoformat(), "STATUS_SCHEDULED", False)])
    past = KICK - dt.timedelta(days=2)
    con = open_scratch(db)
    observe(con, "past", past, past - dt.timedelta(days=5))
    lock(con, "past", past, past - dt.timedelta(minutes=60))
    con.close()
    report = runner.run(days=10, db_path=db, now=now)
    assert report["forecast"]["status"] == "ok"
    assert report["grade"]["status"] == "grade_source_unavailable"
    assert report["locked"]["inserted"] == len(runner.MODEL_ORDER)
    con = store.open_db(db, readonly=True)
    locked = con.execute("SELECT COUNT(*) FROM fbs_forecasts WHERE game_id=? AND lock_protocol='t90'", (GAME,)).fetchone()[0]
    con.close()
    assert locked >= 1


def test_a_current_slate_outage_blocks_new_previews_and_locks_but_grades_independently(tmp_path, forecast_env, boards):
    db = str(tmp_path / "slate-down.sqlite3")
    now = KICK - dt.timedelta(minutes=60)
    past = KICK - dt.timedelta(days=2)
    con = open_scratch(db)
    observe(con, "past", past, past - dt.timedelta(days=5))
    lock(con, "past", past, past - dt.timedelta(minutes=60))
    con.close()
    put_board(boards, past, [board_event("past", past.isoformat(), "STATUS_FINAL", True, 24, 20)])
    # the current window is not stubbed, so the live slate cannot be read
    report = runner.run(days=10, db_path=db, now=now)
    assert report["forecast"]["status"] == "slate_unavailable"
    assert report["previewed"] == 0 and report["locked"].get("blocked") == "slate_unavailable"
    assert report["grade"]["status"] == "ok" and report["grade"]["graded"] == 1
    con = store.open_db(db, readonly=True)
    assert con.execute("SELECT COUNT(*) FROM fbs_previews").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM fbs_forecasts WHERE game_id=?", (GAME,)).fetchone()[0] == 0
    con.close()


def test_a_delayed_game_inside_the_window_takes_no_new_lock(tmp_path, forecast_env, boards):
    db = str(tmp_path / "delayed.sqlite3")
    open_scratch(db).close()
    now = KICK - dt.timedelta(minutes=60)
    window_board(boards, now, [board_event(GAME, KICK.isoformat(), "STATUS_DELAYED", False)])
    report = runner.run(days=10, db_path=db, now=now)
    assert report["forecast"]["status"] == "ok"
    assert report["locked"]["inserted"] == 0
    con = store.open_db(db, readonly=True)
    assert con.execute("SELECT reason FROM fbs_game_status WHERE game_id=?", (GAME,)).fetchone()[0] \
        == "schedule_unresolved_delayed"
    con.close()


# ------------------------------------------------------------------------------- neutral site

def elo_history(season=2025, n=240, seed=11):
    """Completed FBS games in the schema load_events supplies, so the real baseline reads a real history."""
    rng = np.random.default_rng(seed)
    teams = [(str(100 + i), "Team %d" % i, "SEC" if i % 2 else "Big 12") for i in range(12)]
    rows = []
    for i in range(n):
        h, a = teams[i % 12], teams[(i * 5 + 3) % 12]
        if h == a:
            a = teams[(i + 1) % 12]
        kick = dt.datetime(season, 9, 1, 16, tzinfo=dt.timezone.utc) + dt.timedelta(days=i // 4)
        home_score, away_score = int(rng.integers(14, 45)), int(rng.integers(14, 45))
        rows.append({
            "game_id": "h%d" % i, "season": season, "week": None, "kickoff_utc": kick, "utc_date": kick.date(),
            "week_start_utc": (kick - dt.timedelta(days=kick.weekday())).date().isoformat(),
            "home_team_id": h[0], "away_team_id": a[0], "home_team": h[1], "away_team": a[1],
            "home_conference": h[2], "away_conference": a[2], "home_score": home_score, "away_score": away_score,
            "home_win": float(home_score > away_score), "neutral_site": False, "fbs_game": True,
            "fbs_participant": True, "cfb_completed": True, "evaluation_population": True,
            "game_phase": "Regular season", "season_type": "regular", "result_source": "test history",
            "home_model_favorite": np.nan,
        })
    return pd.DataFrame(rows)


def test_a_neutral_site_game_is_priced_by_the_real_elo_baseline(monkeypatch):
    """Only the data load is stubbed. The Elo baseline is the real base.make_predictions: a neutral flag must
    remove exactly the baseline's home advantage from the probability, and conferences must reach the model."""
    frame = synthetic_frame(season=2026)
    state = service.fit(frame, dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc))
    history = elo_history()
    captured = {}
    real_predictions = runner.base.make_predictions

    def spy(combined, first_season):
        captured["combined"] = combined.copy()
        return real_predictions(combined, first_season)

    monkeypatch.setattr(runner.base, "load_events", lambda data_dir, seasons: (history.copy(), None, None, None))
    monkeypatch.setattr(runner.base, "make_predictions", spy)
    kick = pd.Timestamp("2026-10-24T16:00Z")
    teams = dict(home_team_id="100", away_team_id="101", home_team="Team 0", away_team="Team 1", week=8,
                  season=2026, season_type=2)
    slate = pd.DataFrame([dict(game_id="N1", kickoff_utc=kick, neutral_site=True, **teams),
                          dict(game_id="H1", kickoff_utc=kick, neutral_site=False, **teams)])
    scored = runner.g2_for_slate(frame, slate).set_index("game_id")

    combined = captured["combined"]
    event = combined.loc[combined.game_id == "N1"].iloc[0]
    assert bool(event["neutral_site"]) is True
    assert event["home_conference"] == frame.loc[frame.home_team_id == "100", "home_conference"].iloc[0]
    assert event["away_conference"] == frame.loc[frame.away_team_id == "101", "away_conference"].iloc[0]

    logit = lambda p: math.log(p / (1.0 - p))
    gap = logit(float(scored.loc["H1", "p_g2"])) - logit(float(scored.loc["N1", "p_g2"]))
    assert gap == pytest.approx(runner.base.ELO_HOME_ADVANTAGE / 400.0 * math.log(10), abs=1e-9)

    rows = scored.loc[["N1"]].reset_index().assign(**{c: 0.0 for c in FEATS})
    base_p = service.predict(frame, state, rows).iloc[0]["p_g2h"]
    flipped = rows.assign(away_conference="Big 12" if rows.iloc[0]["away_conference"] != "Big 12" else "SEC")
    assert service.predict(frame, state, flipped).iloc[0]["p_g2h"] != base_p   # G2h uses the conference inputs


def test_an_inconsistent_board_is_unverified_so_the_slate_is_unavailable(boards):
    now = KICK - dt.timedelta(minutes=60)
    window_board(boards, now, [])
    broken = {"id": "7777", "date": KICK.isoformat(), "season": {"year": 2026}, "competitions": [{"competitors": []}]}
    boards[(now).strftime("%Y%m%d")].append(broken)
    with pytest.raises(runner.SlateUnavailable, match="no home and away"):
        runner.fetch_slate(days=10, now=now)


def test_a_suspended_game_that_resumes_before_kickoff_can_lock_again(con):
    observe(con, GAME, KICK, NOW_EARLY)
    observe(con, GAME, KICK, NOW_WINDOW - dt.timedelta(minutes=20), lifecycle="suspended", status_name="STATUS_SUSPENDED")
    assert store.lock_forecasts(con, [lock_row(GAME, KICK)], now=NOW_WINDOW)["blocked_status"] == 1
    observe(con, GAME, KICK, NOW_WINDOW - dt.timedelta(minutes=5), lifecycle="scheduled")
    report = store.lock_forecasts(con, [lock_row(GAME, KICK)], now=NOW_WINDOW)
    assert report["inserted"] == 1


# ------------------------------------------------------------- atomic forecast writes and lock risk

def durable_state(db):
    """Every fbs_ table's rows, except the run log, which records the failure itself by design."""
    con = store.open_db(db, readonly=True)
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fbs_%' AND name <> 'fbs_run_reports'")]
        return {name: sorted(repr(tuple(r)) for r in con.execute("SELECT * FROM %s" % name).fetchall())
                for name in names}
    finally:
        con.close()


def test_a_failure_partway_through_a_forecast_write_leaves_every_table_as_it_was(tmp_path, forecast_env, boards,
                                                                                  monkeypatch):
    db = str(tmp_path / "rollback.sqlite3")
    now = KICK - dt.timedelta(minutes=60)
    window_board(boards, now, [board_event(GAME, KICK.isoformat(), "STATUS_SCHEDULED", False)])
    con = open_scratch(db)
    observe(con, GAME, KICK + dt.timedelta(hours=3), NOW_EARLY)     # the board moves the kickoff: a new revision
    con.close()
    before = durable_state(db)

    real_lock = runner.store.lock_forecasts

    def lock_then_fail(con_arg, rows, now=None, commit=True):
        real_lock(con_arg, rows, now=now, commit=commit)            # locks and previews are already written
        raise RuntimeError("injected failure after the lock write")
    monkeypatch.setattr(runner.store, "lock_forecasts", lock_then_fail)

    report = runner.run(days=10, db_path=db, now=now)
    assert report["forecast"]["status"] == "rolled_back"
    assert "injected failure" in report["forecast"]["error"]
    assert durable_state(db) == before

    con = store.open_db(db, readonly=True)
    assert con.execute("SELECT status FROM fbs_run_reports WHERE subsystem = 'forecast' ORDER BY id DESC LIMIT 1").fetchone()[0] == "rolled_back"
    con.close()

    monkeypatch.setattr(runner.store, "lock_forecasts", real_lock)
    recovered = runner.run(days=10, db_path=db, now=now)
    assert recovered["forecast"]["status"] == "ok"
    assert recovered["locked"]["inserted"] == len(runner.MODEL_ORDER)
    con = store.open_db(db, readonly=True)
    assert con.execute("SELECT revision FROM fbs_fixture_revisions WHERE game_id=? ORDER BY revision DESC LIMIT 1",
                       (GAME,)).fetchone()[0] == 2
    con.close()


def test_an_unmapped_pregame_status_is_a_lock_risk_at_once_and_is_queued(tmp_path, forecast_env, boards):
    db = str(tmp_path / "unmapped.sqlite3")
    open_scratch(db).close()
    now = KICK - dt.timedelta(minutes=60)
    window_board(boards, now, [board_event(GAME, KICK.isoformat(), "STATUS_UNRECOGNISED", False)])
    report = runner.run(days=10, db_path=db, now=now)
    assert report["forecast"]["status"] == "ok"
    assert report["locked"]["inserted"] == 0
    assert GAME in report["forecast"]["lock_risk"]
    con = store.open_db(db, readonly=True)
    queued = [dict(r) for r in store.unresolved_queue(con) if r["game_id"] == GAME]
    con.close()
    assert len(queued) == 1 and queued[0]["alert_state"] == "lock_risk"


def test_a_scheduled_game_that_leaves_the_board_is_unverified_but_one_beyond_it_is_untouched(tmp_path, forecast_env,
                                                                                            boards):
    db = str(tmp_path / "absent.sqlite3")
    now = KICK - dt.timedelta(minutes=60)
    far = KICK + dt.timedelta(days=20)                                 # beyond the board this run fetches
    con = open_scratch(db)
    observe(con, GAME, KICK, NOW_EARLY)
    observe(con, "far", far, NOW_EARLY)
    con.close()
    window_board(boards, now, [board_event("other", KICK.isoformat(), "STATUS_SCHEDULED", False,
                                           home=("2001", "Other U"), away=("2002", "Other State"))])
    report = runner.run(days=10, db_path=db, now=now)
    assert report["forecast"]["status"] == "ok"
    con = store.open_db(db, readonly=True)
    status = {r["game_id"]: dict(r) for r in con.execute("SELECT * FROM fbs_game_status")}
    queued = {r["game_id"]: r["alert_state"] for r in store.unresolved_queue(con)}
    con.close()
    assert status[GAME]["lifecycle"] == "unknown" and status[GAME]["reason"] == "absent_from_board"
    assert queued[GAME] == "lock_risk"
    assert status["far"]["lifecycle"] == "scheduled" and "far" not in queued


def test_a_slate_outage_raises_a_lock_risk_for_each_scheduled_game_due_within_a_day(tmp_path, forecast_env, boards):
    db = str(tmp_path / "outage-risk.sqlite3")
    now = KICK - dt.timedelta(minutes=60)
    con = open_scratch(db)
    observe(con, GAME, KICK, NOW_EARLY)
    observe(con, "later", KICK + dt.timedelta(days=3), NOW_EARLY)
    con.close()
    report = runner.run(days=10, db_path=db, now=now)                  # the current board is not stubbed
    assert report["forecast"]["status"] == "slate_unavailable"
    assert GAME in report["forecast"]["lock_risk"] and "later" not in report["forecast"]["lock_risk"]
    con = store.open_db(db, readonly=True)
    queued = {r["game_id"]: r["alert_state"] for r in store.unresolved_queue(con)}
    con.close()
    assert queued[GAME] == "lock_risk" and "later" not in queued



# ----------------------------------------------------------- Eastern capture: dates, horizon, duplicates

UTC = dt.timezone.utc


def _slate_row(game_id, kickoff, lifecycle="scheduled", season=2026, season_type=2, week=8, home="1", away="2"):
    return dict(game_id=game_id, kickoff_utc=pd.Timestamp(kickoff), lifecycle=lifecycle, status_name="STATUS",
                season=season, season_type=season_type, week=week, home_team_id=home, away_team_id=away,
                home_team="H", away_team="A", neutral_site=False, home_score=None, away_score=None,
                completed=False)


def test_scoreboard_dates_are_eastern_and_cover_the_whole_horizon():
    now = dt.datetime(2026, 10, 25, 0, 30, tzinfo=UTC)                  # 20:30 EDT on Oct 24
    dates = runner.scoreboard_dates(now, 10)
    assert dates == ["202610%02d" % d for d in range(23, 32)] + ["202611%02d" % d for d in range(1, 4)]


def test_daylight_saving_change_does_not_skip_or_repeat_an_eastern_date():
    now = dt.datetime(2026, 11, 1, 0, 30, tzinfo=UTC)                  # 20:30 EDT on Oct 31; clocks change that morning
    assert runner.scoreboard_dates(now, 3) == ["20261030", "20261031", "20261101", "20261102", "20261103"]


def test_a_10pm_eastern_game_is_requested_when_its_t90_window_opens_after_utc_midnight(monkeypatch):
    now = dt.datetime(2026, 10, 25, 0, 30, tzinfo=UTC)                  # T-90 of a 22:00 EDT kickoff opens here
    kickoff = dt.datetime(2026, 10, 25, 2, 0, tzinfo=UTC)               # 22:00 EDT, Oct 24
    boards = {"20261024": [board_event("late", kickoff.isoformat(), "STATUS_SCHEDULED", False)]}
    monkeypatch.setattr(runner, "read_scoreboard", lambda date: {"events": boards.get(date, [])})
    monkeypatch.setattr(runner, "BOARD_PACE_SECONDS", 0)
    slate = runner.fetch_slate(days=10, now=now)
    assert slate["game_id"].tolist() == ["late"]
    assert "20261024" in slate.attrs["requested_dates"]


def test_a_standard_time_22_00_game_is_captured_at_its_t90_window_across_utc_midnight(monkeypatch):
    now = dt.datetime(2027, 1, 3, 1, 30, tzinfo=UTC)                    # 20:30 EST on Jan 2
    kickoff = dt.datetime(2027, 1, 3, 3, 0, tzinfo=UTC)                 # 22:00 EST, Jan 2 (a bowl Eve)
    assert runner.eastern_date(kickoff.isoformat()) == "20270102"
    assert "20270102" in runner.scoreboard_dates(now, 10)


def test_midnight_in_each_timezone_belongs_to_the_right_eastern_date():
    assert runner.eastern_date("2026-10-25T04:00:00Z") == "20261025"    # 00:00 EDT, Oct 25
    assert runner.eastern_date("2026-10-25T00:00:00Z") == "20261024"    # 20:00 EDT, Oct 24
    now = dt.datetime(2026, 10, 24, 23, 0, tzinfo=UTC)                   # 19:00 EDT, Oct 24
    assert "20261025" in runner.scoreboard_dates(now, 10)


def test_only_games_kicking_off_strictly_after_now_inside_the_horizon_get_a_new_forecast():
    now = dt.datetime(2026, 10, 24, 15, 0, tzinfo=UTC)                  # 11:00 EDT, Oct 24
    end = runner.forecast_horizon_end(now, 10)
    assert end == dt.datetime(2026, 11, 4, 5, 0, tzinfo=UTC)            # midnight EST, Nov 4: after the Nov 3 date
    slate = pd.DataFrame([
        _slate_row("at-now", now),
        _slate_row("one-second-after", now + dt.timedelta(seconds=1)),
        _slate_row("one-second-before-end", end - dt.timedelta(seconds=1)),
        _slate_row("at-end", end),
        _slate_row("postponed", now + dt.timedelta(days=1), lifecycle="postponed"),
        _slate_row("wrong-season", now + dt.timedelta(hours=2), season=2025),
        _slate_row("no-type", now + dt.timedelta(hours=3), season_type=None),
    ])
    candidates, reasons = runner.forecast_candidates(slate, now, 10)
    assert sorted(candidates["game_id"]) == ["one-second-after", "one-second-before-end"]
    assert reasons == {"started": ["at-now"], "beyond_horizon": ["at-end"],
                       "not_scheduled:postponed": ["postponed"], "season_contradicted": ["wrong-season"],
                       "season_type_missing": ["no-type"]}


def test_the_horizon_is_the_whole_eastern_day_including_saturday_october_31():
    now = dt.datetime(2026, 10, 21, 5, 15, 38, tzinfo=UTC)              # 01:15 EDT, Oct 21: the reported dry run
    end = runner.forecast_horizon_end(now, 10)
    assert end == dt.datetime(2026, 11, 1, 4, 0, tzinfo=UTC)            # Nov 1 00:00 EDT
    slate = pd.DataFrame([
        _slate_row("sat-1600z", dt.datetime(2026, 10, 31, 16, 0, tzinfo=UTC)),
        _slate_row("sat-late", dt.datetime(2026, 11, 1, 3, 59, tzinfo=UTC)),       # 23:59 EDT, Oct 31
        _slate_row("sun-midnight", dt.datetime(2026, 11, 1, 4, 0, tzinfo=UTC)),    # 00:00 EDT, Nov 1
    ])
    candidates, reasons = runner.forecast_candidates(slate, now, 10)
    assert sorted(candidates["game_id"]) == ["sat-1600z", "sat-late"]
    assert reasons == {"beyond_horizon": ["sun-midnight"]}
    assert runner.scoreboard_dates(now, 10)[-1] == "20261031"


def test_the_horizon_ends_on_an_eastern_midnight_on_both_sides_of_the_daylight_saving_change():
    before = runner.forecast_horizon_end(dt.datetime(2026, 10, 28, 16, 0, tzinfo=UTC), 10)
    after = runner.forecast_horizon_end(dt.datetime(2026, 10, 25, 0, 30, tzinfo=UTC), 10)
    assert before == dt.datetime(2026, 11, 8, 5, 0, tzinfo=UTC)         # Nov 7 is EST: midnight is 05:00 UTC
    assert after == dt.datetime(2026, 11, 4, 5, 0, tzinfo=UTC)
    slate = pd.DataFrame([_slate_row("dst-side-in", before - dt.timedelta(seconds=1)),
                          _slate_row("dst-side-out", before)])
    candidates, _ = runner.forecast_candidates(slate, dt.datetime(2026, 10, 28, 16, 0, tzinfo=UTC), 10)
    assert candidates["game_id"].tolist() == ["dst-side-in"]
def test_a_game_copied_onto_two_boards_is_kept_once_and_reported(monkeypatch):
    now = dt.datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    event = board_event("dup", "2026-10-24T16:00Z", "STATUS_SCHEDULED", False)
    boards = {"20261023": [event], "20261024": [dict(event)]}
    monkeypatch.setattr(runner, "read_scoreboard", lambda date: {"events": boards.get(date, [])})
    monkeypatch.setattr(runner, "BOARD_PACE_SECONDS", 0)
    slate = runner.fetch_slate(days=1, now=now)
    assert slate["game_id"].tolist() == ["dup"]
    assert slate.attrs["duplicates"] == ["dup"]


@pytest.mark.parametrize("change", ["kickoff", "status", "season"])
def test_copies_of_one_event_that_disagree_make_the_slate_unverified(monkeypatch, change):
    now = dt.datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    first = board_event("clash", "2026-10-24T16:00Z", "STATUS_SCHEDULED", False)
    second = board_event("clash", "2026-10-24T16:00Z", "STATUS_SCHEDULED", False)
    if change == "kickoff":
        second["date"] = "2026-10-24T17:00Z"
    elif change == "status":
        second["competitions"][0]["status"]["type"]["name"] = "STATUS_IN_PROGRESS"
    else:
        second["season"] = {"year": 2025, "type": 2}
    boards = {"20261023": [first], "20261024": [second]}
    monkeypatch.setattr(runner, "read_scoreboard", lambda date: {"events": boards.get(date, [])})
    monkeypatch.setattr(runner, "BOARD_PACE_SECONDS", 0)
    with pytest.raises(runner.SlateUnavailable, match="differs between scoreboard copies"):
        runner.fetch_slate(days=1, now=now)


def test_an_event_without_an_espn_season_makes_the_slate_unverified(monkeypatch):
    now = dt.datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    event = board_event("nosea", "2026-10-24T16:00Z", "STATUS_SCHEDULED", False)
    del event["season"]
    boards = {"20261024": [event]}
    monkeypatch.setattr(runner, "read_scoreboard", lambda date: {"events": boards.get(date, [])})
    monkeypatch.setattr(runner, "BOARD_PACE_SECONDS", 0)
    with pytest.raises(runner.SlateUnavailable, match="has no season"):
        runner.fetch_slate(days=1, now=now)


def test_a_started_game_is_observed_but_never_previewed_or_locked(tmp_path, forecast_env, boards):
    db = str(tmp_path / "started.sqlite3")
    open_scratch(db).close()
    now = KICK + dt.timedelta(minutes=30)
    window_board(boards, now, [board_event(GAME, KICK.isoformat(), "STATUS_IN_PROGRESS", False)])
    report = runner.run(days=10, db_path=db, now=now)
    assert report["forecast"]["status"] == "ok"
    assert report["previewed"] == 0 and report["locked"].get("inserted", 0) == 0
    con = store.open_db(db, readonly=True)
    assert con.execute("SELECT lifecycle FROM fbs_game_status WHERE game_id=?", (GAME,)).fetchone()[0] == "in_progress"
    assert con.execute("SELECT COUNT(*) FROM fbs_previews").fetchone()[0] == 0
    con.close()


def test_a_season_that_contradicts_its_kickoff_is_unverified_and_queued(tmp_path, forecast_env, boards):
    db = str(tmp_path / "contradicted.sqlite3")
    open_scratch(db).close()
    now = KICK - dt.timedelta(minutes=60)
    window_board(boards, now, [board_event(GAME, KICK.isoformat(), "STATUS_SCHEDULED", False, season=2025)])
    report = runner.run(days=10, db_path=db, now=now)
    assert report["forecast"]["status"] == "ok"
    assert report["previewed"] == 0 and report["locked"].get("inserted", 0) == 0
    assert GAME in report["forecast"]["lock_risk"]
    assert GAME in report["forecast"]["excluded"]["season_contradicted"]
    con = store.open_db(db, readonly=True)
    assert con.execute("SELECT reason FROM fbs_game_status WHERE game_id=?", (GAME,)).fetchone()[0] == "season_contradicted"
    con.close()


def test_the_cli_refuses_an_unmigrated_database_and_leaves_its_bytes_alone(tmp_path, forecast_env, boards):
    db = str(tmp_path / "legacy" / "fbs-model.dev.sqlite3")
    os.makedirs(os.path.dirname(db))
    raw = sqlite3.connect(db)
    raw.executescript("CREATE TABLE fbs_forecasts (game_id TEXT, model TEXT, p_home REAL);")
    raw.commit()
    raw.close()
    before = open(db, "rb").read()
    assert runner.main(["--run", "--db", db]) == 5
    assert open(db, "rb").read() == before


# ----------------------------------------------- season attribution: ESPN season, not the kickoff's year

def test_a_january_bowl_uses_its_espn_season_and_that_seasons_conferences(monkeypatch):
    frame = pd.concat([synthetic_frame(season=2025), synthetic_frame(season=2026)], ignore_index=True)
    for side in ("home", "away"):
        frame.loc[(frame.season == 2026) & (frame[side + "_team_id"] == "100"), side + "_conference"] = "Big Ten"
    label_2025 = runner._current_fbs_team_conferences(frame, 2025)["100"]
    history = elo_history()
    captured = {}
    real_predictions = runner.base.make_predictions

    def spy(combined, first_season):
        captured["combined"] = combined.copy()
        return real_predictions(combined, first_season)

    monkeypatch.setattr(runner.base, "load_events", lambda data_dir, seasons: (history.copy(), None, None, None))
    monkeypatch.setattr(runner.base, "make_predictions", spy)
    teams = dict(home_team_id="100", away_team_id="101", home_team="Team 0", away_team="Team 1", week=1, season_type=3,
                 neutral_site=True)
    slate = pd.DataFrame([dict(game_id="B26", kickoff_utc=pd.Timestamp("2027-01-02T20:00Z"), season=2026, **teams),
                          dict(game_id="B25", kickoff_utc=pd.Timestamp("2026-01-02T20:00Z"), season=2025, **teams)])
    runner.g2_for_slate(frame, slate)
    events = captured["combined"].set_index("game_id")
    assert int(events.loc["B26", "season"]) == 2026
    assert events.loc["B26", "home_conference"] == "Big Ten"
    assert int(events.loc["B25", "season"]) == 2025
    assert events.loc["B25", "home_conference"] == label_2025


def test_a_team_that_changes_conference_is_labelled_by_the_season_of_the_game(monkeypatch):
    frame = pd.concat([synthetic_frame(season=2025), synthetic_frame(season=2026)], ignore_index=True)
    frame.loc[(frame.season == 2026) & (frame.home_team_id == "100"), "home_conference"] = "Big Ten"
    frame.loc[(frame.season == 2026) & (frame.away_team_id == "100"), "away_conference"] = "Big Ten"
    assert runner._current_fbs_team_conferences(frame, 2026)["100"] == "Big Ten"
    assert runner._current_fbs_team_conferences(frame, 2025)["100"] != "Big Ten"


def test_team_ratings_are_only_reported_for_a_season_the_fit_has(monkeypatch):
    class Hier:
        ts_index = {(2025, "1"): 0}
        u = np.array([0.1])
        m = np.array([0.0])
        conf_index = {"SEC": 0}
    frame = synthetic_frame(season=2025)
    state = {"g2h": Hier()}
    assert runner.team_ratings(state, frame, 2026) == []
    assert [r["season"] for r in runner.team_ratings(state, frame, 2025)] == [2025]


def test_an_unfitted_team_season_or_conference_is_reported_not_silently_zeroed():
    class Hier:
        ts_index = {(2025, "1"): 0}
        conf_index = {"SEC": 0}
    scored = pd.DataFrame([dict(game_id="G", season=2026, home_team_id="1", away_team_id="2",
                                home_conference="SEC", away_conference="Big Ten")])
    reasons = {(g["team_id"], g["reason"]) for g in runner.g2h_effect_gaps({"g2h": Hier()}, scored)}
    assert reasons == {("1", "team_season_unfitted"), ("2", "team_season_unfitted"), ("2", "conference_unfitted")}


# ------------------------------------------- as-of features: the live slate must match the research definition

TEAMS = ("1", "2", "3", "4")


def _team_rows(game_id, home, away, season, week, rng):
    out = []
    for team in (home, away):
        row = {"game_id": game_id, "pos_team": team, "season": season, "week": week,
               "off_plays": float(rng.integers(40, 80)), "def_plays": float(rng.integers(40, 80))}
        row.update({m: float(rng.normal(0.5, 0.2)) for m in runner.feat_c.METRIC_COLS_C})
        out.append(row)
    return out


def _history(seasons=(2025,), weeks=4, seed=5):
    rng = np.random.default_rng(seed)
    rows, games = [], []
    for season in seasons:
        for week in range(1, weeks + 1):
            pairs = [(TEAMS[0], TEAMS[1]), (TEAMS[2], TEAMS[3])] if week % 2 else [(TEAMS[0], TEAMS[2]), (TEAMS[1], TEAMS[3])]
            for i, (home, away) in enumerate(pairs):
                game_id = "%d%02d%d" % (season, week, i)
                date = pd.Timestamp("%d-08-30" % season) + pd.Timedelta(days=7 * (week - 1) + i)
                games.append(dict(game_id=game_id, utc_date=date, y=float(rng.integers(0, 2)), season=season, week=week))
                rows += _team_rows(game_id, home, away, season, week, rng)
    return pd.DataFrame(rows), pd.DataFrame(games)


CAND = "candidate"


def _research_diffs(history, home, away, season, placed_week):
    """The research recurrence's own value for a game at this placement, with the game appended as the training
    path would hold it. Its emitted row is the state before that game: the as-of definition under test."""
    rng = np.random.default_rng(99)
    full = pd.concat([history, pd.DataFrame(_team_rows(CAND, home, away, season, placed_week, rng))],
                     ignore_index=True)
    ratings = runner.feat_base.build_team_ratings(full, runner.feat_c.METRIC_COLS_C)
    rows = {side: ratings[(ratings.game_id == CAND) & (ratings.pos_team == team)].iloc[0]
            for side, team in (("home", home), ("away", away))}
    out = {}
    for name, metric in runner.SLATE_METRICS.items():
        out[name] = ((rows["home"]["off_" + metric] + rows["away"]["def_" + metric])
                     - (rows["away"]["off_" + metric] + rows["home"]["def_" + metric]))
    return out


def _slate_diffs(history, games, home, away, season, week, season_type, kickoff, now):
    candidate = pd.DataFrame([dict(game_id=CAND, home_team_id=home, away_team_id=away, season=season,
                                   season_type=season_type, week=week, kickoff_utc=pd.Timestamp(kickoff))])
    frame = games.assign(game_id=games["game_id"].astype(str))[["game_id", "utc_date", "y"]]
    return runner.slate_features(history, frame, candidate, now).iloc[0]


def _assert_matches(research, slate):
    for name in runner.SLATE_METRICS:
        assert slate[name] == pytest.approx(research[name], abs=1e-12), name


def test_a_regular_season_slate_game_gets_exactly_the_research_as_of_features():
    history, games = _history(weeks=4)
    history, games = history[history.week < 3], games[games.week < 3]        # only games before week 3
    kickoff = pd.Timestamp("2025-09-20T16:00Z")
    now = dt.datetime(2025, 9, 19, 12, 0, tzinfo=UTC)
    research = _research_diffs(history, "1", "2", 2025, 3)
    slate = _slate_diffs(history, games, "1", "2", 2025, 3, 2, kickoff, now)
    _assert_matches(research, slate)
    assert not slate["home_prior_season_only"] and not slate["away_no_history"]


def test_a_season_opener_uses_the_prior_season_explicitly_and_matches_the_research_as_of():
    history, games = _history(seasons=(2025,), weeks=4)                    # no 2026 history at all
    now = dt.datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    research = _research_diffs(history, "1", "2", 2026, 1)
    slate = _slate_diffs(history, games, "1", "2", 2026, 1, 2, pd.Timestamp("2026-08-29T16:00Z"), now)
    _assert_matches(research, slate)
    assert slate["home_prior_season_only"] and slate["away_prior_season_only"]
    assert not slate["home_no_history"]


def test_a_missing_current_season_pbp_is_prior_season_carry_over_not_an_error():
    history, games = _history(seasons=(2025,), weeks=4)
    now = dt.datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    slate = _slate_diffs(history, games, "2", "3", 2026, 3, 2, pd.Timestamp("2026-09-15T16:00Z"), now)
    assert slate["feature_season"] == 2026 and slate["home_prior_season_only"]


def test_a_january_bowl_uses_the_whole_regular_season_not_its_week_one_ordering():
    history, games = _history(seasons=(2025,), weeks=4)
    now = dt.datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    kickoff = pd.Timestamp("2026-01-02T20:00Z")
    research = _research_diffs(history, "1", "3", 2025, 5)                  # max regular week 4, placed after it
    slate = _slate_diffs(history, games, "1", "3", 2025, 1, 3, kickoff, now)  # ESPN week 1 for every bowl
    _assert_matches(research, slate)
    stale = _research_diffs(history, "1", "3", 2025, 1)                     # the ordering the source would imply
    assert any(abs(stale[n] - slate[n]) > 1e-9 for n in runner.SLATE_METRICS)


def test_a_team_with_no_history_is_flagged_and_takes_the_league_mean():
    history, games = _history(seasons=(2025,), weeks=4)
    now = dt.datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    research = _research_diffs(history, "9", "1", 2026, 1)
    slate = _slate_diffs(history, games, "9", "1", 2026, 1, 2, pd.Timestamp("2026-08-29T16:00Z"), now)
    _assert_matches(research, slate)
    assert slate["home_no_history"] and not slate["home_has_history"]


def test_history_that_runs_past_now_is_refused_rather_than_used():
    history, games = _history(seasons=(2025,), weeks=4)
    games = games.copy()
    games.loc[games.index[-1], "utc_date"] = pd.Timestamp("2026-09-20")
    now = dt.datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    with pytest.raises(service.FBSModelError, match="runs past now"):
        _slate_diffs(history, games, "1", "2", 2026, 1, 2, pd.Timestamp("2026-09-21T16:00Z"), now)


def test_a_10pm_eastern_game_is_locked_by_a_full_run_when_its_t90_window_opens_after_utc_midnight(
        tmp_path, forecast_env, boards):
    db = str(tmp_path / "late-et.sqlite3")
    open_scratch(db).close()
    kickoff = dt.datetime(2026, 10, 25, 2, 0, tzinfo=UTC)                 # 22:00 EDT, Oct 24
    now = dt.datetime(2026, 10, 25, 0, 30, tzinfo=UTC)                    # exactly T-90
    window_board(boards, now, [board_event(GAME, kickoff.isoformat(), "STATUS_SCHEDULED", False)])
    report = runner.run(days=10, db_path=db, now=now)
    assert report["forecast"]["status"] == "ok"
    assert GAME in report["forecast"]["forecast_games"]
    assert report["locked"]["inserted"] == len(runner.MODEL_ORDER)


def test_the_fit_never_uses_an_outcome_at_or_after_its_cutoff():
    frame = synthetic_frame(season=2025, n=800)                          # dates run past the cutoff below
    cutoff = pd.Timestamp("2026-01-15")
    before = int((frame["utc_date"] < cutoff).sum())
    assert 0 < before < len(frame)
    state = service.fit(frame, cutoff.to_pydatetime().replace(tzinfo=UTC))
    assert state["train_games"] == before
    assert state["train_last_date"] < cutoff


def test_a_postseason_game_is_previewed_but_never_locked_until_bowl_ordering_is_decided(tmp_path, forecast_env, boards):
    db = str(tmp_path / "bowl.sqlite3")
    open_scratch(db).close()
    now = KICK - dt.timedelta(minutes=60)
    window_board(boards, now, [board_event(GAME, KICK.isoformat(), "STATUS_SCHEDULED", False, season_type=3)])
    report = runner.run(days=10, db_path=db, now=now)
    assert report["forecast"]["status"] == "ok"
    assert report["previewed"] == len(runner.MODEL_ORDER)
    assert report["forecast"]["postseason_research_hold"] == [GAME]
    assert report["locked"].get("inserted", 0) == 0


# ------------------------------------- postseason research holds: durable, classified after kickoff, never missed

def _postseason_preview(con, game_id, now, kickoff, hold=True):
    """A pregame observation of a postseason game and its previews, the way a run writes them."""
    rec = dict(game_id=game_id, season=2026, kickoff_utc=kickoff.isoformat(), home_team="H", away_team="A",
               home_team_id="1", away_team_id="2", neutral_site=True, season_type=3)
    obs = store.observe_fixture(con, rec, now, "test")
    store.set_game_status(con, game_id, 2026, obs["revision"], "scheduled", "STATUS_SCHEDULED", now.isoformat(),
                          "test", "pending", None)
    if hold:
        store.set_postseason_hold(con, game_id)
    store.upsert_previews(con, [dict(game_id=game_id, model=m, season=2026, kickoff_utc=kickoff.isoformat(),
                                     home_team="H", away_team="A", home_team_id="1", away_team_id="2",
                                     model_version="v", p_home=0.55, fitted_through="2026-10-20",
                                     hold_reason=store.POSTSEASON_HOLD if hold else None)
                           for m in ("g2", "c2", "g2h")], now=now)


def test_a_held_postseason_preview_is_window_not_eligible_after_kickoff_and_never_missed(tmp_path):
    con = open_scratch(str(tmp_path / "held.sqlite3"))
    kickoff = dt.datetime(2027, 1, 2, 20, 0, tzinfo=UTC)
    _postseason_preview(con, "bowl", kickoff - dt.timedelta(days=2), kickoff)
    counts = store.record_missed_windows(con, now=kickoff + dt.timedelta(hours=1))
    assert counts == {"missed_t90_window": 0, "blocked_unverified_at_cutoff": 0, "window_not_eligible": 3}
    rows = con.execute("SELECT outcome, reason FROM fbs_window_outcomes").fetchall()
    assert {tuple(r) for r in rows} == {("window_not_eligible", store.POSTSEASON_HOLD)}


def test_without_the_hold_the_same_unlocked_bowl_would_be_a_missed_window(tmp_path):
    con = open_scratch(str(tmp_path / "unheld.sqlite3"))
    kickoff = dt.datetime(2027, 1, 2, 20, 0, tzinfo=UTC)
    _postseason_preview(con, "bowl", kickoff - dt.timedelta(days=2), kickoff, hold=False)
    counts = store.record_missed_windows(con, now=kickoff + dt.timedelta(hours=1))
    assert counts["missed_t90_window"] == 3


@pytest.mark.parametrize("later", [
    ("STATUS_IN_PROGRESS", "in_progress", False),
    ("STATUS_FINAL", "completed", True),
    ("STATUS_POSTPONED", "postponed", False),
    ("STATUS_CANCELED", "cancelled", False),
    ("STATUS_UNRECOGNISED", "unknown", False),
])
def test_the_postseason_hold_survives_every_later_status_change(tmp_path, later):
    con = open_scratch(str(tmp_path / "later.sqlite3"))
    kickoff = dt.datetime(2027, 1, 2, 20, 0, tzinfo=UTC)
    _postseason_preview(con, "bowl", kickoff - dt.timedelta(days=2), kickoff)
    name, lifecycle, completed = later
    rec = dict(game_id="bowl", season=2026, kickoff_utc=kickoff.isoformat(), home_team="H", away_team="A",
               home_team_id="1", away_team_id="2", neutral_site=True, season_type=3)
    obs = store.observe_fixture(con, rec, kickoff + dt.timedelta(hours=3), "test")
    store.set_game_status(con, "bowl", 2026, obs["revision"], lifecycle, name, (kickoff + dt.timedelta(hours=3)).isoformat(),
                          "test", "graded" if completed else "pending", None)
    store.upsert_previews(con, [], now=kickoff - dt.timedelta(days=1))           # a later run writes no new rows
    assert store.game_status(con, "bowl")["hold_reason"] == store.POSTSEASON_HOLD
    counts = store.record_missed_windows(con, now=kickoff + dt.timedelta(hours=4))
    assert counts["missed_t90_window"] == 0 and counts["window_not_eligible"] == 3


def test_a_postseason_preview_is_held_through_kickoff_and_final_results_in_a_real_run(tmp_path, forecast_env, boards):
    db = str(tmp_path / "bowl-run.sqlite3")
    open_scratch(db).close()
    now = KICK - dt.timedelta(minutes=60)
    window_board(boards, now, [board_event(GAME, KICK.isoformat(), "STATUS_SCHEDULED", False, season_type=3)])
    before = runner.run(days=10, db_path=db, now=now)
    assert before["previewed"] == len(runner.MODEL_ORDER) and before["locked"].get("inserted", 0) == 0
    boards.clear()
    window_board(boards, KICK + dt.timedelta(hours=1),
                 [board_event(GAME, KICK.isoformat(), "STATUS_IN_PROGRESS", False, 7, 3, season_type=3)])
    after = runner.run(days=10, db_path=db, now=KICK + dt.timedelta(hours=1))
    boards.clear()
    window_board(boards, KICK + dt.timedelta(hours=3),
                 [board_event(GAME, KICK.isoformat(), "STATUS_FINAL", True, 24, 20, season_type=3)])
    final = runner.run(days=10, db_path=db, now=KICK + dt.timedelta(hours=3))
    assert final["missed"]["missed_t90_window"] == 0
    assert after["previewed"] == 0                             # started games receive no new preview
    con = store.open_db(db, readonly=True)
    rows = con.execute("SELECT outcome, reason FROM fbs_window_outcomes").fetchall()
    con.close()
    assert len(rows) == 3 and {tuple(r) for r in rows} == {("window_not_eligible", store.POSTSEASON_HOLD)}
    assert after["forecast"]["status"] == final["forecast"]["status"] == "ok"


def test_a_postseason_event_keeps_its_espn_season_type_and_phase_and_g2_does_not_depend_on_it(monkeypatch):
    history = elo_history()
    captured = {}
    real_predictions = runner.base.make_predictions

    def spy(combined, first_season):
        captured["combined"] = combined.copy()
        return real_predictions(combined, first_season)

    monkeypatch.setattr(runner.base, "load_events", lambda data_dir, seasons: (history.copy(), None, None, None))
    monkeypatch.setattr(runner.base, "make_predictions", spy)
    frame = synthetic_frame(season=2026)
    kick = pd.Timestamp("2027-01-02T20:00Z")
    teams = dict(home_team_id="100", away_team_id="101", home_team="Team 0", away_team="Team 1", week=1,
                 neutral_site=True, kickoff_utc=kick, season=2026)
    slate = pd.DataFrame([dict(game_id="BOWL", season_type=3, **teams), dict(game_id="REG", season_type=2, **teams)])
    scored = runner.g2_for_slate(frame, slate).set_index("game_id")
    events = captured["combined"].set_index("game_id")
    assert events.loc["BOWL", "season_type"] == "postseason" and events.loc["BOWL", "game_phase"] == "Postseason"
    assert events.loc["REG", "season_type"] == "regular" and events.loc["REG", "game_phase"] == "Regular season"
    assert float(scored.loc["BOWL", "p_g2"]) == float(scored.loc["REG", "p_g2"])     # the Elo baseline ignores phase


# ----------------------------------------- duplicate copies: every forecast-driving field must agree

def _two_copies(monkeypatch, first, second):
    now = dt.datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    boards = {"20261023": [first], "20261024": [second]}
    monkeypatch.setattr(runner, "read_scoreboard", lambda date: {"events": boards.get(date, [])})
    monkeypatch.setattr(runner, "BOARD_PACE_SECONDS", 0)
    return runner.fetch_slate(days=1, now=now)


@pytest.mark.parametrize("change, value", [
    ("neutral", True), ("season_type", 3), ("week", 9), ("home_team", "Other Team"),
    ("kickoff", "2026-10-24T17:00Z"), ("status", "STATUS_IN_PROGRESS"), ("season", 2025),
])
def test_copies_of_one_event_that_disagree_on_any_forecast_field_fail_closed(monkeypatch, change, value):
    first = board_event("clash", "2026-10-24T16:00Z", "STATUS_SCHEDULED", False)
    second = board_event("clash", "2026-10-24T16:00Z", "STATUS_SCHEDULED", False)
    if change == "neutral":
        second["competitions"][0]["neutralSite"] = value
    elif change == "season_type":
        second["season"]["type"] = value
    elif change == "week":
        second["week"] = {"number": value}
    elif change == "home_team":
        second["competitions"][0]["competitors"][0]["team"]["displayName"] = value
    elif change == "kickoff":
        second["date"] = value
    elif change == "status":
        second["competitions"][0]["status"]["type"]["name"] = value
    else:
        second["season"] = {"year": value, "type": 2}
    with pytest.raises(runner.SlateUnavailable, match="differs between scoreboard copies"):
        _two_copies(monkeypatch, first, second)


def test_identical_copies_are_kept_once_and_a_live_score_difference_is_the_source_exception(monkeypatch):
    first = board_event("live", "2026-10-24T16:00Z", "STATUS_IN_PROGRESS", False, 7, 3)
    second = board_event("live", "2026-10-24T16:00Z", "STATUS_IN_PROGRESS", False, 10, 3)
    slate = _two_copies(monkeypatch, first, second)
    assert slate["game_id"].tolist() == ["live"] and slate.attrs["duplicates"] == ["live"]


def test_final_scores_that_disagree_between_copies_fail_closed(monkeypatch):
    first = board_event("final", "2026-10-24T16:00Z", "STATUS_FINAL", True, 24, 20)
    second = board_event("final", "2026-10-24T16:00Z", "STATUS_FINAL", True, 24, 21)
    with pytest.raises(runner.SlateUnavailable, match="home_score|away_score"):
        _two_copies(monkeypatch, first, second)


def test_a_completion_flag_that_disagrees_between_copies_fails_closed(monkeypatch):
    first = board_event("done", "2026-10-24T16:00Z", "STATUS_IN_PROGRESS", False, 24, 20)
    second = board_event("done", "2026-10-24T16:00Z", "STATUS_FINAL", True, 24, 20)
    with pytest.raises(runner.SlateUnavailable, match="completed|status_name|lifecycle"):
        _two_copies(monkeypatch, first, second)


# ------------------------------------------------------------------ audit: schema-aware, read-only, byte-stable

def _legacy_only(path):
    raw = sqlite3.connect(path)
    raw.executescript("CREATE TABLE fbs_forecasts (game_id TEXT NOT NULL, model TEXT NOT NULL, season INTEGER NOT NULL,"
                      " kickoff_utc TEXT NOT NULL, home_team TEXT, away_team TEXT, home_team_id TEXT, away_team_id TEXT,"
                      " model_version TEXT, p_home REAL NOT NULL, fitted_through TEXT, created_at_utc TEXT,"
                      " locked_at_utc TEXT, late INTEGER DEFAULT 0, PRIMARY KEY (game_id, model));"
                      "INSERT INTO fbs_forecasts VALUES ('1','g2h',2025,'2025-09-06T00:00:00+00:00','A','B','10','11',"
                      " 'v',0.6,'2025-09-05','2025-09-05T10:00:00+00:00',NULL,0);")
    raw.commit()
    raw.close()


def test_audit_on_a_legacy_copy_reports_migration_required_with_its_legacy_counts_and_changes_nothing(tmp_path, capsys):
    db = str(tmp_path / "legacy-audit" / "fbs-model.dev.sqlite3")
    os.makedirs(os.path.dirname(db))
    _legacy_only(db)
    before = open(db, "rb").read()
    report = runner.audit(db)
    assert report["schema_status"] == "migration_required"
    assert report["forecast_rows"] == 1 and report["rows_by_protocol"] == {"legacy": 1}
    assert report["late_rows"] == 0 and report["graded_rows"] is None
    assert {u["table"] for u in report["unavailable"]} >= {"fbs_previews", "fbs_game_status", "fbs_model_meta"}
    assert runner.main(["--audit", "--db", db]) == 5
    assert open(db, "rb").read() == before


def test_audit_on_a_current_copy_is_full_and_changes_nothing(tmp_path):
    db = str(tmp_path / "current-audit" / "fbs-model.dev.sqlite3")
    open_scratch(db).close()
    before = open(db, "rb").read()
    report = runner.audit(db)
    assert report["schema_status"] == "current" and report["unavailable"] == []
    assert report["forecast_rows"] == 0 and "postseason_research_hold_previews" in report
    assert runner.main(["--audit", "--db", db]) == 0
    assert open(db, "rb").read() == before


def test_audit_of_a_missing_file_creates_nothing(tmp_path):
    db = str(tmp_path / "absent" / "fbs-model.dev.sqlite3")
    report = runner.audit(db)
    assert report["schema_status"] == "not_initialized"
    assert not os.path.exists(db)


def test_a_version_one_scratch_database_gains_the_hold_columns_on_migration(tmp_path):
    db = str(tmp_path / "v1" / "scratch.sqlite3")
    os.makedirs(os.path.dirname(db))
    v1 = store.SCHEMA.replace("    hold_reason TEXT,\n", "").replace(",\n    hold_reason TEXT\n);", "\n);")
    raw = sqlite3.connect(db)
    raw.executescript(v1 + store.TRIGGERS)
    raw.execute("PRAGMA user_version = 1")
    raw.execute("INSERT INTO fbs_game_status(game_id,season,revision,lifecycle,observed_utc,source,grading_state)"
                " VALUES('1',2026,1,'scheduled','2026-10-20T00:00:00+00:00','test','pending')")
    raw.commit()
    raw.close()
    assert "hold_reason" not in store.table_columns(sqlite3.connect(db), "fbs_game_status")
    evidence = store.migrate(db, str(tmp_path / "backups"))
    assert evidence["action"] == "migrated"
    con = store.open_db(db)
    assert "hold_reason" in store.table_columns(con, "fbs_previews")
    assert con.execute("SELECT game_id, lifecycle FROM fbs_game_status").fetchall()[0][0] == "1"
    con.close()


def test_audit_of_a_version_one_copy_names_the_missing_hold_columns(tmp_path):
    db = str(tmp_path / "v1-audit" / "scratch.sqlite3")
    os.makedirs(os.path.dirname(db))
    v1 = store.SCHEMA.replace("    hold_reason TEXT,\n", "").replace(",\n    hold_reason TEXT\n);", "\n);")
    raw = sqlite3.connect(db)
    raw.executescript(v1 + store.TRIGGERS)
    raw.execute("PRAGMA user_version = 1")
    raw.commit()
    raw.close()
    before = open(db, "rb").read()
    report = runner.audit(db)
    assert report["schema_status"] == "migration_required"
    assert {(u.get("table"), u.get("column")) for u in report["unavailable"]} == {
        ("fbs_previews", "hold_reason"), ("fbs_game_status", "hold_reason")}
    assert open(db, "rb").read() == before

