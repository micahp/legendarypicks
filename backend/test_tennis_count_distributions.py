"""Frozen lock distributions: they match the replays they came from, round-trip exactly, and never look ahead.

The parity tests run the replays' own run() functions on a synthetic database and check that the
distribution rebuilt at each match's day gives the same CRPS and log score the replay recorded.
"""
import os
import random
import sqlite3
import tempfile
import unittest
from unittest import mock

import scoreboard_store
import tennis_count_distributions as tcd
import tennis_lock_sweep
import tennis_props_rate_backtest as rb
import tennis_total_games_backtest as tgb

SURFACES = ("Hard", "Clay", "Grass")
SCORES = ("6-4 6-3", "6-2 6-7(4) 6-4", "7-5 4-6 6-3", "6-3 6-4", "7-6(3) 6-4", "6-1 6-0")
MATCH_COLUMNS = (
    "tourney_id TEXT, tourney_name TEXT, tourney_level TEXT, surface TEXT, tourney_date INTEGER, "
    "match_num INTEGER, winner_id INTEGER, loser_id INTEGER, best_of INTEGER, score TEXT, "
    "w_ace INTEGER, w_df INTEGER, w_svpt INTEGER, w_1stIn INTEGER, w_1stWon INTEGER, w_2ndWon INTEGER, "
    "l_ace INTEGER, l_df INTEGER, l_svpt INTEGER, l_1stIn INTEGER, l_1stWon INTEGER, l_2ndWon INTEGER"
)


def iso(day):
    return f"{day // 10000:04d}-{(day // 100) % 100:02d}-{day % 100:02d}"


def _day_list(start, end):
    import datetime as dt
    first = dt.date(start // 10000, (start // 100) % 100, start % 100)
    last = dt.date(end // 10000, (end // 100) % 100, end % 100)
    days = []
    while first <= last:
        days.append(int(first.strftime("%Y%m%d")))
        first += dt.timedelta(days=1)
    return days


def synthetic_db(path, seed=7):
    """A small best-of-three ATP history: early years for the fit, 2022-2023 for the scored window."""
    rng = random.Random(seed)
    con = sqlite3.connect(path)
    con.execute(f"CREATE TABLE tennis_atp_matches ({MATCH_COLUMNS})")
    days = _day_list(20000101, 20000420) + _day_list(20220101, 20231231)
    players = list(range(101, 115))
    for day in days:
        if rng.random() < 0.6:
            continue
        for _ in range(rng.randint(1, 3)):
            winner, loser = rng.sample(players, 2)
            surface = rng.choice(SURFACES)
            wsv, lsv = rng.randint(50, 110), rng.randint(50, 110)
            w1, l1 = int(wsv * rng.uniform(0.55, 0.75)), int(lsv * rng.uniform(0.55, 0.75))
            w2, l2 = int(wsv * rng.uniform(0.4, 0.6)), int(lsv * rng.uniform(0.4, 0.6))
            con.execute(
                "INSERT INTO tennis_atp_matches (tourney_id,tourney_name,tourney_level,surface,tourney_date,"
                "match_num,winner_id,loser_id,best_of,score,w_ace,w_df,w_svpt,w_1stIn,w_1stWon,w_2ndWon,"
                "l_ace,l_df,l_svpt,l_1stIn,l_1stWon,l_2ndWon) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("900", "Synthetic Open", "A", surface, day, rng.randint(1, 99), winner, loser, 3,
                 rng.choice(SCORES), rng.randint(0, 12), rng.randint(0, 5), wsv, w1, int(w1 * 0.7),
                 int(w2 * 0.5), rng.randint(0, 12), rng.randint(0, 5), lsv, l1, int(l1 * 0.7), int(l2 * 0.5)),
            )
    con.commit()
    con.close()


class ReplayParityTest(unittest.TestCase):
    """The frozen PMF rebuilt at a match's day scores exactly as the replay scored that match."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, "synthetic.db")
        synthetic_db(cls.db)

    def _history(self, day):
        con = sqlite3.connect(self.db)
        try:
            return tcd.build_history(con, "atp", iso(day))
        finally:
            con.close()

    def test_count_pmf_matches_the_props_replay_row_by_row(self):
        rows = rb.run(self.db, "atp", start=20230101, end=20231231)
        checked = 0
        histories = {}
        for row in rows:
            day = int(row["date"])
            if day not in histories:
                histories[day] = self._history(day)
            for target in ("aces", "double_faults"):
                if row["target"] != target:
                    continue
                parameters = tcd.count_parameters(histories[day], target, str(row["player_id"]),
                                                  row["surface"], iso(day))
                pmf = tcd.count_pmf_from_parameters(parameters)
                scores = rb.score_pmf(pmf, int(row["actual"]))
                self.assertAlmostEqual(scores["crps"], row["p1_gamma_poisson_crps"], places=9)
                self.assertAlmostEqual(scores["log_score"], row["p1_gamma_poisson_log_score"], places=9)
                checked += 1
        self.assertGreater(checked, 50)

    def test_games_pmf_matches_the_total_games_replay_row_by_row(self):
        tgb_history_start = tgb.HISTORY_START
        tgb.HISTORY_START = tcd.HISTORY_START  # the research driver's override, as in run_counts_eval.py
        try:
            # The point simulator is not a CP4 candidate; a uniform stand-in keeps the replay running.
            uniform = lambda rules, support: ([1.0 / len(support)] * len(support), 0.0, {
                "expected_sets": 0.0, "p_deciding_set": 0.0, "p_any_tiebreak": 0.0,
                "expected_set_games": 0.0, "expected_tiebreak_sets": 0.0})
            with mock.patch.object(tgb, "simulator_distribution",
                                   side_effect=lambda a, b, rules, support: uniform(rules, support)):
                records, _ = tgb.run(self.db, "atp", start=20230101, end=20231231)
        finally:
            tgb.HISTORY_START = tgb_history_start
        self.assertGreater(len(records), 50)
        checked = 0
        for record in records:
            day = int(record["date"])
            history = self._history(day)
            pmf, _ = tcd.games_distribution(history, record["format"], record["surface"],
                                            record["elo_gap"], iso(day))
            scores = tgb.pmf_scores(pmf, tgb.support_for(record["format"]), int(record["actual_games"]))
            self.assertAlmostEqual(scores["crps"], record["direct_surface_competitive_crps"], places=9)
            self.assertAlmostEqual(scores["log_score"], record["direct_surface_competitive_log_score"], places=9)
            checked += 1
        self.assertEqual(checked, len(records))


class FreezeRoundTripTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "synthetic.db")
        synthetic_db(self.db)
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript(scoreboard_store.SCHEMA)

    def _match(self):
        return {
            "gameId": "401900001", "tour": "atp", "tournamentId": "189", "event": "Synthetic Open",
            "identity": {"home": {"espn_id": "1", "sackmann_player_id": "101"},
                         "away": {"espn_id": "2", "sackmann_player_id": "102"}},
        }

    def test_a_stored_row_rederives_the_same_pmf_from_its_own_parameters(self):
        source = sqlite3.connect(self.db)
        try:
            history = tcd.build_history(source, "atp", "2026-10-20")
        finally:
            source.close()
        rows, skipped = tcd.match_distributions(history, "atp", "2026-10-20", self._match())
        self.assertIsNone(skipped)
        self.assertEqual(sorted((r["cell"], r["side"]) for r in rows),
                         [("aces", "away"), ("aces", "home"), ("double_faults", "away"),
                          ("double_faults", "home"), ("total_games", "match")])
        tcd.store_distributions(self.con, "atp", "401900001", "2026-10-20T10:00:00+00:00", rows)
        stored = self.con.execute(
            "SELECT cell, side, parameters, support_start, pmf, trimmed_mass "
            "FROM tennis_model_lock_distributions WHERE game_id='401900001' ORDER BY cell, side").fetchall()
        self.assertEqual(len(stored), 5)
        by_key = {(r["cell"], r["side"]): r for r in rows}
        import json
        for row in stored:
            original = by_key[(row["cell"], row["side"])]
            parameters = json.loads(row["parameters"])
            pmf = json.loads(row["pmf"])
            self.assertEqual(pmf, original["pmf"])
            self.assertEqual(row["support_start"], original["support_start"])
            if row["cell"] in ("aces", "double_faults"):
                full = tcd.count_pmf_from_parameters(parameters)
                start = row["support_start"]
                self.assertEqual(full[start:start + len(pmf)], pmf)
                self.assertAlmostEqual(sum(full[:start]) + sum(full[start + len(pmf):]), row["trimmed_mass"], 15)
                self.assertLess(row["trimmed_mass"], 2e-12)
                self.assertAlmostEqual(sum(pmf) + row["trimmed_mass"], 1.0, places=9)
            else:
                self.assertAlmostEqual(sum(pmf), 1.0, places=9)
                self.assertEqual(parameters["support_end"], row["support_start"] + len(pmf) - 1)

    def test_frozen_rows_cannot_be_updated_or_deleted(self):
        history = tcd.History()
        rows, _ = tcd.match_distributions(history, "atp", "2026-10-20", self._match())
        tcd.store_distributions(self.con, "atp", "401900001", "2026-10-20T10:00:00+00:00", rows)
        with self.assertRaises(sqlite3.DatabaseError):
            self.con.execute("UPDATE tennis_model_lock_distributions SET trimmed_mass = 0")
        with self.assertRaises(sqlite3.DatabaseError):
            self.con.execute("DELETE FROM tennis_model_lock_distributions")


class LookAheadGuardTest(unittest.TestCase):
    def test_a_source_row_on_the_match_day_fails_loudly(self):
        history = tcd.History()
        same_day = [(20261020, "Event", "A", "Hard", 101, 102, 3, "6-4 6-3", 1, 1, 80, 50, 2, 2, 70, 40)]
        with self.assertRaises(tcd.LookAheadError):
            tcd.replay_rows(history, same_day, cutoff=20261020)

    def test_a_source_row_before_the_match_day_is_used(self):
        history = tcd.History()
        earlier = [(20261019, "Event", "A", "Hard", 101, 102, 3, "6-4 6-3", 1, 1, 80, 50, 2, 2, 70, 40)]
        tcd.replay_rows(history, earlier, cutoff=20261020)
        self.assertGreater(history.elo["101"], tcd.tgb.ELO_START)


class SweepFreezeTest(unittest.TestCase):
    NOW = "2026-10-20T10:30:00+00:00"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "synthetic.db")
        synthetic_db(self.db)
        self.con = sqlite3.connect(self.db)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(scoreboard_store.SCHEMA)
        self.con.execute("CREATE TABLE IF NOT EXISTS players(id INTEGER PRIMARY KEY, league TEXT, espn_id TEXT)")
        self.con.execute("CREATE TABLE IF NOT EXISTS player_source_ids(source TEXT, league TEXT, "
                         "player_id INTEGER, source_player_key TEXT)")
        # The sweep also reads the Bovada quote (dev's _bovada_quote), so the fixture needs the props tables it reads.
        self.con.executescript("""
            CREATE TABLE IF NOT EXISTS prop_games (id INTEGER PRIMARY KEY, league TEXT, espn_event_id TEXT);
            CREATE TABLE IF NOT EXISTS props (id INTEGER PRIMARY KEY, game_id INTEGER, player_id INTEGER, market TEXT,
                                              line REAL, side TEXT, source TEXT, odds INTEGER, odds_captured_at TEXT);
        """)
        for espn_id, sackmann_id, player_id in (("1", "101", 1), ("2", "102", 2)):
            self.con.execute("INSERT INTO players(id,league,espn_id) VALUES(?,?,?)", (player_id, "atp", espn_id))
            self.con.execute("INSERT INTO player_source_ids VALUES('sackmann','atp',?,?)", (player_id, sackmann_id))
        self._pre_snapshot("401900001", home="1", away="2")
        self.con.commit()

    def _pre_snapshot(self, game_id, home, away):
        import json
        payload = {"event": "Synthetic Open", "tournament_id": "189", "round": "R32",
                   "home": {"athlete_id": home, "name": "Player One"},
                   "away": {"athlete_id": away, "name": "Player Two"}}
        self.con.execute(
            "INSERT INTO scoreboard_snapshots(league,game_date,game_id,payload,state,start_time,fetched_at,source) "
            "VALUES('atp','2026-10-20',?,?,'pre','2026-10-20T11:00:00+00:00','2026-10-20T10:00:00+00:00','test')",
            (game_id, json.dumps(payload)))

    def _lock_count(self):
        return self.con.execute("SELECT COUNT(*) FROM tennis_model_locks").fetchone()[0]

    def _distribution_count(self):
        return self.con.execute("SELECT COUNT(*) FROM tennis_model_lock_distributions").fetchone()[0]

    def test_a_projectable_match_locks_and_freezes_its_distributions(self):
        report = tennis_lock_sweep.sweep(self.con, now=_utc(self.NOW))
        self.assertEqual(report["locked"], 1)
        self.assertEqual(report["distribution_frozen"], 1, report)
        self.assertEqual(report["distribution_failed"], 0)
        self.assertEqual(self._distribution_count(), 5)
        self.assertEqual(self.con.execute("SELECT DISTINCT model_version FROM tennis_model_lock_distributions")
                         .fetchone()[0], tcd.MODEL_VERSION)

    def test_an_unmapped_identity_locks_as_before_and_freezes_nothing(self):
        self.con.execute("DELETE FROM player_source_ids WHERE player_id=2")
        self.con.commit()
        report = tennis_lock_sweep.sweep(self.con, now=_utc(self.NOW))
        self.assertEqual(report["locked"], 1)
        self.assertEqual(self._distribution_count(), 0)
        self.assertEqual(report["distribution_skip_reasons"], {"identity_unmapped": 1})

    def test_a_match_without_a_projection_writes_no_lock_and_no_distribution(self):
        with mock.patch.object(tennis_lock_sweep, "project_day", return_value={}), \
                mock.patch.object(tennis_lock_sweep, "store_candidates"):
            report = tennis_lock_sweep.sweep(self.con, now=_utc(self.NOW))
        self.assertEqual(report["no_projection"], 1)
        self.assertEqual(self._lock_count(), 0)
        self.assertEqual(self._distribution_count(), 0)

    def test_a_failing_distribution_never_blocks_the_lock(self):
        with mock.patch.object(tennis_lock_sweep, "build_history", side_effect=RuntimeError("boom")):
            report = tennis_lock_sweep.sweep(self.con, now=_utc(self.NOW))
        self.assertEqual(self._lock_count(), 1)
        self.assertEqual(report["distribution_failed"], 1)
        self.assertEqual(self._distribution_count(), 0)

    def test_old_locks_are_counted_not_backfilled(self):
        # A lock made before this change: a row in tennis_model_locks and nothing in the distribution table.
        self.con.execute(
            "INSERT INTO tennis_model_locks(league,game_date,game_id,start_time,locked_at,projection,model_version) "
            "VALUES('atp','2026-10-20','401900001','2026-10-20T11:00:00+00:00','2026-10-20T10:00:00+00:00',"
            "'{}','tennis-global-surface-elo-blend-v2')")
        self.con.commit()
        report = tennis_lock_sweep.sweep(self.con, now=_utc(self.NOW))
        self.assertEqual(report["already_locked"], 1)
        self.assertEqual(report["distribution_frozen"], 0)
        self.assertEqual(self._distribution_count(), 0)

    def test_the_schema_is_idempotent_and_leaves_existing_locks_readable(self):
        tennis_lock_sweep.sweep(self.con, now=_utc(self.NOW))
        self.con.executescript(scoreboard_store.SCHEMA)
        self.assertEqual(self._lock_count(), 1)
        row = self.con.execute("SELECT projection, model_version FROM tennis_model_locks").fetchone()
        self.assertIsNotNone(row["projection"])


def _utc(text):
    import datetime as dt
    return dt.datetime.fromisoformat(text)


if __name__ == "__main__":
    unittest.main()
