import os
import sqlite3
import tempfile

import migrate_publisher_captures
from publisher_capture import capture_payload
import ingest_underdog_props as underdog


def test_migration_and_capture_deduplicate_without_losing_observation_time():
    with tempfile.TemporaryDirectory(prefix="publisher-capture-test-") as directory:
        path = os.path.join(directory, "fixture.db")
        sqlite3.connect(path).close()
        backup, status = migrate_publisher_captures.apply_database(
            path, backup_destination=os.path.join(directory, "before.db")
        )
        assert os.path.isfile(backup)
        assert status.ok
        con = sqlite3.connect(path)
        first, inserted = capture_payload(
            con, source="underdog", league="ufc", endpoint="https://example.test/book",
            payload={"players": [{"id": 7, "name": "A"}]}, captured_at="2026-08-21T00:00:00+00:00",
        )
        second, inserted_again = capture_payload(
            con, source="underdog", league="ufc", endpoint="https://example.test/book",
            payload={"players": [{"name": "A", "id": 7}]}, captured_at="2026-08-21T00:01:00+00:00",
        )
        con.commit()
        row = con.execute(
            "SELECT payload_json, first_captured_at, last_captured_at, capture_count FROM publisher_captures"
        ).fetchone()
        con.close()
        assert (first, inserted, second, inserted_again) == (1, True, 1, False)
        assert row == (
            '{"players":[{"id":7,"name":"A"}]}', "2026-08-21T00:00:00+00:00",
            "2026-08-21T00:01:00+00:00", 2,
        )


def test_capture_refuses_an_unmigrated_database():
    con = sqlite3.connect(":memory:")
    try:
        try:
            capture_payload(con, source="x", league="y", endpoint="z", payload={})
        except Exception as exc:
            assert "not migrated" in str(exc)
        else:
            raise AssertionError("unmigrated capture unexpectedly succeeded")
    finally:
        con.close()


def test_underdog_records_the_full_book_before_it_is_parsed():
    with tempfile.TemporaryDirectory(prefix="publisher-capture-underdog-") as directory:
        path = os.path.join(directory, "fixture.db")
        sqlite3.connect(path).close()
        migrate_publisher_captures.apply_database(path)
        original_db = underdog.DB
        underdog.DB = path
        try:
            capture_id, inserted = underdog.record_publisher_capture(
                {"players": [{"id": "fighter-1", "unparsed_field": {"kept": True}}]},
            )
            assert (capture_id, inserted) == (1, True)
            con = sqlite3.connect(path)
            body = con.execute("SELECT payload_json FROM publisher_captures WHERE id=1").fetchone()[0]
            con.close()
            assert '"unparsed_field":{"kept":true}' in body
        finally:
            underdog.DB = original_db


def test_underdog_dry_run_does_not_open_or_capture_to_a_database():
    capture_id, inserted = underdog.record_publisher_capture({"players": []}, dry_run=True)
    assert (capture_id, inserted) == (None, False)
