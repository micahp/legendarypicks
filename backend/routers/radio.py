"""routers/radio.py: which live MLB/NBA cards' radio is a blackout loop right now.

Serves the file radio_blackout_check.py writes (cron every 5 minutes). The scoreboard labels a
card "Blackout" from this. A result older than STALE_S is not served as current: `games` comes
back empty with `stale: true`, so a dead check can never leave old labels on tonight's cards.
"""
import datetime as dt
import json
import os
import pathlib

from fastapi import APIRouter

router = APIRouter()

_FILE = pathlib.Path(os.environ.get(
    "LP_RADIO_BLACKOUTS", pathlib.Path(__file__).resolve().parent.parent / "data" / "radio-blackouts.json"))
STALE_S = 15 * 60


@router.get("/api/radio/blackouts")
def radio_blackouts():
    try:
        d = json.loads(_FILE.read_text())
    except (OSError, ValueError):
        return {"checked_at": None, "stale": True, "games": {}}
    checked = d.get("checked_at")
    try:
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(checked)).total_seconds()
    except (TypeError, ValueError):
        age = None
    if age is None or age > STALE_S:
        return {"checked_at": checked, "stale": True, "games": {}}
    games = {gid: {"team": g.get("team"), "blackout": bool(g.get("blackout"))}
             for gid, g in (d.get("games") or {}).items()}
    return {"checked_at": checked, "stale": False, "games": games}
