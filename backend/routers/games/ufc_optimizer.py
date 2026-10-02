"""Bounded current DraftKings MMA pool discovery through RotoWire.

RotoWire's slate list identifies whether a DraftKings Classic pool exists; its
player and projection endpoints publish the salary pool. The response is cached
briefly and never writes the database.

The two inventories routinely disagree during fight week, and that disagreement
is not an error: the event list says who is fighting, the salary feed says who
is priced, and a late replacement appears in one before the other. A bout the
publisher cancelled, a bout DraftKings has not priced on both sides, and a
priced fighter the publisher places in no bout are each excluded with a count
and served alongside the bouts that are whole. Only genuine ambiguity -- a
duplicate fighter, an event that does not publish two sides, or a slate with
too few usable bouts to fill a lineup -- fails closed.
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
# How old a stored pool may be before a page view goes and gets a new one. The
# scheduled job runs twice a day; this covers the hours in between, when salaries
# and the card still move. Micah's number.
STALE_SECONDS = 4 * 3600
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
    cancelled_fighters = set()
    fighter_event = {}
    for event_id in event_ids:
        event = events.get(event_id)
        if not isinstance(event, dict):
            raise RuntimeError(f"RotoWire slate event {event_id} is missing")
        status = str(event.get("status") or "").upper()
        fighters = [event.get("fighter1"), event.get("fighter2")]
        if any(word in status for word in ("CANCEL", "POSTPON", "SCRATCH")):
            cancelled.append(event_id)
            cancelled_fighters.update(
                str(fighter.get("id")) for fighter in fighters
                if isinstance(fighter, dict) and fighter.get("id")
            )
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

    seen_raw_fighters = set()
    for row in raw_players:
        if not isinstance(row, dict):
            raise RuntimeError("RotoWire player payload contains a non-object")
        fighter_id = str(row.get("rwID") or "")
        assignment_id = str(row.get("slateID") or "")
        if not fighter_id or not assignment_id or fighter_id in seen_raw_fighters:
            raise RuntimeError("RotoWire pool has a missing or duplicate fighter")
        seen_raw_fighters.add(fighter_id)

    priced = {str(row.get("rwID") or ""): row for row in raw_players}

    # The publisher keeps two inventories and they disagree during fight-week
    # churn: a replaced fighter stays priced after he loses his bout, and his
    # replacement is in the bout before DraftKings prices him. Neither case is
    # ambiguous -- the event node is the published statement of who is
    # fighting whom -- so each is excluded WITH A COUNT instead of failing the
    # whole pool. Never pair fighters ourselves; DraftKings salary symmetry is
    # a price, not a matchup.
    unavailable_fighters = []
    unmatched_fighters = []
    for fighter_id, row in priced.items():
        if fighter_id in fighter_event or fighter_id in cancelled_fighters:
            continue
        if str(row.get("injuryStatus") or "").upper() == "OUT":
            unavailable_fighters.append(fighter_id)
        else:
            unmatched_fighters.append(fighter_id)

    # A bout with only one priced fighter cannot be offered. Drop it whole so
    # a half-bout never reaches the board, and keep the rest of the slate.
    unpriced_events = []
    for event_id in list(active_events):
        ids = [str((active_events[event_id].get(side) or {}).get("id") or "")
               for side in ("fighter1", "fighter2")]
        if all(fighter_id in priced for fighter_id in ids):
            continue
        unpriced_events.append(event_id)
        del active_events[event_id]
        for fighter_id in ids:
            fighter_event.pop(fighter_id, None)
    ordered_event_ids = [event_id for event_id in event_ids if event_id in active_events]

    by_event = {event_id: [] for event_id in active_events}
    seen_players = set()
    for row in raw_players:
        fighter_id = str(row.get("rwID") or "")
        assignment_id = str(row.get("slateID") or "")
        event_id = fighter_event.get(fighter_id)
        if not event_id:
            continue
        if fighter_id in seen_players:
            raise RuntimeError("RotoWire pool has a duplicate fighter")
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
            "startTime": (
                _eastern(str(event["eventDate"])).astimezone(dt.timezone.utc).isoformat()
                if event.get("eventDate") else None
            ),
            "country": row.get("countryFlag"), "record": stats.get("record"),
            "age": _number(stats.get("age")), "height": stats.get("height"),
            "reach": stats.get("reach"), "weightClass": stats.get("weightClassLong"),
            "moneyline": odds.get("moneyline"),
        })
    malformed = [event_id for event_id, rows in by_event.items() if len(rows) != 2]
    if malformed:
        raise RuntimeError(f"RotoWire pool does not contain two fighters for events: {','.join(malformed)}")
    fighters = [fighter for event_id in ordered_event_ids for fighter in by_event.get(event_id, [])]
    if len(fighters) < 6:
        raise RuntimeError("RotoWire Classic pool has fewer than six active fighters")
    event_names = sorted({
        str(active_events[event_id].get("eventName") or "UFC")
        for event_id in ordered_event_ids
    })
    title = " / ".join(event_names)
    return {
        "checked_at": now.isoformat(), "reason": None,
        "excluded_cancelled_fights": len(cancelled),
        "excluded_unavailable_fighters": len(unavailable_fighters),
        "excluded_unpriced_fights": len(unpriced_events),
        "excluded_unmatched_fighters": len(unmatched_fighters),
        "slate": {
            "fighters": fighters, "fightCount": len(by_event), "unresolvedMatchups": 0,
            "source": "rotowire_live", "sourceName": f"DraftKings Classic · {title}",
            "sourceUrl": SOURCE_URL, "slateDate": lock_at.date().isoformat(),
            "lockAt": lock_at.astimezone(dt.timezone.utc).isoformat(),
            "capturedAt": now.isoformat(), "metricLabel": "RW projection",
        },
    }


def _stored_pool(now):
    """The last pool `ingest_ufc_dk_pool.py` captured, if it has not locked."""
    try:
        from routers.games import _db as _pkg_db
        from dk_pool_store import read_unlocked
        connection = _pkg_db()
        try:
            return read_unlocked(connection, now=now)
        finally:
            connection.close()
    except Exception as exc:
        # A reader problem must not take the board down when the live path works.
        print(f"[ufc_pool] stored pool unavailable: {type(exc).__name__}: {exc}")
        return None


def _age_seconds(stored, now):
    """Seconds since this pool was captured, or None if it does not say."""
    stamp = (stored or {}).get("stored_captured_at")
    try:
        captured = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=dt.timezone.utc)
    return (now - captured).total_seconds()


def _persist(payload, now):
    """Keep a page-load refresh, so the next reader does not fetch it again.

    Best effort on purpose, and loud about it. The reader already has a good
    pool in hand; failing the request because the write failed would trade a
    working board for a bookkeeping problem.
    """
    try:
        from routers.games import _db as _pkg_db
        from dk_pool_store import ensure_table, publish
        connection = _pkg_db()
        try:
            ensure_table(connection)
            publish(connection, payload, captured_at=now.isoformat())
            connection.commit()
        finally:
            connection.close()
    except Exception as exc:
        print(f"[ufc_pool] could not store refreshed pool: {type(exc).__name__}: {exc}")


@router.get("/api/ufc/draftkings-pool")
def current_draftkings_pool():
    """Serve the captured pool; fetch live only when there is nothing stored.

    The scheduled job owns the publisher call. A page view that has to go out to
    RotoWire is as available as RotoWire is at that instant, which is how one
    bad moment emptied the board. Reading first also means a publisher outage
    degrades to "captured 20 minutes ago" instead of to nothing.
    """
    now = dt.datetime.now(dt.timezone.utc)
    with _lock:
        if _cache["value"] is not None and _cache["expires"] > now.timestamp():
            return _cache["value"]
        stored = _stored_pool(now)
        age = _age_seconds(stored, now) if stored is not None else None
        if stored is not None and age is not None and age <= STALE_SECONDS:
            _cache.update(value=stored, expires=now.timestamp() + CACHE_SECONDS)
            return stored
        try:
            value = build_current_pool(now=now)
        except Exception as exc:
            if stored is not None:
                # A stale pool beats no pool, and it says how stale it is rather
                # than presenting itself as current.
                print(f"[ufc_pool] refresh failed, serving stored pool: "
                      f"{type(exc).__name__}: {exc}")
                _cache.update(value=stored, expires=now.timestamp() + CACHE_SECONDS)
                return stored
            # Say what the publisher did. The previous generic text cost a
            # python REPL to answer "why is the pool empty" every time.
            raise HTTPException(
                502, f"current DraftKings MMA pool could not be verified: {exc}"
            ) from exc
        if value.get("slate"):
            _persist(value, now)
            value = dict(value, stored_captured_at=now.isoformat())
        _cache.update(value=value, expires=now.timestamp() + CACHE_SECONDS)
        return value
