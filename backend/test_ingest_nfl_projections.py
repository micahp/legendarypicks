import sqlite3
import unittest

import ingest_nfl_projections as ingest


class TestNflProjectionProfileFields(unittest.TestCase):
    def test_qbr_parser_uses_machine_names_and_not_passer_rating(self):
        payload = {
            "pagination": {"count": 1, "pages": 1},
            "categories": [{
                "name": "passing",
                "names": ["completionPct", "QBR", "QBRating", "adjQBR"],
            }],
            "athletes": [{
                "athlete": {"id": "3918298"},
                "categories": [{
                    "name": "passing",
                    "values": [69.3, 65.1, 102.2, 65.4],
                }],
            }],
        }

        self.assertEqual(
            ingest._qbr_values(payload),
            {"3918298": {
                "qbr": 65.1,
                "passer_rating": 102.2,
                "adj_qbr": 65.4,
            }},
        )

    def test_selects_published_prior_actual_line_not_prior_projection(self):
        entity = {
            "stats": [
                {
                    "seasonId": 2025,
                    "scoringPeriodId": 0,
                    "statSourceId": 1,
                    "statSplitTypeId": 0,
                    "stats": {"23": 999},
                },
                {
                    "seasonId": 2025,
                    "scoringPeriodId": 0,
                    "statSourceId": 0,
                    "statSplitTypeId": 0,
                    "stats": {"23": 201, "210": 16},
                },
            ]
        }

        self.assertEqual(ingest._actual_stats(entity), {"23": 201, "210": 16})

    def test_preserves_outlook_as_nullable_authored_text(self):
        self.assertEqual(
            ingest._season_outlook({"seasonOutlook": "  Published outlook.  "}),
            "Published outlook.",
        )
        self.assertIsNone(ingest._season_outlook({"seasonOutlook": "   "}))
        self.assertIsNone(ingest._season_outlook({}))

    def test_adds_profile_columns_to_legacy_projection_table(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            """CREATE TABLE nfl_player_projections(
                   player_id INTEGER,
                   season INTEGER,
                   lp_ppr_projected_points REAL
               )"""
        )

        ingest._ensure_profile_columns(connection)

        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(nfl_player_projections)")
        }
        self.assertTrue(
            {
                "season_outlook", "outlook_source", "actual_season",
                "raw_actual_json", "actual_qbr", "actual_passer_rating", "actual_adj_qbr",
                "qbr_source", "qbr_payload_checksum",
            }
            <= columns
        )
        connection.close()

    def test_atomic_publication_removes_rows_from_an_older_snapshot(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            """CREATE TABLE nfl_player_projections(
                   player_id INTEGER,
                   season INTEGER,
                   payload_checksum TEXT
               )"""
        )
        connection.executemany(
            "INSERT INTO nfl_player_projections VALUES(?,?,?)",
            [
                (1, ingest.SEASON, "current"),
                (2, ingest.SEASON, "previous"),
                (3, ingest.SEASON - 1, "previous"),
            ],
        )

        removed = ingest._delete_stale_projection_rows(connection, "current")

        self.assertEqual(1, removed)
        self.assertEqual(
            [(1, ingest.SEASON), (3, ingest.SEASON - 1)],
            connection.execute(
                "SELECT player_id, season FROM nfl_player_projections ORDER BY player_id"
            ).fetchall(),
        )
        connection.close()


if __name__ == "__main__":
    unittest.main()
