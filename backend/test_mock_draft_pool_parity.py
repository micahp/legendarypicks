#!/usr/bin/env python3

"""Cross-endpoint parity tests for the NFL mock-draft pool payload."""

import json
import os
import sys
import tempfile
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Importing the router initializes its draft tables. Point that side effect at
# a disposable file, then read the canonical data set explicitly in the tests.
_IMPORT_DB = tempfile.NamedTemporaryFile(
    prefix="mock-draft-pool-parity-", suffix=".db", delete=False
)
_IMPORT_DB.close()
_ORIGINAL_LP_DB_PATH = os.environ.get("LP_DB_PATH")
os.environ["LP_DB_PATH"] = _IMPORT_DB.name

from routers import nfl_mock_draft  # noqa: E402

if _ORIGINAL_LP_DB_PATH is None:
    os.environ.pop("LP_DB_PATH", None)
else:
    os.environ["LP_DB_PATH"] = _ORIGINAL_LP_DB_PATH


FIELDS = (
    "team_games",
    "ppr_per_game_played",
    "ppr_per_team_game",
    "xfp_per_game",
    "snap_pct",
    "target_share",
    "pk_pts_total",
    "pk_pts_per_game",
    "dst_pts_total",
    "dst_pts_per_game",
)

# Values measured from the published 2025 data before job16.
EXPECTED = {
    469: {
        "name": "Josh Allen",
        "position": "QB",
        "team_games": 17,
        "ppr_per_game_played": 21.4,
        "ppr_per_team_game": 21.4,
        "xfp_per_game": 20.4,
        "snap_pct": 92.0,
        "target_share": None,
        "pk_pts_total": None,
        "pk_pts_per_game": None,
        "dst_pts_total": None,
        "dst_pts_per_game": None,
    },
    7979: {
        "name": "Jahmyr Gibbs",
        "position": "RB",
        "team_games": 17,
        "ppr_per_game_played": 21.6,
        "ppr_per_team_game": 21.6,
        "xfp_per_game": 18.0,
        "snap_pct": 67.0,
        "target_share": 16.1,
        "pk_pts_total": None,
        "pk_pts_per_game": None,
        "dst_pts_total": None,
        "dst_pts_per_game": None,
    },
    16247: {
        "name": "Puka Nacua",
        "position": "WR",
        "team_games": 17,
        "ppr_per_game_played": 23.4,
        "ppr_per_team_game": 22.1,
        "xfp_per_game": 19.0,
        "snap_pct": 68.0,
        "target_share": 30.1,
        "pk_pts_total": None,
        "pk_pts_per_game": None,
        "dst_pts_total": None,
        "dst_pts_per_game": None,
    },
    11274: {
        "name": "Justin Jefferson",
        "position": "WR",
        "team_games": 17,
        "ppr_per_game_played": 11.9,
        "ppr_per_team_game": 11.9,
        "xfp_per_game": 14.7,
        "snap_pct": 94.0,
        "target_share": 30.7,
        "pk_pts_total": None,
        "pk_pts_per_game": None,
        "dst_pts_total": None,
        "dst_pts_per_game": None,
    },
    14572: {
        "name": "Trey McBride",
        "position": "TE",
        "team_games": 17,
        "ppr_per_game_played": 18.6,
        "ppr_per_team_game": 18.6,
        "xfp_per_game": 17.8,
        "snap_pct": 91.0,
        "target_share": 27.9,
        "pk_pts_total": None,
        "pk_pts_per_game": None,
        "dst_pts_total": None,
        "dst_pts_per_game": None,
    },
    # Aubrey took a fake-punt carry in week 15, so he owns real offensive rows.
    # These two were pinned at 0.0 and 0.8 because job16's spec asked for parity
    # with the player-detail endpoint, and that endpoint leaked them; the
    # research board suppressed all five skill fields and was the correct
    # surface to match. Both endpoints now suppress, so the pin follows.
    882: {
        "name": "Brandon Aubrey",
        "position": "PK",
        "team_games": 17,
        "ppr_per_game_played": None,
        "ppr_per_team_game": None,
        "xfp_per_game": None,
        "snap_pct": None,
        "target_share": None,
        "pk_pts_total": 181.0,
        "pk_pts_per_game": 10.6,
        "dst_pts_total": None,
        "dst_pts_per_game": None,
    },
    30103: {
        "name": "Denver Broncos D/ST",
        "position": "DEF",
        "team_games": 17,
        "ppr_per_game_played": None,
        "ppr_per_team_game": None,
        "xfp_per_game": None,
        "snap_pct": None,
        "target_share": None,
        "pk_pts_total": None,
        "pk_pts_per_game": None,
        "dst_pts_total": 139.0,
        "dst_pts_per_game": 8.2,
    },
}


class MockDraftPoolParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_db = nfl_mock_draft._DB
        repo_db = os.path.join(HERE, "data", "picks.dev.db")
        default_db = (
            repo_db
            if os.path.exists(repo_db)
            else "/root/legendarypicks/backend/data/picks.dev.db"
        )
        cls.db_path = os.environ.get(
            "LP_JOB16_DB_PATH",
            default_db,
        )
        if not os.path.exists(cls.db_path):
            raise unittest.SkipTest(
                f"job16 data set not present at {cls.db_path}"
            )

        nfl_mock_draft._DB = cls.db_path
        cls.pool = json.loads(
            nfl_mock_draft.pool(season=2026).body
        )
        cls.pool_by_id = {
            row["player_id"]: row for row in cls.pool["players"]
        }

    @classmethod
    def tearDownClass(cls):
        nfl_mock_draft._DB = cls.original_db

    def test_literal_expected_values(self):
        for player_id, expected in EXPECTED.items():
            with self.subTest(player_id=player_id):
                row = self.pool_by_id[player_id]
                actual = {
                    "name": row["name"],
                    "position": row["position"],
                    **{field: row[field] for field in FIELDS},
                }
                self.assertEqual(actual, expected)

    def test_pool_matches_player_detail_for_every_position(self):
        player_ids = (469, 7979, 16247, 14572, 882, 30103)
        for player_id in player_ids:
            with self.subTest(player_id=player_id):
                detail = json.loads(
                    nfl_mock_draft.player_detail(player_id=player_id).body
                )
                pool_values = {
                    field: self.pool_by_id[player_id][field]
                    for field in FIELDS
                }
                detail_values = {
                    field: detail[field]
                    for field in FIELDS
                }
                self.assertEqual(pool_values, detail_values)

    def test_position_specific_scoring_guards(self):
        kicker = self.pool_by_id[882]
        defense = self.pool_by_id[30103]
        self.assertIsNotNone(kicker["pk_pts_per_game"])
        self.assertIsNotNone(defense["dst_pts_per_game"])
        self.assertIsNone(defense["ppr_per_game_played"])

    def test_pool_still_has_300_players_and_32_defenses(self):
        self.assertEqual(self.pool["count"], 300)
        defenses = [
            row for row in self.pool["players"]
            if row["position"] == "DEF"
        ]
        self.assertEqual(len(defenses), 32)


if __name__ == "__main__":
    unittest.main()
