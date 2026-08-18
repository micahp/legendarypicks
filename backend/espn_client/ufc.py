"""espn_client.ufc -- fighter resolution and fight history.

`ufc_athlete` resolves a (possibly clipped) fighter name to an ESPN athlete id
from nearby UFC cards; `ufc_fight_history` reads a fighter's most-recent
completed results from the core-API competition/status objects (resolved in
parallel, each cached six hours by the shared client cache).

Shared calls (`_get`, `games`) resolve through the `espn_client` package at
call time so monkeypatching `espn_client._get` (as test_settlement_ufc_mls
does) keeps working.
"""
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import espn_client


def _athlete_name_key(name):
    value = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _athlete_name_parts(name):
    value = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii")
    return re.findall(r"[a-z0-9]+", value.lower())


def ufc_athlete(name, date=None):
    """Resolve a fighter name to ESPN's athlete id from a nearby UFC card.

    Prop-ingested UFC names are occasionally clipped at the end, so resolution
    prefers an exact normalized match and permits a unique 7+ character prefix.
    The date neighborhood handles cards whose early prelims and main card cross
    midnight UTC.
    """
    import datetime as _dt
    candidates = []
    if date:
        try:
            base = _dt.datetime.strptime(str(date)[:10], "%Y-%m-%d").date()
            candidates.extend((base, base - _dt.timedelta(days=1), base + _dt.timedelta(days=1)))
        except (TypeError, ValueError):
            pass
    candidates.append(None)

    fighters = {}
    seen_dates = set()
    for candidate in candidates:
        date_text = candidate.isoformat() if candidate is not None else None
        if date_text in seen_dates:
            continue
        seen_dates.add(date_text)
        try:
            card = espn_client.games("ufc", date_text)
        except Exception:
            continue
        for fight in card:
            for side in ("home", "away"):
                fighter = fight.get(side) or {}
                athlete_id = str(fighter.get("id") or "")
                fighter_name = fighter.get("name") or ""
                if athlete_id and fighter_name:
                    fighters[athlete_id] = {"id": athlete_id, "name": fighter_name}

    target = _athlete_name_key(name)
    exact = [fighter for fighter in fighters.values() if _athlete_name_key(fighter["name"]) == target]
    if len(exact) == 1:
        return exact[0]
    if len(target) < 7:
        return None
    prefix = [
        fighter for fighter in fighters.values()
        if target.startswith(_athlete_name_key(fighter["name"]))
        or _athlete_name_key(fighter["name"]).startswith(target)
    ]
    if len(prefix) == 1:
        return prefix[0]

    # A source may include a middle name omitted by the prop feed ("Jose
    # Delgado" vs "Jose Miguel Delgado"). First + last must both match and the
    # candidate must be unique on the nearby card.
    target_parts = _athlete_name_parts(name)
    if len(target_parts) < 2:
        return None
    first_last = []
    for fighter in fighters.values():
        parts = _athlete_name_parts(fighter["name"])
        if len(parts) >= 2 and parts[0] == target_parts[0] and parts[-1] == target_parts[-1]:
            first_last.append(fighter)
    return first_last[0] if len(first_last) == 1 else None


def _ufc_method(result):
    raw = " ".join(str((result or {}).get(key) or "") for key in (
        "name", "displayName", "shortDisplayName"
    )).lower()
    if "submission" in raw or re.search(r"\bsub\b", raw):
        return "SUB"
    if "knockout" in raw or "tko" in raw or re.search(r"\bko\b", raw):
        return "KO/TKO"
    if "decision" in raw or re.search(r"\bdec\b", raw):
        return "DEC"
    if "disqualification" in raw or re.search(r"\bdq\b", raw):
        return "DQ"
    if "no contest" in raw:
        return "NC"
    return (result or {}).get("shortDisplayName") or "—"


def ufc_fight_history(athlete_id, limit=5):
    """Return a fighter's most-recent completed UFC results from ESPN.

    ESPN's athlete overview returns five compact fight references. Resolve the
    referenced competition, status/result method, and opponent in parallel;
    each upstream object is cached for six hours by the shared client cache.
    """
    athlete_id = str(athlete_id)
    overview = espn_client._get(
        espn_client._COMMON.format(path="mma/ufc") + f"/athletes/{athlete_id}/overview",
        ttl=21600,
    )
    references = []
    for item in overview.get("fightHistory", []):
        uid = item if isinstance(item, str) else (item or {}).get("uid", "")
        match = re.search(r"~e:(\d+)~c:(\d+)", uid or "")
        if match:
            references.append((match.group(1), match.group(2)))
        if len(references) >= max(1, min(int(limit), 5)):
            break

    def safe_get(url):
        try:
            return espn_client._get(url, ttl=21600)
        except Exception:
            return {}

    objects = {}
    jobs = []
    for event_id, fight_id in references:
        base = (
            espn_client._SPORTS_CORE.format(sport="mma")
            + f"/leagues/ufc/events/{event_id}/competitions/{fight_id}"
        )
        jobs.append(((fight_id, "competition"), base + "?lang=en&region=us"))
        jobs.append(((fight_id, "status"), base + "/status?lang=en&region=us"))
    with ThreadPoolExecutor(max_workers=min(10, max(1, len(jobs)))) as pool:
        futures = [(key, pool.submit(safe_get, url)) for key, url in jobs]
        for key, future in futures:
            objects[key] = future.result()

    opponent_ids = set()
    for _, fight_id in references:
        competition = objects.get((fight_id, "competition"), {})
        opponent_ids.update(
            str(row.get("id")) for row in competition.get("competitors", [])
            if row.get("id") is not None and str(row.get("id")) != athlete_id
        )

    opponent_names = {}
    with ThreadPoolExecutor(max_workers=min(5, max(1, len(opponent_ids)))) as pool:
        futures = {
            opponent_id: pool.submit(
                safe_get,
                espn_client._SPORTS_CORE.format(sport="mma")
                + f"/athletes/{opponent_id}?lang=en&region=us",
            )
            for opponent_id in opponent_ids
        }
        for opponent_id, future in futures.items():
            athlete = future.result()
            opponent_names[opponent_id] = (
                athlete.get("displayName") or athlete.get("fullName") or "Opponent"
            )

    fights = []
    for event_id, fight_id in references:
        competition = objects.get((fight_id, "competition"), {})
        status = objects.get((fight_id, "status"), {})
        if (status.get("type") or {}).get("state") != "post":
            continue
        competitors = competition.get("competitors", [])
        fighter = next((row for row in competitors if str(row.get("id")) == athlete_id), None)
        opponent = next((row for row in competitors if str(row.get("id")) != athlete_id), None)
        if not fighter or not opponent:
            continue
        if fighter.get("winner") is True:
            outcome = "W"
        elif opponent.get("winner") is True:
            outcome = "L"
        else:
            result_text = str((status.get("result") or {}).get("displayName") or "").lower()
            outcome = "D" if "draw" in result_text else "NC"
        opponent_id = str(opponent.get("id") or "")
        # round/clock: ESPN's status object for a "post" (final) competition reports the
        # round the fight ended in (period) and elapsed time within that round (clock,
        # seconds; displayClock, "M:SS") -- already being fetched here for method/result,
        # just never read. UFC rounds are a fixed 5 minutes, so total fight time =
        # (round - 1) * 300 + clock_seconds.
        round_num = status.get("period")
        clock_seconds = status.get("clock")
        fight_time_seconds = (
            (round_num - 1) * 300 + clock_seconds
            if isinstance(round_num, int) and isinstance(clock_seconds, (int, float))
            else None
        )
        fights.append({
            "result": outcome,
            "method": _ufc_method(status.get("result") or {}),
            "opponent": opponent_names.get(opponent_id, "Opponent"),
            "date": str(competition.get("date") or "")[:10],
            "event_id": event_id,
            "fight_id": fight_id,
            "round": round_num,
            "clock_display": status.get("displayClock"),
            "fight_time_seconds": fight_time_seconds,
        })
    fights.sort(key=lambda row: row["date"], reverse=True)
    return fights[:limit]
