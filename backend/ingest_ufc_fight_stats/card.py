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

@dataclass(frozen=True)
class CardIdentity:
    athlete_id: str
    canonical_name: str
    fight_id: Optional[str]
    method: str
    event_id: Optional[str] = None

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
                cached = espn.games("ufc", candidate)
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
                        # The publisher's id for the OTHER side of this fight. A fighter we
                        # cannot name-match is still uniquely identified by who they are
                        # standing across from, and an id is a fact where a spelling is a
                        # vocabulary. See the opponent_id ladder in resolve_from_card.
                        "opponent_id": str(opponent.get("id") or "") or None,
                        "fight_id": str(game.get("game_id") or "") or None,
                        "event_id": str(game.get("event_id") or "") or None,
                    }
                )
    return fighters

def resolve_from_card(
    name: str,
    opponent: Optional[str],
    games: Sequence[dict],
    opponent_espn_id: Optional[str] = None,
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

    # A fight has two sides. If we already own the publisher's id for the OTHER side, the
    # fight identifies this side without comparing this side's name to anything, which is
    # the only kind of repair that is safe on an identity.
    #
    # Every ladder below this one compares the target's own spelling, and that is exactly
    # what a two-vocabulary case defeats. On 2026-08-24 both standing SKIPs were first-name
    # divergences: we held "Sergey Spivak" where ESPN publishes "Serghei Spivac", and
    # "Stanley Dorsainvil" where ESPN publishes "Stan Dorsainvil". Neither is a typo to be
    # corrected; they are two publishers' spellings of one person. The prefix, first_last and
    # paired-name ladders all refused, correctly, and the fighters were skipped every run.
    # Their opponents, Vitor Petrino and Gauge Young, were already resolved on our side, and
    # ESPN's own card pairs 4421246 with 5060483 and 5397038 with 5085318. The answer was
    # sitting in the payload the whole time under a key we were discarding.
    #
    # Deliberately NOT gated on any name agreement. Adding "and the surname must match" would
    # have re-broken Spivak/Spivac and bought nothing: the opponent id is already unique on
    # the card, and a second, weaker condition cannot make a unique match safer.
    if opponent_espn_id:
        by_opponent = [row for row in fighters if row.get("opponent_id") == opponent_espn_id]
        if len(by_opponent) == 1:
            row = by_opponent[0]
            return CardIdentity(
                row["id"], row["name"], row["fight_id"], "opponent_id", row["event_id"]
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
