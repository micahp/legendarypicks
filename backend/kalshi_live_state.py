"""Reader for the trade desk's KALSHI_LIVE_STATE.json (written by prediction-market-trading).

Never touches the poller's lock. Every failure returns `available: False` with a reason, so the
panel can say why it has no points; an empty list is never used to mean "poller down".
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path

DEFAULT_PATH = Path("/root/prediction-market-trading/data/orderflow/KALSHI_LIVE_STATE.json")
SCHEMA_VERSION = 2
# The poller sleeps up to 60s when it has no milestones, so a healthy file can be ~64s old.
STALE_AFTER_S = 90
FRESH_UNDER_S = 15
DROP_OVER_S = 60
TOUR_BY_LEAGUE = {"atp": "ATP", "wta": "WTA"}

_cache = {"mtime": None, "body": None}


def _path():
    return Path(os.environ.get("LP_KALSHI_LIVE_STATE") or DEFAULT_PATH)


def _parse(ts):
    return dt.datetime.fromisoformat(ts)


def _unavailable(reason):
    print(f"[kalshi_live_state] unavailable: {reason}", file=sys.stderr, flush=True)
    return {"available": False, "reason": reason, "generated_at": None, "matches": []}


def _load():
    """The file's parsed body, re-read only when its mtime changes."""
    path = _path()
    try:
        mtime = path.stat().st_mtime
    except OSError as exc:
        return None, f"state file missing: {path} ({exc.strerror})"
    if _cache["mtime"] == mtime and _cache["body"] is not None:
        return _cache["body"], None
    try:
        body = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return None, f"state file unreadable: {exc}"
    if body.get("schema_version") != SCHEMA_VERSION:
        return None, f"schema_version {body.get('schema_version')!r}, expected {SCHEMA_VERSION}"
    _cache.update(mtime=mtime, body=body)
    return body, None


def read_live(league, now=None):
    """Live Kalshi points for one tour ("atp" or "wta"), with per-match freshness."""
    tour = TOUR_BY_LEAGUE.get(league.lower())
    if tour is None:
        raise ValueError(f"no Kalshi tennis tour for league {league!r}")
    now = now or dt.datetime.now(dt.timezone.utc)
    body, err = _load()
    if err:
        return _unavailable(err)
    try:
        generated = _parse(body["generated_at"])
    except (KeyError, TypeError, ValueError):
        return _unavailable("state file has no readable generated_at")
    age = (now - generated).total_seconds()
    if age > STALE_AFTER_S:
        return _unavailable(f"poller stale since {generated.strftime('%H:%M:%S')} UTC")
    matches = []
    for m in body.get("matches") or []:
        if m.get("tour") != tour or m.get("finished"):
            continue
        try:
            age_s = (now - _parse(m["polled_at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            continue
        if age_s > DROP_OVER_S:
            continue
        m = dict(m, age_s=round(age_s, 1),
                 freshness="fresh" if age_s < FRESH_UNDER_S else "aging")
        matches.append(m)
    return {"available": True, "reason": None, "generated_at": body["generated_at"], "matches": matches}
