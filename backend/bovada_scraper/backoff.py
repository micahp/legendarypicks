"""backoff — Bovada scraper backoff layer."""
import json
import os
import datetime as dt

from .config import _BACKOFF_HOURS, _BACKOFF_PATH, _EMPTY_RUNS_BEFORE_BACKOFF  # noqa: E402


def _load_backoff() -> dict:
    try:
        with open(_BACKOFF_PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}

def _save_backoff(state: dict):
    try:
        with open(_BACKOFF_PATH, "w") as fh:
            json.dump(state, fh, indent=1, sort_keys=True)
    except OSError as exc:  # noqa: BLE001 - never let scheduling state break a scrape
        print(f"  (could not persist backoff state: {exc})")

def _should_fetch(league: str, state: dict):
    """(fetch?, why) — has this league been empty often enough to deserve a rest?

    Fails OPEN. A league with no recorded history is always fetched: this coupon is how we
    DISCOVER that a season started, so refusing to look would make the backoff
    self-fulfilling. Only a league that has actually answered "no board" several times in a
    row gets rested, and only for a few hours.
    """
    entry = state.get(league) or {}
    if (entry.get("empty_runs") or 0) < _EMPTY_RUNS_BEFORE_BACKOFF:
        return True, ""
    last = entry.get("last_empty_at")
    if not last:
        return True, ""
    try:
        when = dt.datetime.fromisoformat(last)
    except ValueError:
        return True, ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    rested = (dt.datetime.now(dt.timezone.utc) - when).total_seconds() / 3600.0
    if rested < _BACKOFF_HOURS:
        return False, (f"no board on the last {entry['empty_runs']} runs; "
                       f"resting {_BACKOFF_HOURS - rested:.1f}h more")
    return True, ""

def _record_result(league: str, state: dict, event_count: int):
    entry = state.setdefault(league, {})
    if event_count:
        entry["empty_runs"] = 0
        entry.pop("last_empty_at", None)
    else:
        entry["empty_runs"] = (entry.get("empty_runs") or 0) + 1
        entry["last_empty_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
