"""Tests for routers/nfl_model.py: what the model page is allowed to show.

Plants: a legacy lock with no projected scores and no snapshot, a snapshot whose line differs from
the schedule's current line, an unlocked audit row that must not appear, and a graded game.
Model Pick expectations are worked out by hand from docs/MODEL-PICK-RULES.md ("NFL order").
"""
import datetime as dt
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_lock as nl  # noqa: E402
from routers import nfl_model as m  # noqa: E402

LOCK_AT = dt.datetime(2026, 10, 11, 16, 0, tzinfo=dt.timezone.utc)
LEGACY = "nfl-v1 cap=21.0 sigma=13.4"

TEAMS = [("ARI", "Arizona Cardinals"), ("ATL", "Atlanta Falcons"), ("BAL", "Baltimore Ravens"),
         ("BUF", "Buffalo Bills"), ("CAR", "Carolina Panthers"), ("CHI", "Chicago Bears"),
         ("CIN", "Cincinnati Bengals"), ("CLE", "Cleveland Browns"), ("DAL", "Dallas Cowboys"),
         ("DEN", "Denver Broncos"), ("DET", "Detroit Lions"), ("GB", "Green Bay Packers"),
         ("HOU", "Houston Texans"), ("IND", "Indianapolis Colts"), ("JAX", "Jacksonville Jaguars"),
         ("KC", "Kansas City Chiefs"), ("LAC", "Los Angeles Chargers"), ("LAR", "Los Angeles Rams"),
         ("LV", "Las Vegas Raiders"), ("MIA", "Miami Dolphins"), ("MIN", "Minnesota Vikings"),
         ("NE", "New England Patriots"), ("NO", "New Orleans Saints"), ("NYG", "New York Giants"),
         ("NYJ", "New York Jets"), ("PHI", "Philadelphia Eagles"), ("PIT", "Pittsburgh Steelers"),
         ("SEA", "Seattle Seahawks"), ("SF", "San Francisco 49ers"), ("TB", "Tampa Bay Buccaneers"),
         ("TEN", "Tennessee Titans"), ("WSH", "Washington Commanders")]
CODES = [code for code, _ in TEAMS]
NAMES = dict(TEAMS)


def make_db(con):
    """The tables the NFL model page reads, including the team and preseason tables that team
    strength reads. Every test builds its own database in a temp directory."""
    con.execute(
        "CREATE TABLE nfl_schedule (game_id TEXT, season INT, game_type TEXT, week INT, "
        "home_team TEXT, away_team TEXT, location TEXT, home_score REAL, away_score REAL, "
        "result REAL, spread_line REAL, total_line REAL, home_moneyline REAL, "
        "away_moneyline REAL, gameday TEXT, gametime TEXT, ingested_at TEXT)")
    con.execute("CREATE TABLE nfl_teams (season INT, team TEXT, team_name TEXT, conference TEXT, "
                "division TEXT)")
    con.execute("CREATE TABLE prop_games (id INTEGER PRIMARY KEY AUTOINCREMENT, league TEXT NOT NULL, "
                "date TEXT NOT NULL, home TEXT, away TEXT, espn_event_id TEXT, final_home INTEGER, "
                "final_away INTEGER, start_time TEXT, cancelled_at TEXT, cancel_reason TEXT, "
                "cancel_source TEXT)")
    for code, name in TEAMS:
        con.execute("INSERT INTO nfl_teams VALUES (2026, ?, ?, 'X', 'Y')", (code, name))


class Payload(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(os.path.join(self._tmp.name, "t.db"))
        make_db(self.con)
        self.con.execute("INSERT INTO nfl_schedule VALUES ('g1',2026,'REG',5,'GB','CHI','Home',"
                         "NULL,NULL,NULL,-1.5,45.5,105,-125,'2026-10-11','13:00','i0')")
        nl.ensure_schema(self.con)
        nl.start_run(self.con, "r1", 2026, 5, m.ADOPTED, {})
        nl.lock_week(self.con, "r1", 2026, 5, lambda h, a, n: (17.4, 28.9, 0.19), as_of="t1",
                     now=LOCK_AT)
        nl.finish_run(self.con, "r1", "ok")
        nl.start_run(self.con, "r2", 2026, 5, m.ADOPTED, {})
        nl.lock_week(self.con, "r2", 2026, 5, lambda h, a, n: (30.0, 10.0, 0.9), as_of="t2",
                     now=LOCK_AT)                       # a refresh: locked = 0, never shown
        nl.finish_run(self.con, "r2", "ok")
        nl.start_run(self.con, "legacy", 2026, 5, LEGACY, {})
        self.con.execute(
            "INSERT INTO game_projections (run_id, league, game_id, season, week, home, away, "
            " proj_margin, proj_total, p_home_win, market_spread, market_total, market_source, "
            " locked, locked_at, model_version) VALUES ('legacy','nfl','g1',2026,5,'GB','CHI',"
            " -14.2,46.3,0.14,-1.5,45.5,'nflverse',1,'t0','nfl-v1 cap=21.0 sigma=13.4')")
        nl.finish_run(self.con, "legacy", "ok")
        self.con.execute("UPDATE nfl_schedule SET spread_line = 3.0")   # line moved after lock
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self._tmp.cleanup()

    def lock(self, gid="g1"):
        g, = [x for x in m.locks_payload(self.con, 2026, 5)["games"] if x["game_id"] == gid]
        return g["locks"]

    def test_locked_rows_only_with_the_locked_line(self):
        p = m.locks_payload(self.con, 2026, None)
        self.assertEqual(p["week"], 5)
        g, = p["games"]
        v1 = g["locks"][m.ADOPTED]
        self.assertEqual((v1["proj_home"], v1["proj_away"], v1["locked_at"]), (17.4, 28.9, "t1"))
        self.assertEqual(v1["line"]["spread"], -1.5)
        self.assertEqual(v1["line"]["source"], "snapshot")
        self.assertEqual(v1["line"]["home_moneyline"], 105)

    def test_pick_is_one_backend_rule_on_the_frozen_line(self):
        # Margin -11.5 for GB against a snapshot spread of -1.5 (CHI favoured). M = 11.5 for CHI:
        # M >= 7 and M >= V = 1.5, so rule 1: CHI -1.5. The schedule line was moved to 3.0 in
        # setUp, and the pick must still read the frozen snapshot.
        pick = self.lock()[m.ADOPTED]["pick"]
        self.assertEqual((pick["market"], pick["side"], pick["line"], pick["rule"], pick["status"]),
                         ("spread", "away", -1.5, 1, "pick"))
        self.assertEqual(pick["label"], "CHI -1.5")

    def test_pick_statuses_for_a_missing_line_and_a_pickem(self):
        # Spread 3 for GB (home favoured by 3), projected margin 3: M = 3, V = 3 gives rule 4.
        nl.start_run(self.con, "eq", 2026, 5, "eq-v", {})
        self.con.execute(
            "INSERT INTO game_projections (run_id, league, game_id, season, week, home, away, "
            "proj_margin, proj_total, p_home_win, market_spread, market_total, market_source, "
            "locked, locked_at, model_version) VALUES ('eq','nfl','g1',2026,5,'GB','CHI',"
            "3.0,44.5,0.55,3.0,44.5,'nflverse',1,'t-eq','eq-v')")
        nl.finish_run(self.con, "eq", "ok")
        # No spread at all: no rule can run.
        nl.start_run(self.con, "nl", 2026, 5, "nl-v", {})
        self.con.execute(
            "INSERT INTO game_projections (run_id, league, game_id, season, week, home, away, "
            "proj_margin, proj_total, p_home_win, market_spread, market_total, market_source, "
            "locked, locked_at, model_version) VALUES ('nl','nfl','g1',2026,5,'GB','CHI',"
            "2.0,44.5,0.55,NULL,44.5,'nflverse',1,'t-nl','nl-v')")
        nl.finish_run(self.con, "nl", "ok")
        # A pick'em (spread 0) with no team strength: rule 5 has no favourite, so no pick.
        nl.start_run(self.con, "pk", 2026, 5, "pk-v", {})
        self.con.execute(
            "INSERT INTO game_projections (run_id, league, game_id, season, week, home, away, "
            "proj_margin, proj_total, p_home_win, market_spread, market_total, market_source, "
            "locked, locked_at, model_version) VALUES ('pk','nfl','g1',2026,5,'GB','CHI',"
            "0.0,44.5,0.5,0.0,44.5,'nflverse',1,'t-pk','pk-v')")
        nl.finish_run(self.con, "pk", "ok")
        locks = self.lock()
        self.assertEqual((locks["eq-v"]["pick"]["market"], locks["eq-v"]["pick"]["side"],
                          locks["eq-v"]["pick"]["rule"], locks["eq-v"]["pick"]["label"]),
                         ("ml", "home", 4, "GB ML"))
        self.assertEqual((locks["nl-v"]["pick"]["status"], locks["nl-v"]["pick"]["label"]),
                         ("no_line", "No line"))
        self.assertEqual((locks["pk-v"]["pick"]["status"], locks["pk-v"]["pick"]["rule"],
                          locks["pk-v"]["pick"]["label"]), ("no_pick", 5, "No pick"))

    def test_legacy_lock_shows_no_scores_and_says_where_its_line_came_from(self):
        g, = m.locks_payload(self.con, 2026, 5)["games"]
        legacy = g["locks"][LEGACY]
        self.assertIsNone(legacy["proj_home"])
        self.assertEqual(legacy["line"]["source"], "lock row")
        # Snapshot-less lock: the row's own market_spread -1.5 is the line. M = 14.2 for CHI: rule 1.
        self.assertEqual((legacy["pick"]["side"], legacy["pick"]["rule"], legacy["pick"]["label"]),
                         ("away", 1, "CHI -1.5"))

    def test_models_labelled_and_ordered_with_one_adopted(self):
        models = m.locks_payload(self.con, 2026, 5)["models"]
        self.assertEqual([x["label"] for x in models],
                         ["v1 points", "v1 points (10-09, before the freeze)"])
        self.assertEqual([x["adopted"] for x in models], [True, False])

    def test_the_elo_stack_is_a_fourth_trial_model_after_v1_and_v2(self):
        v = "nfl-v1+elo stack season=2026 train=2010-2025 elo=538 K=20 hfa=65 carry=0.3333 lead=90min"
        d = m.describe("nfl-v1-elo-stack", v)
        self.assertEqual((d["family"], d["label"], d["adopted"]), ("v1+elo", "v1 + Elo", False))
        self.assertGreater(d["order"], m.describe("nfl-ratings-v1", m.ADOPTED)["order"])
        self.assertLess(d["order"], m.describe("nfl-epa-v2", "nfl-epa-v2 untuned")["order"])

    def _final(self, hs, as_, ats="win"):
        self.con.execute("UPDATE nfl_schedule SET home_score=?, away_score=?, result=?",
                         (hs, as_, hs - as_))
        brier = None if hs == as_ else 0.03                     # the grader stores no Brier for a tie
        self.con.execute("INSERT INTO projection_grades VALUES ('nfl','g1',?,?,?,?,0.2,"
                         "4.5,-1.3,?,'t9')", (m.ADOPTED, hs, as_, brier, ats))

    def test_final_and_grade_appear_together(self):
        self.con.execute("UPDATE nfl_schedule SET home_score=20, away_score=27, result=-7")
        self.con.execute("INSERT INTO projection_grades VALUES ('nfl','g1',?,20,27,0.03,0.2,"
                         "4.5,-1.3,'win','t9')", (m.ADOPTED,))
        g, = m.locks_payload(self.con, 2026, 5)["games"]
        self.assertEqual(g["final"], {"home": 20.0, "away": 27.0})
        grade = g["locks"][m.ADOPTED]["grade"]
        self.assertEqual(grade["pick"], "win")               # CHI -1.5 against a 7-point CHI win
        self.assertNotIn("ats", grade)                       # the stored spread column is not shown
        self.assertNotIn("total", grade)
        self.assertEqual(g["kickoff_utc"], "2026-10-11T17:00:00Z")

    def test_grade_carries_the_straight_up_result(self):
        self._final(20, 27)                                     # CHI (away) won; lock favoured CHI
        g, = m.locks_payload(self.con, 2026, 5)["games"]
        self.assertEqual(g["locks"][m.ADOPTED]["grade"]["su"], "win")

    def test_record_counts_only_graded_and_says_what_is_waiting(self):
        before = {r["version"]: r for r in m.locks_payload(self.con, 2026, 5)["record"]}
        self.assertEqual((before[m.ADOPTED]["locked"], before[m.ADOPTED]["graded"],
                          before[m.ADOPTED]["awaiting"]), (1, 0, 1))
        self.assertIsNone(before[m.ADOPTED]["su"])              # no graded game: no record, not 0-0
        self.assertIsNone(before[m.ADOPTED]["pick"])
        self._final(20, 27)
        rec = {r["version"]: r for r in m.locks_payload(self.con, 2026, 5)["record"]}
        v1 = rec[m.ADOPTED]
        self.assertEqual((v1["locked"], v1["graded"], v1["awaiting"]), (1, 1, 0))
        self.assertEqual(v1["pick"], {"win": 1, "loss": 0, "push": 0, "no_pick": 0, "no_line": 0})
        self.assertEqual(v1["su"], {"win": 1, "loss": 0, "tie": 0, "no_pick": 0})
        self.assertAlmostEqual(v1["mean_brier"], 0.03)
        self.assertEqual(v1["brier_n"], 1)
        self.assertAlmostEqual(v1["mean_abs_margin_err"], 4.5)
        self.assertNotIn("ats", v1)
        self.assertNotIn("total", v1)
        legacy = rec[LEGACY]                                    # locked, not graded: still waiting
        self.assertEqual((legacy["locked"], legacy["graded"], legacy["awaiting"]), (1, 0, 1))
        self.assertEqual([r["version"] for r in m.locks_payload(self.con, 2026, 5)["record"]],
                         [m.ADOPTED, LEGACY])

    def test_a_tied_game_is_a_tie_not_a_loss_for_straight_up_and_a_loss_for_the_pick(self):
        self._final(24, 24, ats="push")
        v1 = {r["version"]: r for r in m.locks_payload(self.con, 2026, 5)["record"]}[m.ADOPTED]
        self.assertEqual(v1["su"], {"win": 0, "loss": 0, "tie": 1, "no_pick": 0})
        # CHI -1.5 on a 24-24 tie: CHI does not win by more than 1.5, so the pick loses.
        self.assertEqual(v1["pick"]["loss"], 1)
        self.assertEqual(v1["pick"]["push"], 0)
        self.assertIsNone(v1["mean_brier"])                     # the grader stores no Brier for a tie
        self.assertEqual(v1["brier_n"], 0)

    def test_no_locks_is_an_empty_payload_not_an_error(self):
        p = m.locks_payload(self.con, 2025, None)
        self.assertEqual((p["week"], p["games"], p["weeks"]), (None, [], []))

    def test_failed_runs_are_not_exposed_as_locks_or_records(self):
        for run_id in ("r1", "r2", "legacy"):
            nl.finish_run(self.con, run_id, "failed", error="planted failure")
        payload = m.locks_payload(self.con, 2026, None)
        self.assertEqual((payload["week"], payload["weeks"], payload["models"],
                          payload["games"], payload["record"]), (None, [], [], [], []))

    def test_preview_runs_remain_visible_but_are_not_counted_as_locked(self):
        nl.start_run(self.con, "preview", 2026, 5, "preview-v", {}, status="preview")
        self.con.execute(
            "INSERT INTO game_projections (run_id, league, game_id, season, week, home, away, "
            "proj_margin, proj_total, p_home_win, locked, locked_at, model_version) "
            "VALUES ('preview','nfl','g1',2026,5,'GB','CHI',2,45,0.6,0,'t-preview','preview-v')")
        payload = m.locks_payload(self.con, 2026, 5)
        preview = payload["games"][0]["locks"]["preview-v"]
        self.assertTrue(preview["preview"])
        self.assertEqual(preview["previewed_at"], "t-preview")
        self.assertIsNone(preview["grade"])
        self.assertEqual(next(row for row in payload["models"] if row["version"] == "preview-v")["locks"], 0)
        self.assertNotIn("preview-v", [r["version"] for r in payload["record"]])

    def test_graded_no_pick_and_no_line_are_counted_apart_from_wins_and_losses(self):
        # A pick'em with no team strength (no_pick) and a lock with no spread (no_line), both
        # graded. Neither is a win or a loss in the Model Pick record.
        nl.start_run(self.con, "pk", 2026, 5, "pk-v", {})
        self.con.execute(
            "INSERT INTO game_projections (run_id, league, game_id, season, week, home, away, "
            "proj_margin, proj_total, p_home_win, market_spread, market_total, market_source, "
            "locked, locked_at, model_version) VALUES ('pk','nfl','g1',2026,5,'GB','CHI',"
            "0.0,44.5,0.5,0.0,44.5,'nflverse',1,'t-pk','pk-v')")
        nl.finish_run(self.con, "pk", "ok")
        nl.start_run(self.con, "nl", 2026, 5, "nl-v", {})
        self.con.execute(
            "INSERT INTO game_projections (run_id, league, game_id, season, week, home, away, "
            "proj_margin, proj_total, p_home_win, market_spread, market_total, market_source, "
            "locked, locked_at, model_version) VALUES ('nl','nfl','g1',2026,5,'GB','CHI',"
            "2.0,44.5,0.55,NULL,44.5,'nflverse',1,'t-nl','nl-v')")
        nl.finish_run(self.con, "nl", "ok")
        self.con.execute("UPDATE nfl_schedule SET home_score=20, away_score=27, result=-7")
        for version in ("pk-v", "nl-v"):
            self.con.execute("INSERT INTO projection_grades VALUES ('nfl','g1',?,20,27,0.3,0.7,-7,0,"
                             "'loss','t9')", (version,))
        rec = {r["version"]: r for r in m.locks_payload(self.con, 2026, 5)["record"]}
        self.assertEqual(rec["pk-v"]["pick"], {"win": 0, "loss": 0, "push": 0, "no_pick": 1, "no_line": 0})
        self.assertEqual(rec["nl-v"]["pick"], {"win": 0, "loss": 0, "push": 0, "no_pick": 0, "no_line": 1})
        self.assertEqual(rec["pk-v"]["graded"], 1)

    def test_a_later_line_or_projection_cannot_change_the_locked_pick_or_grade(self):
        before = self.lock()[m.ADOPTED]["pick"]
        # The schedule line moves, and a refresh row (locked = 0) with a very different projection
        # is written after the lock. Neither may change the locked pick.
        self.con.execute("UPDATE nfl_schedule SET spread_line=20.0, total_line=59.0")
        self._final(20, 27)
        after = self.lock()[m.ADOPTED]
        self.assertEqual(after["pick"], before)
        self.assertEqual(after["pick"]["label"], "CHI -1.5")
        self.assertEqual(after["grade"]["pick"], "win")
        row = next(x for x in m.locks_payload(self.con, 2026, 5)["record"] if x["version"] == m.ADOPTED)
        self.assertEqual(row["pick"]["win"], 1)

    def test_grading_twice_gives_identical_payloads(self):
        self._final(20, 27)
        first = m.locks_payload(self.con, 2026, 5)
        second = m.locks_payload(self.con, 2026, 5)
        self.assertEqual(first, second)

    def test_two_model_versions_keep_independent_records(self):
        self._final(20, 27)                                     # adopted: CHI covers -> win
        self.con.execute("INSERT INTO projection_grades VALUES ('nfl','g1',?,27,20,0.5,0.7,0.0,0.0,"
                         "'loss','t9')", (LEGACY,))             # legacy: GB wins -> loss
        rec = {r["version"]: r for r in m.locks_payload(self.con, 2026, 5)["record"]}
        self.assertEqual(rec[m.ADOPTED]["pick"]["win"], 1)
        self.assertEqual(rec[m.ADOPTED]["pick"]["loss"], 0)
        self.assertEqual(rec[LEGACY]["pick"]["loss"], 1)
        self.assertEqual(rec[LEGACY]["pick"]["win"], 0)

    def test_null_snapshot_fields_fall_back_to_original_lock_row(self):
        # The grader and the page both use COALESCE(snapshot, lock row). The snapshot's line is
        # gone, so the lock row's -1.5 and 45.5 stand, and the pick is the same CHI -1.5.
        self.con.execute("UPDATE nfl_line_snapshots SET spread_line=NULL, total_line=NULL")
        self.con.execute("UPDATE nfl_schedule SET spread_line=99.0, total_line=99.0")
        g, = m.locks_payload(self.con, 2026, 5)["games"]
        lock = g["locks"][m.ADOPTED]
        self.assertEqual((lock["line"]["spread"], lock["line"]["total"]), (-1.5, 45.5))
        self.assertEqual(lock["pick"]["label"], "CHI -1.5")
        self._final(20, 27)
        graded, = m.locks_payload(self.con, 2026, 5)["games"]
        self.assertEqual(graded["locks"][m.ADOPTED]["grade"]["pick"], "win")

    def test_epa_family(self):
        d = m.describe("nfl-epa-v2", "nfl-epa-v2 pure per-play half_life=12 lam=450 NOT-ADOPTED")
        self.assertEqual((d["family"], d["label"], d["adopted"]), ("v2", "v2 EPA", False))


class TeamStrengthAtTheLock(unittest.TestCase):
    """Tiers from real rows. Scenario (all 2026):

    preseason prop_games, 16 games dated 2026-08-20: CODES[2k] beat CODES[2k+1] by 16 - k. Half
    the home rows carry the full team name. So ARI (CODES[0]) has +16 and ATL (CODES[1]) has -16.
    REG week 1 (2026-09-10), first REG day: DEN 14 CHI 17.
    REG week 4 (2026-10-04): ARI 30 CHI 10, so ARI averages (16 + 20) / 2 = 18 before 10-11.
    Week 5 (2026-10-11, 13:00 ET), ARI (home) vs ATL, spread 0, total 45: the locked game.
    Two later rows must not count for it: a same-day REG game is not in the schedule's scored set,
    and REG week 6 (2026-10-18) ARI 0 DEN 40 is dated after the kickoff. A prop row dated after the
    first REG day (2026-09-12, ARI 0 to 100) is outside the preseason window.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(os.path.join(self._tmp.name, "t.db"))
        make_db(self.con)
        for k in range(16):
            home, away = CODES[2 * k], CODES[2 * k + 1]
            label = NAMES[home] if k % 2 == 0 else home
            self.con.execute("INSERT INTO prop_games (league, date, home, away, final_home, final_away) "
                             "VALUES ('nfl', '2026-08-20', ?, ?, ?, 20)", (label, away, 20 + 16 - k))
        self.con.execute("INSERT INTO prop_games (league, date, home, away, final_home, final_away) "
                         "VALUES ('nfl', '2026-09-12', 'ARI', 'NO', 0, 100)")
        reg = [("g_w1", 1, "2026-09-10", "DEN", "CHI", 14, 17),
               ("g_prior", 4, "2026-10-04", "ARI", "CHI", 30, 10),
               ("g_future", 6, "2026-10-18", "ARI", "DEN", 0, 40)]
        for gid, wk, day, home, away, hs, as_ in reg:
            self.con.execute("INSERT INTO nfl_schedule VALUES (?,2026,'REG',?,?,?,'Home',?,?,?,NULL,NULL,"
                             "NULL,NULL,?,'13:00','i')", (gid, wk, home, away, hs, as_, hs - as_, day))
        self.con.execute("INSERT INTO nfl_schedule VALUES ('g_test',2026,'REG',5,'ARI','ATL','Home',"
                         "NULL,NULL,NULL,0.0,45.0,-110,-110,'2026-10-11','13:00','i')")
        nl.ensure_schema(self.con)
        nl.start_run(self.con, "r5", 2026, 5, "v5", {})
        nl.lock_week(self.con, "r5", 2026, 5, lambda h, a, n: (24.0, 24.0, 0.5), as_of="t5", now=LOCK_AT)
        nl.finish_run(self.con, "r5", "ok")
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self._tmp.cleanup()

    def tiers(self):
        return m.StrengthTiers(self.con, 2026)

    def test_pickem_between_a_strong_and_a_weak_team_is_the_strong_moneyline(self):
        self.assertEqual(self.tiers().for_kickoff("2026-10-11", "ARI", "ATL"), ("strong", "weak"))
        pick = m.locks_payload(self.con, 2026, 5)["games"][0]["locks"]["v5"]["pick"]
        self.assertEqual((pick["market"], pick["side"], pick["rule"], pick["label"]),
                         ("ml", "home", 5, "ARI ML"))

    def test_only_games_dated_before_the_kickoff_feed_the_tiers(self):
        t = self.tiers()
        t.for_kickoff("2026-10-11", "ARI", "ATL")                      # loads the season
        margins = m._per_game_margins(t._rows, "2026-10-11")
        # ARI: +16 (preseason) and +20 (week 4). The 0-40 game on 10-18 and the 0-100 prop row
        # dated 09-12 are both outside their windows and must not move the average.
        self.assertAlmostEqual(margins["ARI"], 18.0, places=12)
        self.assertAlmostEqual(margins["ATL"], -16.0, places=12)

    def test_preseason_window_ends_the_day_before_the_first_reg_game(self):
        t = self.tiers()
        t.for_kickoff("2026-10-11", "ARI", "ATL")
        preseason = [r for r in t._rows if r[0] == "2026-08-20"]
        self.assertEqual(len(preseason), 16)
        self.assertFalse([r for r in t._rows if r[0] == "2026-09-12"])

    def test_full_team_names_and_aliases_map_to_codes(self):
        self.con.execute("INSERT INTO prop_games (league, date, home, away, final_home, final_away) "
                         "VALUES ('nfl', '2026-08-22', 'LA', 'WAS', 10, 7)")
        t = self.tiers()
        t.for_kickoff("2026-10-11", "ARI", "ATL")
        self.assertIn(("2026-08-22", "LAR", "WSH", 10.0, 7.0), t._rows)
        self.assertIn(("2026-08-20", "ARI", "ATL", 36.0, 20.0), t._rows)

    def test_an_unknown_team_name_fails_loudly(self):
        self.con.execute("INSERT INTO prop_games (league, date, home, away, final_home, final_away) "
                         "VALUES ('nfl', '2026-08-21', 'Gotham Giants', 'BAL', 10, 7)")
        with self.assertRaisesRegex(ValueError, "Gotham Giants"):
            self.tiers().for_kickoff("2026-10-11", "ARI", "ATL")
        with self.assertRaisesRegex(ValueError, "Gotham Giants"):
            m.locks_payload(self.con, 2026, 5)

    def test_a_season_without_32_teams_fails_loudly(self):
        self.con.execute("DELETE FROM nfl_teams WHERE team = 'WSH'")
        with self.assertRaisesRegex(ValueError, "31 teams"):
            self.tiers().for_kickoff("2026-10-11", "ARI", "ATL")

    def test_no_games_before_kickoff_means_no_tier(self):
        self.assertEqual(self.tiers().for_kickoff("2026-08-19", "ARI", "ATL"), (None, None))

    def test_a_missing_kickoff_date_is_refused(self):
        with self.assertRaises(ValueError):
            self.tiers().for_kickoff(None, "ARI", "ATL")

    def test_a_non_iso_date_in_the_schedule_is_refused(self):
        self.con.execute("UPDATE nfl_schedule SET gameday = '10/11/2026' WHERE game_id = 'g_prior'")
        with self.assertRaisesRegex(ValueError, "not a YYYY-MM-DD"):
            self.tiers().for_kickoff("2026-10-11", "ARI", "ATL")


if __name__ == "__main__":
    unittest.main()
