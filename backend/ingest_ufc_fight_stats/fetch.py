"""ESPN network fetchers for UFC fight history, stats, and status."""
from __future__ import annotations

import os
import sys
import time
from typing import List, Optional
from urllib.error import HTTPError, URLError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import espn_client as espn  # noqa: E402

_STATS_URL = (
    espn._SPORTS_CORE.format(sport="mma")
    + "/leagues/ufc/events/{event_id}/competitions/{fight_id}"
    + "/competitors/{competitor_id}/statistics?lang=en&region=us"
)

_STATUS_URL = (
    espn._SPORTS_CORE.format(sport="mma")
    + "/leagues/ufc/events/{event_id}/competitions/{fight_id}"
    + "/status?lang=en&region=us"
)

class SourceUnavailable(RuntimeError):
    """An upstream request failed in a way that must not be treated as no data."""


class StatsPayload(dict):
    """Parsed statistics with the untouched publisher response attached.

    The ingest plan still consumes this as a normal mapping.  Keeping the
    original body alongside it lets the plan retain even an empty-but-valid
    statistics response before deciding that a fighter has no usable stats.
    """

    def __init__(self, values: dict, raw_payload: Optional[dict]):
        super().__init__(values)
        self.raw_payload = raw_payload

def _error_kind(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return "http_{}".format(exc.code)
    if isinstance(exc, URLError):
        return "url_error"
    return type(exc).__name__

def _retry_delay(exc: Exception, attempt: int) -> float:
    if isinstance(exc, HTTPError) and exc.headers:
        raw = exc.headers.get("Retry-After")
        try:
            return min(5.0, max(0.25, float(raw)))
        except (TypeError, ValueError):
            pass
    return 1.0 + attempt

def _retryable(exc: Exception) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code == 429 or 500 <= exc.code <= 599
    return isinstance(exc, URLError)

def fetch_fight_history(athlete_id: str, limit: int, attempts: int = 2) -> List[dict]:
    """Fetch overview history with one bounded retry for transient source errors."""
    last_error: Optional[Exception] = None
    for attempt in range(max(1, attempts)):
        try:
            return espn.ufc_fight_history(athlete_id, limit=limit)
        except Exception as exc:
            last_error = exc
            if attempt + 1 >= attempts or not _retryable(exc):
                break
            time.sleep(_retry_delay(exc, attempt))
    assert last_error is not None
    raise SourceUnavailable("fight_history_{}".format(_error_kind(last_error))) from last_error

def fetch_stats(
    event_id: str,
    fight_id: str,
    competitor_id: str,
    attempts: int = 2,
) -> dict:
    """Return raw per-fight stats; distinguish missing data from source failure."""
    url = _STATS_URL.format(
        event_id=event_id, fight_id=fight_id, competitor_id=competitor_id
    )
    data = None
    last_error: Optional[Exception] = None
    for attempt in range(max(1, attempts)):
        try:
            data = espn._get(url, ttl=21600)
            break
        except HTTPError as exc:
            if exc.code == 404:
                # A 404 has no publisher document to retain.  Do not turn it
                # into an invented empty source body in the capture ledger.
                return StatsPayload({}, None)
            last_error = exc
        except Exception as exc:
            last_error = exc
        if (
            last_error is None
            or attempt + 1 >= attempts
            or not _retryable(last_error)
        ):
            break
        time.sleep(_retry_delay(last_error, attempt))
    if data is None:
        assert last_error is not None
        raise SourceUnavailable("stats_{}".format(_error_kind(last_error))) from last_error
    categories = (data.get("splits") or {}).get("categories") or []
    if not categories:
        return StatsPayload({}, data)
    stats_list = categories[0].get("stats") or []
    values = {
        item["name"]: item.get("value")
        for item in stats_list
        if isinstance(item, dict) and "name" in item
    }
    return StatsPayload(values, data)

def fetch_fight_status(
    event_id: str,
    fight_id: str,
    attempts: int = 2,
) -> dict:
    """Fetch one completed fight status with bounded transient retries."""
    url = _STATUS_URL.format(event_id=event_id, fight_id=fight_id)
    last_error: Optional[Exception] = None
    for attempt in range(max(1, attempts)):
        try:
            return espn._get(url, ttl=21600)
        except Exception as exc:
            last_error = exc
        if attempt + 1 >= attempts or not _retryable(last_error):
            break
        time.sleep(_retry_delay(last_error, attempt))
    assert last_error is not None
    raise SourceUnavailable("fight_status_{}".format(_error_kind(last_error))) from last_error
