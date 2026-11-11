"""Grounded story candidates for a pregame preview.

Each candidate is a dict with a claim sentence, its strength, and the evidence
it rests on. Every item is checked against the pregame cutoff (as_of) first.
Anything stamped after as_of is ignored, so later facts cannot leak in.

Pure functions. No I/O.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
STATUS_WORDS = ("out", "doubtful", "questionable", "probable")
_NUMBER_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
}
_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd"}


def parse_utc(value: str) -> datetime:
    return datetime.strptime(value, TIME_FORMAT).replace(tzinfo=timezone.utc)


def before_cutoff(item: Dict[str, Any], as_of: str) -> bool:
    return parse_utc(item["ts"]) <= parse_utc(as_of)


def visible(items: List[Dict[str, Any]], as_of: str) -> List[Dict[str, Any]]:
    return [item for item in items if before_cutoff(item, as_of)]


def _word(n: int) -> str:
    return _NUMBER_WORDS.get(n, str(n))


def _ordinal(n: int) -> str:
    if n in _ORDINALS:
        return _ORDINALS[n]
    if 10 <= n % 100 <= 20:
        return "{}th".format(n)
    return "{}{}".format(n, {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def _streak(letters: List[str]) -> tuple:
    """(kind, length) of the run at the end of a chronological W/L list."""
    if not letters:
        return None, 0
    kind = letters[-1]
    length = 0
    for letter in reversed(letters):
        if letter != kind:
            break
        length += 1
    return kind, length


def _opening_losses(letters: List[str]) -> int:
    count = 0
    for letter in letters:
        if letter != "L":
            break
        count += 1
    return count


def team_momentum(team: str, results: List[Dict[str, Any]],
                  as_of: str) -> Optional[Dict[str, Any]]:
    """A streak of 3 or more, with the opening stretch when it matters."""
    rows = sorted(visible(results, as_of), key=lambda r: r["date"])
    letters = [r["result"] for r in rows]
    kind, length = _streak(letters)
    if length < 3:
        return None
    word = "won" if kind == "W" else "lost"
    opening = _opening_losses(letters)
    if kind == "W" and opening >= 3 and opening + length == len(letters):
        claim = ("{} lost their opening {} games and have won {} straight"
                 .format(team, _word(opening), _word(length)))
    else:
        opening = 0
        claim = "{} have {} {} straight".format(team, word, _word(length))
    return {
        "kind": "team_momentum",
        "id": "momentum:{}".format(team),
        "team": team,
        "claim": claim,
        "strength": min(0.9, 0.3 + 0.06 * length),
        "streak_kind": kind,
        "streak_length": length,
        "opening_losses": opening,
        "sample_games": len(letters),
        "evidence": [{"id": "result:{}:{}".format(team, r["date"]),
                      "ts": r["ts"]} for r in rows],
    }


def emerging_player(player_id: str, player: Dict[str, Any],
                    as_of: str) -> Optional[Dict[str, Any]]:
    """A recent scoring run. Draft claims need a draft record. None is not 'undrafted'."""
    logs = sorted(visible(player.get("game_logs", []), as_of),
                  key=lambda g: g["date"])
    if len(logs) < 3:
        return None
    last3 = logs[-3:]
    points = [g["points"] for g in last3]
    if max(points) < 30 and sum(points) / 3.0 < 20:
        return None
    name = player["name"]
    claim = "{} scored {}, {} and {} points in his last three games".format(
        name, points[0], points[1], points[2])
    evidence = [{"id": "log:{}:{}".format(player_id, g["date"]),
                 "ts": g["ts"]} for g in last3]
    draft = player.get("draft")
    draft_overall = None
    extra: List[str] = []
    if draft and draft.get("ts") and before_cutoff(draft, as_of):
        draft_overall = draft.get("overall")
        if draft_overall:
            extra.append("{} was the {} overall pick in the {} draft".format(
                name, _ordinal(draft_overall), draft["year"]))
            evidence.append({"id": "draft:{}".format(player_id),
                             "ts": draft["ts"]})
    return {
        "kind": "emerging_player",
        "id": "player:{}".format(player_id),
        "player_id": player_id,
        "name": name,
        "claim": claim,
        "extra_sentences": extra,
        "strength": 0.7 if max(points) >= 30 else 0.6,
        "points": points,
        "draft_overall": draft_overall,
        "evidence": evidence,
    }


def national_broadcast(broadcast: Optional[Dict[str, Any]],
                       as_of: str) -> Optional[Dict[str, Any]]:
    """Only a national telecast may be called national. Regional gets no claim."""
    if not broadcast or not before_cutoff(broadcast, as_of):
        return None
    if broadcast.get("national") is not True:
        return None
    network = broadcast["network"]
    return {
        "kind": "national_broadcast",
        "id": "broadcast:{}".format(network),
        "claim": "The game is nationally televised on {}".format(network),
        "strength": 0.2,
        "evidence": [{"id": "broadcast:{}".format(network),
                      "ts": broadcast["ts"]}],
    }


def availability(entries: List[Dict[str, Any]], players: Dict[str, Any],
                 as_of: str) -> List[Dict[str, Any]]:
    """Injury statuses known at the cutoff. Never says a player will play."""
    out = []
    for entry in visible(entries, as_of):
        status = entry.get("status")
        player = players.get(entry.get("player_id"))
        if status not in STATUS_WORDS or not player:
            continue  # fail loudly upstream; here an unknown name is simply omitted
        out.append({
            "kind": "lineup_shift",
            "id": "availability:{}".format(entry["player_id"]),
            "player_id": entry["player_id"],
            "claim": "{} is listed as {}".format(player["name"], status),
            "strength": 0.5 if status in ("out", "doubtful") else 0.3,
            "status": status,
            "evidence": [{"id": "availability:{}:{}".format(
                entry["player_id"], entry["ts"]), "ts": entry["ts"]}],
        })
    return out


def candidates_for_game(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every grounded candidate for a bundle, strongest first, then by id."""
    as_of = bundle["as_of"]
    found: List[Dict[str, Any]] = []
    for team, results in sorted(bundle.get("results", {}).items()):
        candidate = team_momentum(team, results, as_of)
        if candidate:
            found.append(candidate)
    players = bundle.get("players", {})
    for player_id in sorted(players):
        candidate = emerging_player(player_id, players[player_id], as_of)
        if candidate:
            found.append(candidate)
    candidate = national_broadcast(bundle.get("broadcast"), as_of)
    if candidate:
        found.append(candidate)
    found.extend(availability(bundle.get("availability", []), players, as_of))
    return sorted(found, key=lambda c: (-c["strength"], c["id"]))
