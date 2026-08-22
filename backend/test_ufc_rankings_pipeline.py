#!/usr/bin/env python3
import os
import sqlite3
import tempfile
import unittest

from fastapi import HTTPException
from ingest_ufc_rankings import P4P_DIVISIONS, WEIGHT_DIVISIONS, ensure_table, store
from migrate_ufc_rankings_to_prod import promote
from routers import games as games_router
from verify_ufc_rankings import validate_payload


def complete_groups(fighter="Ranked Fighter"):
    return [
        {
            "division": division,
            "champion": "Champion" if division in WEIGHT_DIVISIONS else "",
            "fighters": [{"rank": 1, "name": fighter}],
        }
        for division in sorted(P4P_DIVISIONS | WEIGHT_DIVISIONS)
    ]


class UfcIngestTests(unittest.TestCase):
    def test_incomplete_scrape_does_not_delete_last_good_data(self):
        con = sqlite3.connect(":memory:")
        ensure_table(con)
        con.execute("INSERT INTO ufc_rankings VALUES ('Old',1,'Last Good',0,'old')")
        con.commit()
        with self.assertRaises(ValueError):
            store(con, complete_groups()[:-1], "new")
        self.assertEqual(
            con.execute("SELECT fighter FROM ufc_rankings").fetchall(),
            [("Last Good",)],
        )

    def test_insert_failure_rolls_back_delete(self):
        con = sqlite3.connect(":memory:")
        con.execute(
            "CREATE TABLE ufc_rankings(division TEXT, rank INTEGER, "
            "fighter TEXT CHECK(fighter <> 'Poison'), is_champion INTEGER, captured_at TEXT)"
        )
        con.execute("INSERT INTO ufc_rankings VALUES ('Old',1,'Last Good',0,'old')")
        con.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            store(con, complete_groups("Poison"), "new")
        self.assertEqual(
            con.execute("SELECT fighter FROM ufc_rankings").fetchall(),
            [("Last Good",)],
        )


class UfcPromotionTests(unittest.TestCase):
    def test_promotion_is_idempotent_and_preserves_unrelated_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            dev_path = os.path.join(tmp, "dev.db")
            prod_path = os.path.join(tmp, "prod.db")
            with sqlite3.connect(dev_path) as dev:
                ensure_table(dev)
                store(dev, complete_groups(), "captured")
                source_count = dev.execute("SELECT COUNT(*) FROM ufc_rankings").fetchone()[0]
            with sqlite3.connect(prod_path) as prod:
                prod.execute("CREATE TABLE props(id INTEGER PRIMARY KEY, name TEXT)")
                prod.execute("INSERT INTO props VALUES (1, 'untouched')")

            first_backup, first_count = promote(dev_path, prod_path)
            second_backup, second_count = promote(dev_path, prod_path)

            self.assertTrue(os.path.isfile(first_backup))
            self.assertTrue(os.path.isfile(second_backup))
            self.assertEqual((first_count, second_count), (source_count, source_count))
            with sqlite3.connect(prod_path) as prod:
                self.assertEqual(
                    prod.execute("SELECT COUNT(*) FROM ufc_rankings").fetchone()[0],
                    source_count,
                )
                self.assertEqual(prod.execute("SELECT * FROM props").fetchall(), [(1, "untouched")])

    def test_invalid_source_is_rejected_before_prod_backup_or_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            dev_path = os.path.join(tmp, "dev.db")
            prod_path = os.path.join(tmp, "prod.db")
            with sqlite3.connect(dev_path) as dev:
                ensure_table(dev)
                dev.execute("INSERT INTO ufc_rankings VALUES ('Flyweight',1,'Only',0,'now')")
            with sqlite3.connect(prod_path) as prod:
                prod.execute("CREATE TABLE sentinel(value TEXT)")
                prod.execute("INSERT INTO sentinel VALUES ('safe')")

            with self.assertRaises(ValueError):
                promote(dev_path, prod_path)
            self.assertFalse(any(name.startswith("prod.db.bak-") for name in os.listdir(tmp)))
            with sqlite3.connect(prod_path) as prod:
                self.assertEqual(prod.execute("SELECT * FROM sentinel").fetchall(), [("safe",)])

    def test_champion_only_group_is_rejected_before_backup_or_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            dev_path = os.path.join(tmp, "dev.db")
            prod_path = os.path.join(tmp, "prod.db")
            with sqlite3.connect(dev_path) as dev:
                ensure_table(dev)
                store(dev, complete_groups(), "captured")
                dev.execute(
                    "DELETE FROM ufc_rankings WHERE division='Flyweight' AND is_champion=0"
                )
            with sqlite3.connect(prod_path) as prod:
                prod.execute("CREATE TABLE sentinel(value TEXT)")
                prod.execute("INSERT INTO sentinel VALUES ('safe')")

            with self.assertRaisesRegex(ValueError, "no ranked non-champion rows"):
                promote(dev_path, prod_path)
            self.assertFalse(any(name.startswith("prod.db.bak-") for name in os.listdir(tmp)))
            with sqlite3.connect(prod_path) as prod:
                self.assertEqual(prod.execute("SELECT * FROM sentinel").fetchall(), [("safe",)])

    def test_bad_prod_schema_is_rejected_before_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            dev_path = os.path.join(tmp, "dev.db")
            prod_path = os.path.join(tmp, "prod.db")
            with sqlite3.connect(dev_path) as dev:
                ensure_table(dev)
                store(dev, complete_groups(), "captured")
            with sqlite3.connect(prod_path) as prod:
                prod.execute("CREATE TABLE ufc_rankings(wrong TEXT)")

            with self.assertRaisesRegex(ValueError, "prod ufc_rankings schema mismatch"):
                promote(dev_path, prod_path)
            self.assertFalse(any(name.startswith("prod.db.bak-") for name in os.listdir(tmp)))


class UfcReleaseGateTests(unittest.TestCase):
    def test_gate_requires_both_p4p_lists_and_11_divisions(self):
        payload = {
            "pound_for_pound": {"men": [{"rank": 1}], "women": [{"rank": 1}]},
            "divisions": [{"ranked": [{"rank": 1}]} for _ in range(11)],
        }
        self.assertEqual(validate_payload(payload), (1, 1, 11))
        payload["pound_for_pound"]["women"] = []
        with self.assertRaisesRegex(ValueError, "women's P4P"):
            validate_payload(payload)


class UfcEndpointTests(unittest.TestCase):
    def test_missing_table_returns_503_instead_of_empty_200(self):
        original_db = games_router._db
        try:
            games_router._db = lambda: sqlite3.connect(":memory:")
            with self.assertRaises(HTTPException) as raised:
                games_router.ufc_rankings()
            self.assertEqual(raised.exception.status_code, 503)
            self.assertIn("not been promoted", raised.exception.detail)
        finally:
            games_router._db = original_db

    def test_empty_table_returns_503_instead_of_empty_200(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "empty.db")
            with sqlite3.connect(db_path) as con:
                ensure_table(con)
            original_db = games_router._db
            try:
                games_router._db = lambda: sqlite3.connect(db_path)
                with self.assertRaises(HTTPException) as raised:
                    games_router.ufc_rankings()
                self.assertEqual(raised.exception.status_code, 503)
                self.assertIn("is empty", raised.exception.detail)
            finally:
                games_router._db = original_db

    def test_partial_rankings_return_503(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "partial.db")
            with sqlite3.connect(db_path) as con:
                ensure_table(con)
                store(con, complete_groups(), "captured")
                con.execute(
                    "DELETE FROM ufc_rankings WHERE division='Flyweight' AND is_champion=0"
                )
            original_db = games_router._db
            try:
                games_router._db = lambda: sqlite3.connect(db_path)
                with self.assertRaises(HTTPException) as raised:
                    games_router.ufc_rankings()
                self.assertEqual(raised.exception.status_code, 503)
                self.assertIn("is incomplete", raised.exception.detail)
            finally:
                games_router._db = original_db

    def test_complete_rankings_decode_historical_html_entities(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "complete.db")
            with sqlite3.connect(db_path) as con:
                ensure_table(con)
                store(con, complete_groups("Sean O&#039;Malley"), "captured")
            original_db = games_router._db
            try:
                games_router._db = lambda: sqlite3.connect(db_path)
                result = games_router.ufc_rankings()
                self.assertEqual(len(result["divisions"]), 11)
                self.assertEqual(
                    result["pound_for_pound"]["men"][0]["fighter"],
                    "Sean O'Malley",
                )
            finally:
                games_router._db = original_db


if __name__ == "__main__":
    unittest.main()
