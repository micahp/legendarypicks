"""Lifecycle of the NCAAF forecasting operation: status, grading, locks, revisions, outages and voids.

Boards are stubbed at ESPN's scoreboard boundary (runner.read_scoreboard), so the real parsing,
classification, planning and writes all run. The forecast tests fit and predict with the real
service on a synthetic frame. Locks are allowed only where a test stubs the parity certificate;
no real certificate is used here.
"""
import datetime as dt
import math
import sqlite3

import numpy as np
import pandas as pd
import pytest

import fbs_lifecycle as life
import fbs_model_runner as runner
import fbs_model_service as service
import fbs_model_store as store
from fbs_phase3_features_c import FEATURE_NAMES_C as FEATS

KICK = dt.datetime(2026, 10, 24, 16, 0, tzinfo=dt.timezone.utc)      # 12:00 ET, 2026-10-24
NOW_EARLY = KICK - dt.timedelta(hours=10)
NOW_WINDOW = KICK - dt.timedelta(minutes=60)                         # inside T-90
GAME = "9001"
HOME = ("2229", "Florida International")
AWAY = ("2393", "Middle Tennessee")


# ------------------------------------------------------------------------------------ helpers

def board_event(game_id, kickoff, name, completed, home_score=None, away_score=None, home=HOME, away=AWAY,
                season=2026, neutral=False):
    def comp(side, team, score):
        return {"homeAway": side, "score": None if score is None else str(score),
                "team": {"id": team[0], "location": team[1], "displayName": team[1] + " Team"}}
    state = "post" if completed else "pre"
    return {"id": game_id, "date": kickoff, "season": {"year": season},
            "competitions": [{"neutralSite": neutral,
                              "status": {"type": {"name": name, "state": state, "completed": completed}},
                              "competitors": [comp("home", home, home_score), comp("away", away, away_score)]}]}


@pytest.fixture
def con(tmp_path):
    connection = store.open_db(str(tmp_path / "fbs-model.dev.sqlite3"))
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
    con = store.open_db(db)
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
    con = store.open_db(db)
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
    con = store.open_db(db)
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
    con = store.open_db(db)
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

    def fake_features(ratings, slate, season):
        return pd.DataFrame({"game_id": slate["game_id"].astype(str), **{c: 0.0 for c in FEATS}})
    monkeypatch.setattr(runner, "slate_features", fake_features)
    monkeypatch.setattr(runner, "parity_certified", lambda db_path: (True, "TEST STUB certificate"))
    return frame


def window_board(boards, now, events):
    for offset in range(0, 11):
        day = (now + dt.timedelta(days=offset)).strftime("%Y%m%d")
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
    con = store.open_db(db)
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
    con = store.open_db(db)
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
    teams = dict(home_team_id="100", away_team_id="101", home_team="Team 0", away_team="Team 1", week=8)
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
    con = store.open_db(db)
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
    con = store.open_db(db)
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
    con = store.open_db(db)
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

