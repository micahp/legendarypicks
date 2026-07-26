#!/usr/bin/env python3

import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
from unittest import mock


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Importing the esports package initializes backend modules that honor LP_DB_PATH. Keep any
# import-time database work isolated from the live dev/prod databases.
_TEST_DB = tempfile.NamedTemporaryFile(prefix="esports-streams-", suffix=".db", delete=False)
_TEST_DB.close()
os.environ["LP_DB_PATH"] = _TEST_DB.name

from routers.esports import streams  # noqa: E402


class KickViewerReliabilityTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_TEST_DB.name)
        except FileNotFoundError:
            pass

    def setUp(self):
        streams._live_cache.clear()
        streams._viewer_last_good.clear()
        with streams._kick_snapshot_lock:
            streams._kick_snapshot_cache.clear()
        with streams._kick_viewer_inflight_lock:
            streams._kick_viewer_inflight.clear()
        streams._kick_token_cache.update(token=None, exp=0, failure_status=None)

    @staticmethod
    def _snapshot(*, now=100.0, online=True, viewers=None, broadcaster_user_id=123,
                  failure_kind=None, viewer_retry_at=None):
        return streams._kick_snapshot(
            now,
            online=online,
            viewers=viewers,
            broadcaster_user_id=broadcaster_user_id,
            failure_kind=failure_kind,
            status_code=200,
            viewer_retry_at=viewer_retry_at,
        )

    def test_first_missing_viewer_refreshes_despite_fresh_online_cache(self):
        initial = self._snapshot(
            now=time.time(),
            viewers=None,
            failure_kind="viewer_missing",
        )
        retry = self._snapshot(
            now=time.time(),
            viewers=None,
            failure_kind="viewer_missing",
        )
        fallback = self._snapshot(now=time.time(), viewers=3142)
        candidate = streams._candidate(
            url="https://kick.com/starladder",
            platform="kick",
            channel="starladder",
            attested=True,
            source="fixture",
        )

        with ThreadPoolExecutor(max_workers=1) as executor:
            with ExitStack() as stack:
                stack.enter_context(
                    mock.patch.object(streams, "_get_probe_executor", return_value=executor)
                )
                channels = stack.enter_context(mock.patch.object(
                    streams,
                    "_kick_channel_data",
                    side_effect=[initial, retry],
                ))
                livestreams = stack.enter_context(mock.patch.object(
                    streams,
                    "_kick_user_livestream_data",
                    return_value=fallback,
                ))
                watch = streams._pick_stream([candidate], match_live=True, network_checks=True)

        self.assertIs(watch["online"], True)
        self.assertEqual(3142, watch["viewers"])
        self.assertEqual(2, channels.call_count)
        livestreams.assert_called_once_with("starladder", 123)
        self.assertEqual(3142, streams._kick_cached_snapshot("starladder")["viewers"])

    def test_cache_mode_live_promotion_uses_existing_viewer_sample(self):
        streams._store_kick_snapshot(
            "cct_cs",
            self._snapshot(now=time.time(), viewers=554),
        )
        candidate = streams._candidate(
            url="https://kick.com/cct_cs",
            platform="kick",
            channel="cct_cs",
            source="fixture",
        )

        watch = streams._pick_stream(
            [candidate],
            match_live=False,
            network_checks="cache",
        )

        self.assertIs(watch["online"], True)
        self.assertEqual(554, watch["viewers"])

    def test_cache_mode_first_miss_schedules_refresh_without_waiting(self):
        streams._store_kick_snapshot(
            "nodwin_cs2",
            self._snapshot(
                now=time.time(),
                viewers=None,
                failure_kind="viewer_missing",
            ),
        )
        candidate = streams._candidate(
            url="https://kick.com/nodwin_cs2",
            platform="kick",
            channel="nodwin_cs2",
            source="fixture",
        )
        pending = Future()

        started = time.monotonic()
        with mock.patch.object(
            streams,
            "_submit_kick_viewer_refresh",
            return_value=pending,
        ) as submit:
            watch = streams._pick_stream(
                [candidate],
                match_live=False,
                network_checks="cache",
            )

        self.assertLess(time.monotonic() - started, 0.2)
        self.assertIs(watch["online"], True)
        self.assertIsNone(watch["viewers"])
        submit.assert_called_once_with("nodwin_cs2")

    def test_official_active_livestream_fallback_reads_viewer_count(self):
        response = {
            "data": [{
                "broadcaster_user": {"id": 123},
                "channel": {"slug": "starladder"},
                "viewer_count": 3142,
            }],
        }
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(
                os.environ,
                {"KICK_CLIENT_ID": "client", "KICK_CLIENT_SECRET": "secret"},
            ))
            stack.enter_context(mock.patch.object(streams, "_kick_token", return_value="token"))
            api = stack.enter_context(mock.patch.object(
                streams,
                "_kick_api_json",
                return_value=(response, None, 200),
            ))
            snapshot = streams._kick_user_livestream_data("starladder", 123)

        self.assertEqual(3142, snapshot["viewers"])
        self.assertIs(snapshot["online"], True)
        self.assertEqual(
            f"{streams._KICK_API_USER_LIVESTREAMS}?user_id=123",
            api.call_args.args[0],
        )

    def test_channels_snapshot_keeps_liveness_and_exposes_missing_viewer_reason(self):
        response = {
            "data": [{
                "broadcaster_user_id": 123,
                "stream": {"is_live": True, "viewer_count": None},
            }],
        }
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(
                os.environ,
                {"KICK_CLIENT_ID": "client", "KICK_CLIENT_SECRET": "secret"},
            ))
            stack.enter_context(mock.patch.object(streams, "_kick_token", return_value="token"))
            stack.enter_context(mock.patch.object(
                streams,
                "_kick_api_json",
                return_value=(response, None, 200),
            ))
            diagnostic = stack.enter_context(mock.patch.object(streams, "_kick_log_failure"))
            snapshot = streams._kick_channel_data("starladder")

        self.assertIs(snapshot["online"], True)
        self.assertIsNone(snapshot["viewers"])
        self.assertEqual(123, snapshot["broadcaster_user_id"])
        self.assertEqual("viewer_missing", snapshot["failure_kind"])
        diagnostic.assert_called_once_with("starladder", "viewer_missing", 200)

    def test_channel_without_stream_remains_positively_offline(self):
        response = {"data": [{"broadcaster_user_id": 123, "stream": None}]}
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(
                os.environ,
                {"KICK_CLIENT_ID": "client", "KICK_CLIENT_SECRET": "secret"},
            ))
            stack.enter_context(mock.patch.object(streams, "_kick_token", return_value="token"))
            stack.enter_context(mock.patch.object(
                streams,
                "_kick_api_json",
                return_value=(response, None, 200),
            ))
            stack.enter_context(mock.patch.object(streams, "_kick_log_failure"))
            snapshot = streams._kick_channel_data("offline-channel")

        self.assertIs(snapshot["online"], False)
        self.assertEqual("stream_missing", snapshot["failure_kind"])

    def test_zero_is_a_real_kick_viewer_value(self):
        streams._store_kick_snapshot(
            "hidden-count",
            self._snapshot(now=100, viewers=0),
        )
        with mock.patch.object(streams.time, "time", return_value=100):
            self.assertEqual(
                0,
                streams._viewer_count(
                    {"platform": "kick", "channel": "hidden-count"},
                    confirmed_live=True,
                ),
            )

    def test_transient_miss_returns_recent_last_good(self):
        candidate = {"platform": "kick", "channel": "starladder"}
        streams._store_kick_snapshot(
            "starladder",
            self._snapshot(now=100, viewers=3142),
        )
        with mock.patch.object(streams.time, "time", return_value=100):
            self.assertEqual(3142, streams._viewer_count(candidate, confirmed_live=True))

        streams._store_kick_snapshot(
            "starladder",
            self._snapshot(
                now=110,
                viewers=None,
                failure_kind="viewer_missing",
                viewer_retry_at=110,
            ),
        )
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(streams.time, "time", return_value=110))
            submit = stack.enter_context(mock.patch.object(
                streams,
                "_submit_kick_viewer_refresh",
            ))
            self.assertEqual(3142, streams._viewer_count(candidate, confirmed_live=True))
        submit.assert_not_called()

    def test_last_good_expires_after_fifteen_minutes(self):
        candidate = {"platform": "kick", "channel": "starladder"}
        streams._viewer_last_good["kick:starladder"] = (100, 3142)
        streams._store_kick_snapshot(
            "starladder",
            self._snapshot(
                now=1001,
                viewers=None,
                failure_kind="viewer_missing",
                viewer_retry_at=1001,
            ),
        )
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(streams.time, "time", return_value=1001))
            submit = stack.enter_context(mock.patch.object(
                streams,
                "_submit_kick_viewer_refresh",
            ))
            self.assertIsNone(streams._viewer_count(candidate, confirmed_live=True))
        submit.assert_not_called()

    def test_total_failure_without_history_remains_null(self):
        streams._store_kick_snapshot(
            "starladder",
            self._snapshot(
                now=100,
                viewers=None,
                failure_kind="empty_data",
                viewer_retry_at=100,
            ),
        )
        with mock.patch.object(streams.time, "time", return_value=100):
            self.assertIsNone(
                streams._viewer_count(
                    {"platform": "kick", "channel": "starladder"},
                    confirmed_live=True,
                ),
            )

    def test_failed_viewer_refresh_does_not_erase_known_liveness(self):
        streams._store_kick_snapshot(
            "starladder",
            self._snapshot(
                now=100,
                viewers=None,
                failure_kind="viewer_missing",
                viewer_retry_at=100,
            ),
        )
        primary_failure = self._snapshot(
            now=101,
            online=None,
            viewers=None,
            broadcaster_user_id=None,
            failure_kind="http_error",
        )
        fallback_failure = self._snapshot(
            now=102,
            online=None,
            viewers=None,
            failure_kind="empty_data",
        )
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                streams,
                "_kick_channel_data",
                return_value=primary_failure,
            ))
            stack.enter_context(mock.patch.object(
                streams,
                "_kick_user_livestream_data",
                return_value=fallback_failure,
            ))
            refreshed = streams._refresh_kick_viewer_snapshot("starladder")

        self.assertIs(refreshed["online"], True)
        self.assertEqual("empty_data", refreshed["failure_kind"])

    def test_refreshes_are_deduplicated_per_channel(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def blocked_refresh(channel):
            calls.append(channel)
            started.set()
            release.wait(timeout=1)
            return self._snapshot(now=time.time(), viewers=3142)

        with ThreadPoolExecutor(max_workers=2) as executor:
            with ExitStack() as stack:
                stack.enter_context(
                    mock.patch.object(streams, "_get_probe_executor", return_value=executor)
                )
                stack.enter_context(mock.patch.object(
                    streams,
                    "_refresh_kick_viewer_snapshot",
                    side_effect=blocked_refresh,
                ))
                first = streams._submit_kick_viewer_refresh("starladder")
                self.assertTrue(started.wait(timeout=1))
                second = streams._submit_kick_viewer_refresh("starladder")
                self.assertIs(first, second)
                release.set()
                self.assertEqual(3142, first.result(timeout=1)["viewers"])

        self.assertEqual(["starladder"], calls)

    def test_first_sample_wait_is_bounded(self):
        pending = Future()
        candidate = {"platform": "kick", "channel": "starladder"}
        streams._store_kick_snapshot(
            "starladder",
            self._snapshot(now=time.time(), viewers=None, failure_kind="viewer_missing"),
        )

        started = time.monotonic()
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                streams,
                "_submit_kick_viewer_refresh",
                return_value=pending,
            ))
            stack.enter_context(mock.patch.object(streams, "_KICK_VIEWER_REFRESH_WAIT", 0.001))
            diagnostic = stack.enter_context(mock.patch.object(streams, "_kick_log_failure"))
            self.assertIsNone(streams._viewer_count(candidate, confirmed_live=True))
        self.assertLess(time.monotonic() - started, 0.2)
        diagnostic.assert_called_once_with("starladder", "refresh_timeout")

    def test_twitch_and_youtube_viewer_paths_are_unchanged(self):
        with mock.patch.object(streams, "_twitch_viewer_count", return_value=111) as twitch:
            self.assertEqual(
                111,
                streams._viewer_count({"platform": "twitch", "channel": "example"}),
            )
        twitch.assert_called_once_with("example")

        embed = "https://www.youtube.com/embed/abcdefghijk"
        with mock.patch.object(streams, "yt_viewer_count", return_value=222) as youtube:
            self.assertEqual(
                222,
                streams._viewer_count({"platform": "youtube", "embedUrl": embed}),
            )
        youtube.assert_called_once_with(embed)

    def test_missing_credentials_record_only_safe_failure_metadata(self):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(
                os.environ,
                {"KICK_CLIENT_ID": "", "KICK_CLIENT_SECRET": ""},
            ))
            diagnostic = stack.enter_context(mock.patch.object(streams, "_kick_log_failure"))
            snapshot = streams._kick_channel_data("starladder")

        self.assertEqual("token_unavailable", snapshot["failure_kind"])
        self.assertEqual(
            {
                "fetched_at",
                "online",
                "viewers",
                "broadcaster_user_id",
                "failure_kind",
                "status_code",
                "viewer_retry_at",
            },
            set(snapshot),
        )
        diagnostic.assert_called_once_with("starladder", "token_unavailable", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
