#!/usr/bin/env python3

import copy
import datetime as dt
import json
import os
import socket
import tempfile
import unittest
from unittest import mock

from routers import plays


UTC = dt.timezone.utc


def _fixture():
    return {
        "schema_version": "plays-board-v1",
        "surface": "curated_plays",
        "mode": "paper_research_only",
        "generated_at": "2026-07-19T12:00:10Z",
        "as_of": "2026-07-19T12:00:00Z",
        "published_at": "2026-07-19T12:00:11Z",
        "timezone": "America/Chicago",
        "freshness_policy": {
            "quote_stale_after_seconds": 90,
            "board_stale_after_seconds": 900,
        },
        "scope": {
            "from": "2026-07-19T07:00:00-05:00",
            "through": "2026-07-19T15:00:00-05:00",
            "label": "Sunday 2026-07-19",
        },
        "risk_definition": "One risk unit is entry price minus stop price.",
        "limitations": ["Research only; no order is placed."],
        "category_status": [
            {
                "category": "mlb",
                "status": "one_conditional_play",
                "note": "No pregame buy; wait for the stated trigger.",
            }
        ],
        "plays": [
            {
                "category": "mlb",
                "ticker": "KXMLBGAME-TEST",
                "title": "Boston to beat Tampa Bay",
                "side": "YES",
                "current_price": 0.54,
                "current_bid": 0.53,
                "current_ask": 0.54,
                "current_bid_depth": 1200.0,
                "current_ask_depth": 2400.0,
                "price_as_of": "2026-07-19T12:00:05Z",
                "entry_price": 0.19,
                "stop_price": 0.0,
                "target_price": 0.57,
                "r_target": 2.0,
                "thesis": "Wait for a reversible discount on the quality side.",
                "entry_condition": "Buy only after the exact live trigger and stabilization.",
                "invalidation": "No entry if the structural game state changes.",
                "exit_rule": "Exit into the comeback repricing.",
                "confidence": "medium_high_if_triggered",
                "resolves_at": "2026-07-19T19:30:00Z",
                "resolves_at_note": "Expected game-resolution window.",
            }
        ],
    }


class PlaysApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "plays_board.json")

    def _write(self, payload=None):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload if payload is not None else _fixture(), handle)

    def test_valid_snapshot_derives_current_state_and_decimal_prices(self):
        self._write()
        result = plays.load_snapshot(
            self.path,
            now=dt.datetime(2026, 7, 19, 12, 0, 30, tzinfo=UTC),
        )

        self.assertEqual("current", result["board_status"])
        self.assertEqual("current", result["plays"][0]["quote_status"])
        self.assertEqual("open_window", result["plays"][0]["event_status"])
        self.assertEqual(0.19, result["plays"][0]["entry_price"])
        self.assertEqual(25, result["plays"][0]["quote_age_seconds"])

    def test_snapshot_becomes_stale_then_archived(self):
        self._write()
        stale = plays.load_snapshot(
            self.path,
            now=dt.datetime(2026, 7, 19, 12, 16, tzinfo=UTC),
        )
        archived = plays.load_snapshot(
            self.path,
            now=dt.datetime(2026, 7, 19, 20, 0, tzinfo=UTC),
        )

        self.assertEqual("stale", stale["board_status"])
        self.assertEqual("stale", stale["plays"][0]["quote_status"])
        self.assertEqual("archived", archived["board_status"])
        self.assertEqual("expired", archived["plays"][0]["event_status"])

    def test_market_status_overrides_estimated_resolution_time(self):
        payload = _fixture()
        payload["plays"][0]["market_status"] = "active"
        self._write(payload)
        still_active = plays.load_snapshot(
            self.path,
            now=dt.datetime(2026, 7, 19, 20, 0, tzinfo=UTC),
        )

        payload["plays"][0]["market_status"] = "finalized"
        payload["plays"][0]["resolves_at"] = "2026-07-20T19:30:00Z"
        self._write(payload)
        finalized = plays.load_snapshot(
            self.path,
            now=dt.datetime(2026, 7, 19, 12, 0, 30, tzinfo=UTC),
        )

        self.assertEqual("open_window", still_active["plays"][0]["event_status"])
        self.assertEqual("expired", finalized["plays"][0]["event_status"])

    def test_missing_snapshot_returns_machine_readable_503(self):
        with mock.patch.dict(os.environ, {"LP_PLAYS_BOARD_PATH": self.path}):
            response = plays.today_plays()
        payload = json.loads(response.body)

        self.assertEqual(503, response.status_code)
        self.assertEqual("no-store", response.headers["cache-control"])
        self.assertEqual("unavailable", payload["board_status"])
        self.assertEqual("snapshot_missing", payload["error_code"])
        self.assertEqual([], payload["plays"])

    def test_malformed_json_and_bad_timestamp_fail_closed(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not-json")
        with self.assertRaisesRegex(plays.SnapshotUnavailable, "failed validation") as malformed:
            plays.load_snapshot(self.path)
        self.assertEqual("snapshot_invalid", malformed.exception.code)

        payload = _fixture()
        payload["as_of"] = "2026-07-19 12:00:00"
        self._write(payload)
        with self.assertRaises(plays.SnapshotUnavailable) as bad_time:
            plays.load_snapshot(self.path)
        self.assertEqual("snapshot_invalid", bad_time.exception.code)

    def test_oversized_snapshot_fails_before_json_parse(self):
        with open(self.path, "wb") as handle:
            handle.seek(plays.MAX_SNAPSHOT_BYTES)
            handle.write(b"x")
        with self.assertRaises(plays.SnapshotUnavailable) as oversized:
            plays.load_snapshot(self.path)
        self.assertEqual("snapshot_too_large", oversized.exception.code)

    def test_non_decimal_price_and_crossed_book_fail_closed(self):
        payload = _fixture()
        payload["plays"][0]["entry_price"] = 19
        self._write(payload)
        with self.assertRaises(plays.SnapshotUnavailable):
            plays.load_snapshot(self.path)

        payload = _fixture()
        payload["plays"][0]["current_bid"] = 0.60
        payload["plays"][0]["current_ask"] = 0.54
        self._write(payload)
        with self.assertRaises(plays.SnapshotUnavailable):
            plays.load_snapshot(self.path)

    def test_unavailable_quote_is_explicit(self):
        payload = _fixture()
        for field in (
            "current_price",
            "current_bid",
            "current_ask",
            "current_bid_depth",
            "current_ask_depth",
            "price_as_of",
        ):
            payload["plays"][0][field] = None
        self._write(payload)
        result = plays.load_snapshot(
            self.path,
            now=dt.datetime(2026, 7, 19, 12, 0, 30, tzinfo=UTC),
        )

        self.assertEqual("unavailable", result["plays"][0]["quote_status"])
        self.assertIsNone(result["plays"][0]["quote_age_seconds"])

    def test_request_path_does_not_attempt_network_access(self):
        self._write()
        with mock.patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("network access is forbidden"),
        ):
            result = plays.load_snapshot(
                self.path,
                now=dt.datetime(2026, 7, 19, 12, 0, 30, tzinfo=UTC),
            )
        self.assertEqual("current", result["board_status"])

    def test_success_route_is_no_store_and_does_not_mutate_file(self):
        payload = _fixture()
        self._write(payload)
        before = copy.deepcopy(payload)
        with mock.patch.dict(os.environ, {"LP_PLAYS_BOARD_PATH": self.path}):
            with mock.patch.object(
                plays.dt,
                "datetime",
                wraps=dt.datetime,
            ) as datetime_mock:
                datetime_mock.now.return_value = dt.datetime(2026, 7, 19, 12, 0, 30, tzinfo=UTC)
                response = plays.today_plays()
        with open(self.path, "r", encoding="utf-8") as handle:
            after = json.load(handle)

        self.assertEqual(200, response.status_code)
        self.assertEqual("no-store", response.headers["cache-control"])
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestTheWidgetUsesTodaysSlate:
    """The morning window is the one nobody looked at.

    `espn.games(league)` with no date returns whatever ESPN is serving, and
    before first pitch that is still last night's finished games. Measured on
    prod 2026-08-19 at 09:50 ET: nine cards, all yesterday's games, all priced
    at 1 cent because their markets had settled, including a team that won 6-0.
    The scoreboard for the same date correctly said `pre` for every one.
    """

    def test_todays_games_come_from_the_store_not_an_undated_call(self, monkeypatch):
        import datetime as dt
        from routers import live_discounts
        import scoreboard_store

        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        monkeypatch.setattr(scoreboard_store, "read",
                            lambda lg, d: {"games": [{"game_id": "X", "state": "pre"}]}
                            if d == today else None)

        def never(*a, **k):
            raise AssertionError("the undated publisher board must not be called")
        monkeypatch.setattr(live_discounts.espn, "games", never)

        games = live_discounts._games_today("mlb")
        assert [g["game_id"] for g in games] == ["X"]

    def test_the_fallback_is_dated_never_undated(self, monkeypatch):
        """A store miss falls back to the publisher WITH a date. An undated call
        is what produced yesterday's games in the first place."""
        import datetime as dt
        from routers import live_discounts
        import scoreboard_store

        monkeypatch.setattr(scoreboard_store, "read", lambda lg, d: None)
        seen = {}

        def capture(league, date=None):
            seen["date"] = date
            return []
        monkeypatch.setattr(live_discounts.espn, "games", capture)

        live_discounts._games_today("mlb")
        assert seen["date"] == dt.datetime.now(dt.timezone.utc).date().isoformat()


class TestAStalePayloadExpires:
    """"A stale payload beats a stack trace" is true for a minute, not a day.

    `hit` in the failure branch is the EXPIRED cache entry. Serving it with no
    age limit meant that once `_build` began failing the widget froze on its
    last good answer permanently: every poll re-entered the branch, the
    timestamp was never refreshed, so it could never go fresh again.
    """

    def test_a_recent_failure_still_serves_the_last_good_answer(self, monkeypatch):
        import time
        from routers import live_discounts as ld
        ld._cache["mlb"] = (time.time() - 60, {"cards": ["old"]})
        monkeypatch.setattr(ld, "_build", lambda lg: (_ for _ in ()).throw(RuntimeError("upstream")))
        out = ld.live_discounts(league="mlb")
        assert out["cards"] == ["old"], "a one-minute hiccup should not blank the widget"

    def test_an_old_failure_reports_instead_of_freezing(self, monkeypatch):
        import time
        from fastapi import HTTPException
        from routers import live_discounts as ld
        ld._cache["mlb"] = (time.time() - 14 * 3600, {"cards": ["yesterday"]})
        monkeypatch.setattr(ld, "_build", lambda lg: (_ for _ in ()).throw(RuntimeError("upstream")))
        try:
            out = ld.live_discounts(league="mlb")
        except HTTPException as exc:
            assert exc.status_code == 502
        else:
            assert out.get("cards") != ["yesterday"], \
                "a 14-hour-old payload must never be served as live"
