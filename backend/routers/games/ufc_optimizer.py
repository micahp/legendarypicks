"""Bounded current DraftKings MMA pool discovery through RotoWire.

RotoWire's slate list identifies whether a DraftKings Classic pool exists; its
player and projection endpoints publish the salary pool. The response is cached
briefly and never writes the database. Cancelled bouts are removed explicitly;
an unexplained one-sided or duplicate bout fails closed.
"""
import datetime as dt
import json
import threading
import urllib.request

from fastapi import APIRouter, HTTPException

router = APIRouter()

BASE = "https://www.rotowire.com/daily/mma/api"
SLATES = BASE + "/slate-list.php?siteID=1"
PLAYERS = BASE + "/players.php?slateID={slate_id}"
PROJECTIONS = BASE + "/projections.php?slateID={slate_id}&projSource=RotoWire"
SOURCE_URL = "https://www.rotowire.com/daily/mma/optimizer.php"
USER_AGENT = "LegendaryPicks/0.9 current-DraftKings-pool"
CACHE_SECONDS = 300
_cache = {"expires": 0.0, "value": None}
_lock = threading.Lock()


def _get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _eastern(value):
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeError("RotoWire timestamp is malformed") from exc
    if parsed.tzinfo is not None:
        return parsed
    # RotoWire publishes these clock fields in ET but managed DEV is Python 3.8
    # (no stdlib zoneinfo). Encode the post-2007 US DST rule explicitly instead
    # of inheriting the host's Chicago timezone or adding an unpinned package.
    march_first = dt.date(parsed.year, 3, 1)
    second_sunday = 8 + (6 - march_first.weekday()) % 7
    november_first = dt.date(parsed.year, 11, 1)
    first_sunday = 1 + (6 - november_first.weekday()) % 7
    dst_start = dt.datetime(parsed.year, 3, second_sunday, 2)
    dst_end = dt.datetime(parsed.year, 11, first_sunday, 2)
    offset = -4 if dst_start <= parsed < dst_end else -5
    return parsed.replace(tzinfo=dt.timezone(dt.timedelta(hours=offset)))


def _number(value, *, required=False):
    if value is None or value == "":
        if required:
            raise RuntimeError("RotoWire player is missing a required number")
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("RotoWire player has a malformed number") from exc
    return int(result) if result.is_integer() else result


def build_current_pool(now=None, get_json=_get_json):
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    payload = get_json(SLATES)
    if not isinstance(payload, dict) or not isinstance(payload.get("slates"), list):
        raise RuntimeError("RotoWire slate list changed shape")
    events = payload.get("events")
    if not isinstance(events, dict):
        raise RuntimeError("RotoWire slate list has no event inventory")

    candidates = []
    for slate in payload["slates"]:
        if not isinstance(slate, dict) or slate.get("contestType") != "Classic":
            continue
        try:
            lock_at = _eastern(str(slate["startDate"]))
            slate_id = int(slate["slateID"])
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("RotoWire Classic slate is missing its ID or lock time")
        if lock_at > now:
            candidates.append((lock_at, slate_id, slate))
    if not candidates:
        return {"slate": None, "checked_at": now.isoformat(), "reason": "no_unlocked_classic_pool"}
    lock_at, slate_id, slate_meta = min(candidates, key=lambda item: item[0])

    event_ids = [str(value) for value in slate_meta.get("events") or []]
    if not event_ids:
        raise RuntimeError("RotoWire Classic slate has no events")
    active_events = {}
    cancelled = []
    fighter_event = {}
    for event_id in event_ids:
        event = events.get(event_id)
        if not isinstance(event, dict):
            raise RuntimeError(f"RotoWire slate event {event_id} is missing")
        status = str(event.get("status") or "").upper()
        fighters = [event.get("fighter1"), event.get("fighter2")]
        if any(word in status for word in ("CANCEL", "POSTPON", "SCRATCH")):
            cancelled.append(event_id)
            continue
        if any(not isinstance(fighter, dict) or not fighter.get("id") for fighter in fighters):
            raise RuntimeError(f"RotoWire event {event_id} does not publish two fighters")
        ids = [str(fighter["id"]) for fighter in fighters]
        if ids[0] == ids[1] or any(fighter_id in fighter_event for fighter_id in ids):
            raise RuntimeError("RotoWire event inventory reuses a fighter")
        active_events[event_id] = event
        for fighter_id in ids:
            fighter_event[fighter_id] = event_id

    raw_players = get_json(PLAYERS.format(slate_id=slate_id))
    projection_payload = get_json(PROJECTIONS.format(slate_id=slate_id))
    if not isinstance(raw_players, list) or not isinstance(projection_payload, dict):
        raise RuntimeError("RotoWire pool payload changed shape")
    raw_projections = projection_payload.get("projections")
    if not isinstance(raw_projections, list):
        raise RuntimeError("RotoWire projection payload has no projections")
    projections = {}
    for row in raw_projections:
        key = str(row.get("slateID") or "") if isinstance(row, dict) else ""
        if not key or key in projections:
            raise RuntimeError("RotoWire projections have missing or duplicate slate IDs")
        projections[key] = _number(row.get("pts"))

    by_event = {event_id: [] for event_id in active_events}
    seen_players = set()
    for row in raw_players:
        if not isinstance(row, dict):
            raise RuntimeError("RotoWire player payload contains a non-object")
        fighter_id = str(row.get("rwID") or "")
        assignment_id = str(row.get("slateID") or "")
        event_id = fighter_event.get(fighter_id)
        if not event_id:
            # A player left in the salary pool after a publisher-marked
            # cancellation is excluded with that bout, never remapped by name.
            if any(fighter_id in {
                str((events[eid].get("fighter1") or {}).get("id") or ""),
                str((events[eid].get("fighter2") or {}).get("id") or ""),
            } for eid in cancelled):
                continue
            raise RuntimeError(f"RotoWire pool fighter {fighter_id or '?'} has no active event")
        if not assignment_id or fighter_id in seen_players:
            raise RuntimeError("RotoWire pool has a missing or duplicate fighter")
        seen_players.add(fighter_id)
        event = active_events[event_id]
        pair = [str(event[side]["id"]) for side in ("fighter1", "fighter2")]
        opponent_id = pair[1] if pair[0] == fighter_id else pair[0]
        stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
        odds = row.get("odds") if isinstance(row.get("odds"), dict) else {}
        projection = projections.get(assignment_id)
        name = " ".join(part for part in (row.get("firstName"), row.get("lastName")) if part)
        if not name:
            raise RuntimeError(f"RotoWire pool fighter {fighter_id} has no name")
        by_event[event_id].append({
            "id": f"rw:{fighter_id}",
            "name": name,
            "salary": _number(row.get("salary"), required=True),
            "fppg": projection, "target": projection,
            "gameInfo": f"rw-event:{event_id}", "opponentId": f"rw:{opponent_id}",
            "startTime": _eastern(str(event["eventDate"])).astimezone(dt.timezone.utc).isoformat(),
            "country": row.get("countryFlag"), "record": stats.get("record"),
            "age": _number(stats.get("age")), "height": stats.get("height"),
            "reach": stats.get("reach"), "weightClass": stats.get("weightClassLong"),
            "moneyline": odds.get("moneyline"),
        })
    malformed = [event_id for event_id, rows in by_event.items() if len(rows) != 2]
    if malformed:
        raise RuntimeError(f"RotoWire pool does not contain two fighters for events: {','.join(malformed)}")
    fighters = [fighter for event_id in event_ids for fighter in by_event.get(event_id, [])]
    if len(fighters) < 6:
        raise RuntimeError("RotoWire Classic pool has fewer than six active fighters")
    event_names = sorted({str(active_events[event_id].get("eventName") or "UFC") for event_id in active_events})
    title = " / ".join(event_names)
    return {
        "checked_at": now.isoformat(), "reason": None,
        "excluded_cancelled_fights": len(cancelled),
        "slate": {
            "fighters": fighters, "fightCount": len(by_event), "unresolvedMatchups": 0,
            "source": "rotowire_live", "sourceName": f"DraftKings Classic · {title}",
            "sourceUrl": SOURCE_URL, "slateDate": lock_at.date().isoformat(),
            "capturedAt": now.isoformat(), "metricLabel": "RW projection",
        },
    }


@router.get("/api/ufc/draftkings-pool")
def current_draftkings_pool():
    now = dt.datetime.now(dt.timezone.utc)
    with _lock:
        if _cache["value"] is not None and _cache["expires"] > now.timestamp():
            return _cache["value"]
        try:
            value = build_current_pool(now=now)
        except Exception as exc:
            raise HTTPException(502, "current DraftKings MMA pool could not be verified") from exc
        _cache.update(value=value, expires=now.timestamp() + CACHE_SECONDS)
        return value
