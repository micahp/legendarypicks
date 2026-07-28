"""Tests for D/ST entities: scoring, ingest, and draft-board integration."""
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from routers import nfl_offseason
from routers import nfl_mock_draft
import ingest_nfl_dst as dst_mod
import ingest_nfl_adp

# Use the same NFL_TEAMS the ingest module publishes.
NFL_TEAMS = dst_mod.NFL_TEAMS


class DstScoringTests(unittest.TestCase):
    """Verify the ESPN D/ST scoring formula in isolation."""

    def test_sack_interception_fumble_td_points(self):
        # Use points_allowed=21 (0-point tier) to isolate individual stat values
        self.assertEqual(1.0, dst_mod.compute_fantasy_pts(sacks=1, points_allowed=21))
        self.assertEqual(2.0, dst_mod.compute_fantasy_pts(interceptions=1, points_allowed=21))
        self.assertEqual(2.0, dst_mod.compute_fantasy_pts(fumble_rec=1, points_allowed=21))
        self.assertEqual(6.0, dst_mod.compute_fantasy_pts(tds=1, points_allowed=21))
        self.assertEqual(2.0, dst_mod.compute_fantasy_pts(safeties=1, points_allowed=21))
        self.assertEqual(6.0, dst_mod.compute_fantasy_pts(st_tds=1, points_allowed=21))
        self.assertEqual(6.0, dst_mod.compute_fantasy_pts(pr_tds=1, points_allowed=21))

    def test_points_allowed_tiers(self):
        cases = [
            (0, 10.0),
            (1, 7.0),
            (6, 7.0),
            (7, 4.0),
            (13, 4.0),
            (14, 1.0),
            (20, 1.0),
            (21, 0.0),
            (27, 0.0),
            (28, -1.0),
            (34, -1.0),
            (35, -4.0),
            (45, -4.0),
        ]
        for pa, expected in cases:
            with self.subTest(points_allowed=pa):
                self.assertEqual(expected, dst_mod.points_allowed_tier(pa))

    def test_complete_week_example(self):
        """Reproduce a known D/ST score: 3 sacks, 1 INT, 1 FR, 0 TD, 13 PA."""
        pts = dst_mod.compute_fantasy_pts(
            sacks=3, interceptions=1, fumble_rec=1,
            points_allowed=13,
        )
        # 3*1 + 1*2 + 1*2 + 4 (PA tier) = 11
        self.assertEqual(11.0, pts)

    def test_shutout_bonus(self):
        """0 points allowed = 10-point bonus."""
        pts = dst_mod.compute_fantasy_pts(points_allowed=0)
        self.assertEqual(10.0, pts)

    def test_blowout_penalty(self):
        """35+ points allowed = -4."""
        pts = dst_mod.compute_fantasy_pts(points_allowed=35)
        self.assertEqual(-4.0, pts)

    def test_defensive_touchdown(self):
        """A defensive TD is worth 6."""
        pts = dst_mod.compute_fantasy_pts(tds=1, points_allowed=20)
        self.assertEqual(7.0, pts)  # 6 TD + 1 PA tier

    def test_special_teams_and_punt_return_tds(self):
        """ST TD and PR TD each worth 6."""
        pts = dst_mod.compute_fantasy_pts(st_tds=1, pr_tds=1, points_allowed=21)
        self.assertEqual(12.0, pts)  # 6 + 6 + 0 PA tier


class DstEnsurePlayersTests(unittest.TestCase):
    """The DEF player spine (32 rows, one per team)."""

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        self.con = sqlite3.connect(self.db_path)
        self.con.execute("""
            CREATE TABLE players (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                league TEXT NOT NULL,
                team TEXT,
                position TEXT,
                active INTEGER,
                updated_at TEXT
            )
        """)
        self.con.commit()

    def tearDown(self):
        self.con.close()
        os.unlink(self.db_path)

    def test_creates_32_def_players_from_empty_db(self):
        players = dst_mod.ensure_dst_players(self.con)
        self.assertEqual(32, len(players))
        self.assertEqual(set(NFL_TEAMS.keys()), set(players.keys()))

        row = self.con.execute(
            "SELECT name, team, position, active FROM players WHERE league='nfl' AND position='DEF'"
        ).fetchall()
        self.assertEqual(32, len(row))
        for name, team, position, active in row:
            self.assertTrue(name.endswith(" D/ST"))
            self.assertEqual("DEF", position)
            self.assertEqual(1, active)
            self.assertIn(team, NFL_TEAMS)

    def test_idempotent_does_not_duplicate(self):
        first = dst_mod.ensure_dst_players(self.con)
        second = dst_mod.ensure_dst_players(self.con)
        self.assertEqual(first, second)

        count = self.con.execute(
            "SELECT COUNT(*) FROM players WHERE league='nfl' AND position='DEF'"
        ).fetchone()[0]
        self.assertEqual(32, count)

    def test_picks_up_existing_def_players(self):
        # Insert a few by hand
        self.con.execute(
            "INSERT INTO players (name, league, team, position, active, updated_at) "
            "VALUES ('Arizona Cardinals D/ST', 'nfl', 'ARI', 'DEF', 1, datetime('now'))"
        )
        self.con.execute(
            "INSERT INTO players (name, league, team, position, active, updated_at) "
            "VALUES ('Dallas Cowboys D/ST', 'nfl', 'DAL', 'DEF', 1, datetime('now'))"
        )
        self.con.commit()

        players = dst_mod.ensure_dst_players(self.con)
        self.assertEqual(32, len(players))
        # Existing players preserved, missing ones created
        self.assertIn("ARI", players)
        self.assertIn("DAL", players)
        self.assertIn("SEA", players)


class DstDraftBoardTests(unittest.TestCase):
    """The nfl/draft-board endpoint returns DEF players with D/ST stats."""

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        with sqlite3.connect(self.db_path) as connection:
            connection.executescript("""
                CREATE TABLE players(
                  id INTEGER PRIMARY KEY,
                  name TEXT NOT NULL,
                  league TEXT NOT NULL,
                  team TEXT,
                  position TEXT,
                  active INTEGER,
                  updated_at TEXT
                );
                CREATE TABLE player_game_logs(
                  player_id INTEGER,
                  league TEXT,
                  season INTEGER,
                  game_no TEXT,
                  game_id TEXT,
                  game_type TEXT,
                  team TEXT,
                  stats TEXT
                );
                CREATE TABLE nfl_dst_stats(
                  player_id INTEGER NOT NULL,
                  season INTEGER NOT NULL,
                  week INTEGER NOT NULL,
                  sacks REAL,
                  interceptions REAL,
                  tds REAL,
                  safeties REAL,
                  fumble_rec REAL,
                  st_tds REAL,
                  pr_tds REAL,
                  points_allowed REAL,
                  fantasy_pts REAL,
                  UNIQUE(player_id, season, week)
                );
                CREATE TABLE nfl_adp(
                  player_id INTEGER,
                  season INTEGER,
                  adp REAL,
                  percent_owned REAL
                );
                CREATE TABLE nfl_depth_chart(
                  player_id INTEGER,
                  season INTEGER,
                  team TEXT,
                  pos_abb TEXT,
                  pos_rank INTEGER
                );
                CREATE TABLE team_stats_coverage(
                  run_id TEXT PRIMARY KEY,
                  league TEXT,
                  season INTEGER,
                  status TEXT,
                  fetched_teams INTEGER,
                  fetched_games INTEGER,
                  completed_at TEXT
                );
                CREATE TABLE nfl_schedule(
                  game_id TEXT,
                  season INTEGER,
                  week INTEGER,
                  home_team TEXT,
                  away_team TEXT
                );
            """)
            # Two D/ST players
            connection.executemany(
                "INSERT INTO players VALUES(?,?,?,?,?,?,?)",
                [
                    (101, "Seattle Seahawks D/ST", "nfl", "SEA", "DEF", 1, "2026-07-20T12:00:00+00:00"),
                    (102, "Kansas City Chiefs D/ST", "nfl", "KC", "DEF", 1, "2026-07-20T12:00:00+00:00"),
                    # Also a skill player so the board still works for non-DEF
                    (1, "Alias Receiver", "nfl", "LAR", "WR", 1, "2026-07-20T12:00:00+00:00"),
                ],
            )
            # Skill player game logs
            for week in range(1, 17):
                connection.execute(
                    "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?,?)",
                    (1, "nfl", 2025, str(week), f"2025_{week:02d}_LA_SF", "REG", "LA",
                     '{"fpts_ppr": 20.0, "xfpts_ppr": 18.0, "off_pct": 0.9, "target_share": 0.25}'),
                )
            # D/ST stats for 2025: Seattle played 17 weeks
            for week in range(1, 18):
                connection.execute(
                    "INSERT INTO nfl_dst_stats VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (101, 2025, week, 2, 1, 0, 0, 1, 0, 0, 17, 10.0),
                )
            # Kansas City only 8 weeks (partial season data)
            for week in range(1, 9):
                connection.execute(
                    "INSERT INTO nfl_dst_stats VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (102, 2025, week, 3, 0, 0, 0, 0, 0, 0, 21, 3.0),
                )
            # ADP for one D/ST
            connection.execute(
                "INSERT INTO nfl_adp VALUES(101,2026,120.0,85.0)"
            )
            # Schedule for team weeks
            for week in range(1, 18):
                connection.execute(
                    "INSERT INTO nfl_schedule VALUES(?,?,?,?,?)",
                    (f"2025_{week:02d}_SEA_OPP", 2025, week, "SEA", "OPP"),
                )
                connection.execute(
                    "INSERT INTO nfl_schedule VALUES(?,?,?,?,?)",
                    (f"2025_{week:02d}_KC_OPP", 2025, week, "KC", "OPP"),
                )
            connection.execute(
                "INSERT INTO team_stats_coverage VALUES(?,?,?,?,?,?,?)",
                ("run", "nfl", 2025, "complete", 32, 272, "2026-07-14T21:22:17Z"),
            )

        self.original_db = nfl_offseason._db
        self.original_today = nfl_offseason._today
        nfl_offseason._db = lambda: sqlite3.connect(self.db_path)
        nfl_offseason._today = lambda: dt.date(2026, 7, 21)

    def tearDown(self):
        nfl_offseason._db = self.original_db
        nfl_offseason._today = self.original_today
        os.unlink(self.db_path)

    def board(self, position=None, sort="adp", q=None, limit=50, offset=0):
        return nfl_offseason.nfl_draft_board(
            position=position, sort=sort, q=q, limit=limit, offset=offset,
        )

    def test_board_includes_def_players(self):
        payload = self.board()
        positions = {p["position"] for p in payload["players"]}
        self.assertIn("DEF", positions)

    def test_board_filters_def_position(self):
        payload = self.board(position="DEF")
        self.assertEqual(payload["position"], "DEF")
        # Only two DEF players in the DB
        self.assertGreaterEqual(payload["eligible_players"], 2)
        for player in payload["players"]:
            self.assertEqual(player["position"], "DEF")

    def test_dst_player_has_dst_fields_and_no_ppr_fields(self):
        payload = self.board(position="DEF")
        dst_players = {p["name"]: p for p in payload["players"]}

        seattle = dst_players["Seattle Seahawks D/ST"]
        self.assertIsNotNone(seattle["dst_pts_per_game"])
        self.assertIsNotNone(seattle["dst_pts_total"])
        # PPR fields should be absent for DEF
        self.assertIsNone(seattle["ppr_per_game_played"])
        self.assertIsNone(seattle["ppr_per_team_game"])
        self.assertIsNone(seattle["xfp_per_game"])
        self.assertIsNone(seattle["snap_pct"])
        self.assertIsNone(seattle["target_share"])

    def test_dst_seattle_full_season_has_correct_games(self):
        payload = self.board(position="DEF")
        dst_players = {p["name"]: p for p in payload["players"]}

        seattle = dst_players["Seattle Seahawks D/ST"]
        self.assertEqual(seattle["games_played"], 17)
        self.assertEqual(seattle["team_games"], 17)
        self.assertEqual(seattle["sample"], "full")
        # 17 weeks × 10.0 pts = 170 total
        self.assertEqual(seattle["dst_pts_per_game"], 10.0)
        self.assertEqual(seattle["dst_pts_total"], 170.0)

    def test_dst_kc_partial_season_has_correct_games(self):
        payload = self.board(position="DEF")
        dst_players = {p["name"]: p for p in payload["players"]}

        kc = dst_players["Kansas City Chiefs D/ST"]
        self.assertEqual(kc["games_played"], 8)
        # 8 weeks × 3.0 pts = 24 total
        self.assertEqual(kc["dst_pts_per_game"], 3.0)
        self.assertEqual(kc["dst_pts_total"], 24.0)
        self.assertEqual(kc["sample"], "full")

    def test_dst_thin_sample_when_under_4_games(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM nfl_dst_stats WHERE player_id=102 AND week > 2")
        payload = self.board(position="DEF")
        dst_players = {p["name"]: p for p in payload["players"]}
        kc = dst_players["Kansas City Chiefs D/ST"]
        self.assertEqual(kc["games_played"], 2)
        self.assertEqual(kc["sample"], "thin")

    def test_dst_sort_by_dst_pts_per_game(self):
        payload = self.board(position="DEF", sort="dst_pts_per_game")
        self.assertGreaterEqual(len(payload["players"]), 2)
        # Seattle (10.0) should sort before Kansas City (3.0) — both descending
        names = [p["name"] for p in payload["players"]]
        self.assertEqual(names[0], "Seattle Seahawks D/ST")

    def test_dst_no_sample_when_no_dst_stats(self):
        # Delete all D/ST stats — players become "none" sample
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM nfl_dst_stats")
        # A D/ST player without stats and without ADP should not appear
        payload = self.board()
        names = [p["name"] for p in payload["players"]]
        # Seattle has ADP (120.0), KC has no ADP
        self.assertIn("Seattle Seahawks D/ST", names)
        self.assertNotIn("Kansas City Chiefs D/ST", names)

    def test_dst_no_adp_no_stats_is_absent(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM nfl_dst_stats")
            con.execute("DELETE FROM nfl_adp WHERE player_id=101")
        payload = self.board()
        names = [p["name"] for p in payload["players"]]
        self.assertNotIn("Seattle Seahawks D/ST", names)
        self.assertNotIn("Kansas City Chiefs D/ST", names)

    def test_skill_player_unaffected_by_dst_changes(self):
        """Ensure the WR player still works normally."""
        payload = self.board(position="WR")
        self.assertEqual(payload["position"], "WR")
        self.assertGreaterEqual(payload["eligible_players"], 1)
        wr = {p["name"]: p for p in payload["players"]}["Alias Receiver"]
        self.assertEqual(wr["position"], "WR")
        self.assertEqual(wr["ppr_per_game_played"], 20.0)
        self.assertIsNone(wr["dst_pts_per_game"])


class DstIngestResolutionTests(unittest.TestCase):
    """Tests for _build_dst_resolutions — the fail-closed pre-validation step."""

    def _make_entity(self, pro_team_id, adp=100.0, default_position_id=16):
        return {
            "defaultPositionId": default_position_id,
            "proTeamId": pro_team_id,
            "fullName": f"Team{pro_team_id} D/ST",
            "ownership": {"averageDraftPosition": adp,
                          "percentOwned": 90.0, "percentStarted": 5.0},
            "draftRanksByRankType": {},
        }

    def test_resolves_all_32_when_map_is_complete(self):
        """Happy path: 32 entities, complete proTeamMap, all 32 def_to_pid entries."""
        pro_team_map = {i: f"T{i:02d}" for i in range(1, 33)}
        def_to_pid = {f"T{i:02d}": 30093 + i for i in range(1, 33)}
        entities = [self._make_entity(i) for i in range(1, 33)]

        resolutions = ingest_nfl_adp._build_dst_resolutions(
            entities, pro_team_map, def_to_pid
        )
        self.assertEqual(len(resolutions), 32)
        pids = {pid for pid, _, _ in resolutions}
        self.assertEqual(len(pids), 32)

    def test_raises_when_pro_team_map_is_empty(self):
        """proTeamMap with zero entries → RuntimeError."""
        pro_team_map: dict = {}
        def_to_pid = {"T01": 30094}
        entities = [self._make_entity(1)]

        with self.assertRaises(RuntimeError) as ctx:
            ingest_nfl_adp._build_dst_resolutions(entities, pro_team_map, def_to_pid)
        self.assertIn("D/ST preflight", str(ctx.exception))

    def test_raises_when_not_all_32_resolve(self):
        """Only 20 of 32 teams have DEF player entries → RuntimeError."""
        pro_team_map = {i: f"T{i:02d}" for i in range(1, 33)}
        def_to_pid = {f"T{i:02d}": 30093 + i for i in range(1, 21)}  # only 20
        entities = [self._make_entity(i) for i in range(1, 33)]

        with self.assertRaises(RuntimeError) as ctx:
            ingest_nfl_adp._build_dst_resolutions(entities, pro_team_map, def_to_pid)
        self.assertIn("D/ST preflight", str(ctx.exception))

    def test_raises_when_entity_has_unmapped_pro_team_id(self):
        """Entity has proTeamId not in proTeamMap → skips it → fewer than 32."""
        pro_team_map = {i: f"T{i:02d}" for i in range(1, 32)}  # missing 32
        def_to_pid = {f"T{i:02d}": 30093 + i for i in range(1, 33)}
        entities = [self._make_entity(i) for i in range(1, 33)]

        with self.assertRaises(RuntimeError) as ctx:
            ingest_nfl_adp._build_dst_resolutions(entities, pro_team_map, def_to_pid)
        self.assertIn("expected exactly 32", str(ctx.exception))

    def test_ignores_non_def_entities(self):
        """Entities with defaultPositionId != 16 are skipped."""
        pro_team_map = {i: f"T{i:02d}" for i in range(1, 33)}
        def_to_pid = {f"T{i:02d}": 30093 + i for i in range(1, 33)}
        entities = [self._make_entity(1, default_position_id=1)]  # QB entity

        with self.assertRaises(RuntimeError) as ctx:
            ingest_nfl_adp._build_dst_resolutions(entities, pro_team_map, def_to_pid)
        # 0 D/ST resolved → set mismatch
        self.assertIn("expected exactly 32", str(ctx.exception))

    def test_raises_when_resolved_entity_has_null_adp(self):
        """A resolved D/ST with null ADP must be rejected — all 32 need real ADP."""
        pro_team_map = {i: f"T{i:02d}" for i in range(1, 33)}
        def_to_pid = {f"T{i:02d}": 30093 + i for i in range(1, 33)}
        entities = [self._make_entity(i, adp=None) for i in range(1, 33)]
        with self.assertRaises(RuntimeError) as ctx:
            ingest_nfl_adp._build_dst_resolutions(entities, pro_team_map, def_to_pid)
        self.assertIn("expected exactly 32", str(ctx.exception))

    def test_raises_when_def_to_pid_has_33_and_only_32_resolve(self):
        """33 active DEF rows but feed resolves 32 → still a failure."""
        pro_team_map = {i: f"T{i:02d}" for i in range(1, 33)}
        # 33 entries — one extra that won't be in the feed
        def_to_pid = {f"T{i:02d}": 30093 + i for i in range(1, 34)}
        entities = [self._make_entity(i) for i in range(1, 33)]
        with self.assertRaises(RuntimeError) as ctx:
            ingest_nfl_adp._build_dst_resolutions(entities, pro_team_map, def_to_pid)
        self.assertIn("D/ST preflight", str(ctx.exception))


class DstPoolSelectionTests(unittest.TestCase):
    """Tests for the pool builder — DEF-guaranteed selection after job15."""

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        self.con = sqlite3.connect(self.db_path)
        self.con.executescript("""
            CREATE TABLE players(
              id INTEGER PRIMARY KEY, name TEXT, league TEXT,
              team TEXT, position TEXT, active INTEGER);
            CREATE TABLE nfl_adp(
              player_id INTEGER, season INTEGER, adp REAL, percent_owned REAL);
            CREATE TABLE player_game_logs(
              player_id INTEGER, league TEXT, season INTEGER,
              game_no TEXT, team TEXT);
            CREATE TABLE nfl_dst_stats(
              player_id INTEGER, season INTEGER, week INTEGER, fantasy_pts REAL);
            CREATE TABLE nfl_schedule(
              season INTEGER, week INTEGER, home_team TEXT, away_team TEXT);
        """)
        # 32 DEF — MIA and ARI get tier-2 ADP/low ownership so they would
        # be excluded by a global top-300 cap
        _MIA_CODE = "MIA"
        _ARI_CODE = "ARI"
        for i in range(1, 33):
            if i == 14:
                tid, adp, pct = _MIA_CODE, 170.0, 0.5
            elif i == 1:
                tid, adp, pct = _ARI_CODE, 169.5, 0.3
            else:
                tid = f"T{i:02d}"
                adp, pct = 95.0 + i, 85.0 - i * 0.3
            pid = 30093 + i
            self.con.execute(
                "INSERT INTO players VALUES(?,?,?,?,?,?)",
                (pid, f"{tid} D/ST", "nfl", tid, "DEF", 1))
            self.con.execute(
                "INSERT INTO nfl_adp VALUES(?,2026,?,?)",
                (pid, adp, pct))
        # 270 skill players
        for i in range(1, 271):
            pid = i
            self.con.execute(
                "INSERT INTO players VALUES(?,?,?,?,?,?)",
                (pid, f"Player {i}", "nfl", "T01", "RB", 1))
            self.con.execute(
                "INSERT INTO nfl_adp VALUES(?,2026,?,?)",
                (pid, float(i), 99.0))
        # Some game logs for skill players
        for i in range(1, 11):
            for w in range(1, 13):
                self.con.execute(
                    "INSERT INTO player_game_logs VALUES(?,'nfl',2025,?,?)",
                    (i, str(w), "T01"))
        # D/ST stats for team weeks
        for i in range(1, 33):
            tid = f"T{i:02d}"
            for w in range(1, 18):
                self.con.execute(
                    "INSERT INTO nfl_schedule VALUES(2025,?,?,?)",
                    (w, tid, "OPP"))
                self.con.execute(
                    "INSERT INTO nfl_dst_stats VALUES(?,2025,?,10.0)",
                    (30093 + i, w))
        self.con.commit()

        self.orig_db = nfl_mock_draft._DB
        nfl_mock_draft._DB = self.db_path

    def tearDown(self):
        nfl_mock_draft._DB = self.orig_db
        self.con.close()
        os.unlink(self.db_path)

    def _pool_sort_key(self, p):
        """Production sort key from nfl_mock_draft.py."""
        adp = p["adp"]
        return (0 if adp is not None else 1,
                adp if adp is not None else 999999,
                -(p["percent_owned"] or 0),
                p["name"])

    def test_count_300_def_32(self):
        resp = nfl_mock_draft.pool(season=2026)
        body = json.loads(resp.body)
        self.assertEqual(body["count"], 300)
        defs = [p for p in body["players"] if p["position"] == "DEF"]
        self.assertEqual(len(defs), 32)

    def test_mia_ari_survive_despite_tier2(self):
        """MIA and ARI have tier-2 ADP/low ownership — global cap would exclude them."""
        resp = nfl_mock_draft.pool(season=2026)
        body = json.loads(resp.body)
        def_teams = {p["team"] for p in body["players"] if p["position"] == "DEF"}
        self.assertIn("MIA", def_teams, "MIA must survive reserved merge")
        self.assertIn("ARI", def_teams, "ARI must survive reserved merge")

    def test_all_def_adp_non_null(self):
        resp = nfl_mock_draft.pool(season=2026)
        body = json.loads(resp.body)
        for p in body["players"]:
            if p["position"] == "DEF":
                self.assertIsNotNone(p["adp"], f"{p['name']} adp is None")

    def test_no_dst_rank_in_payload(self):
        resp = nfl_mock_draft.pool(season=2026)
        body = json.loads(resp.body)
        for p in body["players"]:
            self.assertNotIn("dst_rank", p)

    def test_full_300_ordering_matches_production_key(self):
        resp = nfl_mock_draft.pool(season=2026)
        body = json.loads(resp.body)
        ids = [p["player_id"] for p in body["players"]]
        expected = sorted(body["players"], key=self._pool_sort_key)
        expected_ids = [p["player_id"] for p in expected]
        self.assertEqual(ids, expected_ids,
            f"Mismatch at idx {next((i for i,(a,b) in enumerate(zip(ids,expected_ids)) if a!=b), -1)}")


class DstB17PlayerDetailTests(unittest.TestCase):
    """B17: player_detail must use nfl_dst_stats for DEF availability."""

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        self.con = sqlite3.connect(self.db_path)
        self.con.executescript("""
            CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, league TEXT,
              team TEXT, position TEXT, active INTEGER);
            CREATE TABLE nfl_adp(player_id INTEGER, season INTEGER, adp REAL,
              percent_owned REAL);
            CREATE TABLE player_game_logs(player_id INTEGER, league TEXT, season INTEGER,
              game_no TEXT, stats TEXT, team TEXT);
            CREATE TABLE nfl_dst_stats(player_id INTEGER, season INTEGER, week INTEGER,
              fantasy_pts REAL);
            CREATE TABLE nfl_schedule(season INTEGER, week INTEGER, home_team TEXT,
              away_team TEXT);
        """)
        self.con.execute("INSERT INTO players VALUES(30116,'SEA D/ST','nfl','SEA','DEF',1)")
        self.con.execute("INSERT INTO nfl_adp VALUES(30116,2026,106.51,98.4)")
        # Dummy log rows so pool team_weeks_map has SEA entry
        for w in range(1, 18):
            self.con.execute("INSERT INTO nfl_dst_stats VALUES(30116,2025,?,10.0)", (w,))
            self.con.execute("INSERT INTO nfl_schedule VALUES(2025,?,?,?)",
                             (w, "SEA", "OPP"))
            self.con.execute("INSERT INTO player_game_logs VALUES(?,?,?,?,?,?)",
                             (9999, 'nfl', 2025, str(w), '{}', 'SEA'))
        self.con.commit()
        self.orig_db = nfl_mock_draft._DB
        nfl_mock_draft._DB = self.db_path

    def tearDown(self):
        nfl_mock_draft._DB = self.orig_db
        self.con.close()
        os.unlink(self.db_path)

    def test_detail_gp_17_from_dst_stats_no_game_logs(self):
        resp = nfl_mock_draft.player_detail(player_id=30116)
        body = json.loads(resp.body)
        self.assertEqual(body["games_played"], 17)
        self.assertEqual(body["games_missed"], 0)
        self.assertEqual(body["sample"], "full")
        self.assertGreater(len(body["weeks_played"]), 0)
        self.assertEqual(body["dst_pts_total"], 170.0)

    def test_detail_matches_pool_field_for_field(self):
        detail = json.loads(nfl_mock_draft.player_detail(player_id=30116).body)
        pool_body = json.loads(nfl_mock_draft.pool(season=2026).body)
        pool_def = [p for p in pool_body["players"] if p["player_id"] == 30116]
        self.assertTrue(pool_def, "SEA not in pool")
        pool = pool_def[0]
        for field in ["games_played", "games_missed", "sample", "weeks_played", "team_weeks"]:
            self.assertEqual(detail[field], pool[field],
                f"{field}: detail={detail[field]} != pool={pool[field]}")


class DstFollowUpTests(DstDraftBoardTests):
    """Follow-up regression: published ADP preserved, filterSlotIds removed.

    Inherits DstDraftBoardTests setUp/tearDown for complete board schema."""

    def setUp(self):
        super().setUp()
        # Add DEF with ADP>=169 and QB with ADP>=169
        con = nfl_offseason._db()
        con.execute("INSERT INTO players VALUES(103,'Late DEF','nfl','ARI','DEF',1,'2026-07-28')")
        con.execute("INSERT INTO nfl_adp VALUES(103,2026,170.0,98.0)")
        for w in range(1, 18):
            con.execute("INSERT INTO nfl_dst_stats VALUES(103,2025,?,2,1,0,0,1,0,0,17,5.0)", (w,))
            con.execute("INSERT INTO nfl_schedule VALUES(?,?,?,?,?)",
                       (f"2025_{w:02d}_ARI_OPP", 2025, w, "ARI", "OPP"))
        con.execute("INSERT INTO players VALUES(2,'Late QB','nfl','SF','QB',1,'2026-07-28')")
        con.execute("INSERT INTO nfl_adp VALUES(2,2026,170.0,50.0)")
        for w in range(1, 13):
            con.execute("INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?,?)",
                       (2, 'nfl', 2025, str(w), f'g{w}', 'REG', 'SF',
                        '{"fpts_ppr":10.0}'))
        con.commit()
        con.close()

    def test_def_adp_ge_169_survives_and_non_null(self):
        """DEF with published ADP >=169 must survive without reclassification."""
        payload = self.board(position="DEF")
        defs = [p for p in payload["players"] if p["position"] == "DEF"]
        self.assertGreaterEqual(len(defs), 1)
        late = [p for p in defs if p["name"] == "Late DEF"]
        self.assertEqual(len(late), 1)
        self.assertEqual(late[0]["adp"], 170.0)

    def test_non_def_published_adp_ge_169_survives(self):
        """A copied non-DEF ADP is not discarded by a reader-side cutoff."""
        payload = self.board(position="QB")
        qbs = [p for p in payload["players"] if p["position"] == "QB"]
        self.assertGreaterEqual(len(qbs), 1)
        late = [p for p in qbs if p["name"] == "Late QB"]
        self.assertEqual(len(late), 1)
        self.assertEqual(late[0]["adp"], 170.0)

    def test_filter_slot_ids_absent_from_headers(self):
        """Both HEADERS and per-page filter omit filterSlotIds."""
        filter_str = ingest_nfl_adp.HEADERS["x-fantasy-filter"]
        self.assertNotIn("filterSlotIds", filter_str)
        import inspect
        src = inspect.getsource(ingest_nfl_adp._fetch_page)
        self.assertNotIn("filterSlotIds", src)


if __name__ == "__main__":
    unittest.main()
