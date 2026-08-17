import collections
import os
import sqlite3
import tempfile
import unittest

import ingest_tennis_players as tennis


def ranking_document(league, athletes):
    return {
        "rankings": [{
            "name": league.upper(),
            "ranks": [{"athlete": athlete} for athlete in athletes],
        }]
    }


class TennisSpineTest(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        self.addCleanup(lambda: os.unlink(self.db_path) if os.path.exists(self.db_path) else None)
        with sqlite3.connect(self.db_path) as connection:
            connection.executescript(
                """
                CREATE TABLE players(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    team TEXT,
                    league TEXT NOT NULL,
                    espn_id TEXT,
                    active INTEGER DEFAULT 1,
                    updated_at TEXT,
                    UNIQUE(espn_id, league)
                );
                """
            )

    def _fetcher(self, documents):
        calls = []

        def fetch(url):
            calls.append(url)
            for league in tennis.LEAGUES:
                if f"/tennis/{league}/rankings" in url:
                    return documents[league]
            raise AssertionError(url)

        return fetch, calls

    def test_publishes_publisher_ids_and_verbatim_accents_with_no_team(self):
        documents = {
            "atp": ranking_document("atp", [
                {"id": "100", "displayName": "Jannik Sinner", "active": True},
                {"id": "101", "displayName": "João Fonseca", "active": True},
            ]),
            "wta": ranking_document("wta", [
                {"id": "200", "displayName": "Iga Świątek", "active": True},
            ]),
        }
        fetch, calls = self._fetcher(documents)
        counts = collections.Counter()
        result = tennis.refresh(self.db_path, fetch_json=fetch, request_counts=counts)

        self.assertEqual(2, len(calls))
        self.assertEqual(2, counts[tennis.HOST])
        self.assertEqual(2, result["atp"]["inserted"])
        self.assertEqual(1, result["wta"]["inserted"])
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT name,team,league,espn_id,active FROM players ORDER BY espn_id"
            ).fetchall()
        self.assertEqual([
            ("Jannik Sinner", None, "atp", "100", 1),
            ("João Fonseca", None, "atp", "101", 1),
            ("Iga Świątek", None, "wta", "200", 1),
        ], rows)

    def test_empty_second_league_leaves_first_league_unwritten(self):
        documents = {
            "atp": ranking_document("atp", [
                {"id": "100", "displayName": "Jannik Sinner", "active": True},
            ]),
            "wta": {"rankings": [{"name": "WTA", "ranks": []}]},
        }
        fetch, _ = self._fetcher(documents)

        with self.assertRaisesRegex(tennis.TennisSpineError, "published 0 athletes"):
            tennis.refresh(self.db_path, fetch_json=fetch)
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM players").fetchone()[0])

    def test_duplicate_source_id_fails_before_writing(self):
        document = ranking_document("atp", [
            {"id": "100", "displayName": "Jannik Sinner", "active": True},
            {"id": "100", "displayName": "Different Person", "active": True},
        ])

        with self.assertRaisesRegex(tennis.TennisSpineError, "1 unique ESPN ids for 2"):
            tennis.extract_ranked_athletes(document, "atp")

    def test_name_only_existing_row_is_not_assigned_a_publisher_id(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "INSERT INTO players(name,team,league,espn_id,active) VALUES(?,NULL,'atp',NULL,1)",
                ("Jannik Sinner",),
            )
            connection.commit()
        documents = {
            "atp": ranking_document("atp", [
                {"id": "100", "displayName": "Jannik Sinner", "active": True},
            ]),
        }
        fetch, _ = self._fetcher(documents)

        with self.assertRaisesRegex(tennis.TennisSpineError, "name-only/other-id spine conflicts"):
            tennis.refresh(self.db_path, leagues=("atp",), fetch_json=fetch)
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(
                [("Jannik Sinner", None)],
                connection.execute("SELECT name,espn_id FROM players").fetchall(),
            )

    def test_matching_publisher_id_refreshes_name_and_clears_team(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """INSERT INTO players(name,team,league,espn_id,active,updated_at)
                   VALUES('Iga Swiatek','NOT_A_TEAM','wta','200',0,'old')"""
            )
            connection.commit()
        documents = {
            "wta": ranking_document("wta", [
                {"id": "200", "displayName": "Iga Świątek", "active": True},
            ]),
        }
        fetch, _ = self._fetcher(documents)
        result = tennis.refresh(self.db_path, leagues=("wta",), fetch_json=fetch)

        self.assertEqual(1, result["wta"]["matched"])
        self.assertEqual(1, result["wta"]["refreshed"])
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(
                ("Iga Świątek", None, "200", 1),
                connection.execute(
                    "SELECT name,team,espn_id,active FROM players WHERE league='wta'"
                ).fetchone(),
            )


if __name__ == "__main__":
    unittest.main()
