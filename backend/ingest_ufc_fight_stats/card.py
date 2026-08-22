"""Resolve UFC fighters against an ESPN card."""
from __future__ import annotations

import datetime as dt
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import espn_client as espn  # noqa: E402

from .names import _name_key, _name_parts, _parse_date
from .targets import _dedupe_games


# Kept inside the caller-owned card cache so one source response serves both
# identity resolution and the raw-capture plan.  It cannot collide with an
# ISO date key.
_RAW_CARD_PAYLOADS_KEY = "__ufc_raw_card_payloads__"

@dataclass(frozen=True)
class CardIdentity:
    athlete_id: str
    canonical_name: str
    fight_id: Optional[str]
    method: str
    event_id: Optional[str] = None


def _scoreboard_endpoint(card_date: Optional[str]) -> str:
    """Return the exact ESPN scoreboard URL for a card-date source body."""
    _, path = espn._check("ufc")
    query = "?dates=" + card_date.replace("-", "") if card_date else ""
    return espn._SITE.format(path=path) + "/scoreboard" + query


def card_source_payloads(cache: Dict[Optional[str], object]) -> List[Tuple[str, dict]]:
    """Raw successful card responses observed while resolving this plan."""
    stored = cache.get(_RAW_CARD_PAYLOADS_KEY) or {}
    return [stored[key] for key in sorted(stored)]

def _card_for_date(
    card_date: Optional[str],
    cache: Dict[Optional[str], object],
) -> Tuple[Optional[List[dict]], Optional[str]]:
    """Fetch one card window and distinguish an outage from a legitimate miss."""
    parsed = _parse_date(card_date)
    candidates: List[Optional[str]]
    if parsed is None:
        candidates = [None]
    else:
        candidates = [
            parsed.isoformat(),
            (parsed - dt.timedelta(days=1)).isoformat(),
            (parsed + dt.timedelta(days=1)).isoformat(),
        ]
    successful = 0
    collected: List[dict] = []
    error_kinds: List[str] = []
    for index, candidate in enumerate(candidates):
        cached = cache.get(candidate)
        if cached is None:
            try:
                # `games()` normalizes and discards most of the scoreboard.
                # Keep the actual publisher document first, then normalize the
                # same object so this does not spend a second request.
                raw = espn.scoreboard_raw("ufc", candidate)
                from espn_client.scoreboard import _games_from_payload
                cached = _games_from_payload("ufc", candidate, raw)
                raw_cache = cache.setdefault(_RAW_CARD_PAYLOADS_KEY, {})
                raw_cache[candidate] = (_scoreboard_endpoint(candidate), raw)
            except Exception as exc:
                cached = exc
            cache[candidate] = cached
        if isinstance(cached, Exception):
            error_kinds.append(type(cached).__name__)
            continue
        successful += 1
        collected.extend(cached)
        # The exact date supplied a card. Do not make unnecessary neighbor requests.
        if index == 0 and cached:
            break
    if successful == 0:
        reason = ",".join(sorted(set(error_kinds))) or "unknown_error"
        return None, "scoreboard_unavailable:{}".format(reason)
    return _dedupe_games(collected), None

def _fighters_from_card(games: Sequence[dict]) -> List[dict]:
    fighters = []
    for game in games:
        for side, other_side in (("home", "away"), ("away", "home")):
            fighter = game.get(side) or {}
            opponent = game.get(other_side) or {}
            athlete_id = str(fighter.get("id") or "")
            name = str(fighter.get("name") or "")
            if athlete_id and name:
                fighters.append(
                    {
                        "id": athlete_id,
                        "name": name,
                        "opponent": str(opponent.get("name") or ""),
                        "fight_id": str(game.get("game_id") or "") or None,
                        "event_id": str(game.get("event_id") or "") or None,
                    }
                )
    return fighters

def resolve_from_card(
    name: str,
    opponent: Optional[str],
    games: Sequence[dict],
) -> Optional[CardIdentity]:
    """Resolve one source fighter using conservative card and pair context."""
    fighters = _fighters_from_card(games)
    target = _name_key(name)
    exact = [row for row in fighters if _name_key(row["name"]) == target]
    if len(exact) == 1:
        row = exact[0]
        return CardIdentity(
            row["id"], row["name"], row["fight_id"], "exact", row["event_id"]
        )
    if len(target) >= 7:
        prefix = [
            row
            for row in fighters
            if target.startswith(_name_key(row["name"]))
            or _name_key(row["name"]).startswith(target)
        ]
        if len(prefix) == 1:
            row = prefix[0]
            return CardIdentity(
                row["id"], row["name"], row["fight_id"], "prefix", row["event_id"]
            )
    target_parts = _name_parts(name)
    if len(target_parts) >= 2:
        first_last = []
        for row in fighters:
            parts = _name_parts(row["name"])
            if len(parts) >= 2 and parts[0] == target_parts[0] and parts[-1] == target_parts[-1]:
                first_last.append(row)
        if len(first_last) == 1:
            row = first_last[0]
            return CardIdentity(
                row["id"],
                row["name"],
                row["fight_id"],
                "first_last",
                row["event_id"],
            )
    # A paired opponent is strong enough to repair a small source spelling error,
    # but still require the fighter's first name to agree.
    if opponent and target_parts:
        pair_matches = [
            row
            for row in fighters
            if _name_key(row["opponent"]) == _name_key(opponent)
            and _name_parts(row["name"])
            and _name_parts(row["name"])[0] == target_parts[0]
        ]
        if len(pair_matches) == 1:
            row = pair_matches[0]
            return CardIdentity(
                row["id"],
                row["name"],
                row["fight_id"],
                "opponent_pair",
                row["event_id"],
            )
    return None

def _identity_for_existing_id(
    athlete_id: str,
    games: Sequence[dict],
    fallback_name: str,
) -> CardIdentity:
    matches = [row for row in _fighters_from_card(games) if row["id"] == athlete_id]
    if len(matches) == 1:
        row = matches[0]
        return CardIdentity(
            row["id"], row["name"], row["fight_id"], "stored_id", row["event_id"]
        )
    return CardIdentity(athlete_id, fallback_name, None, "stored_id")
