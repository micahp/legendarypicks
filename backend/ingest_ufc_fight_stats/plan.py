"""Plan construction for the UFC fight-stat ingest."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

# Route shared helpers through the package object at call time so tests that
# monkeypatch ingest._card_for_date / fetch_fight_history / fetch_stats /
# fetch_fight_status keep working exactly as before the split.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import espn_client as espn  # noqa: E402

import ingest_ufc_fight_stats as ingest
from .targets import FighterTarget  # noqa: E402
from .card import CardIdentity  # noqa: E402
from .fetch import SourceUnavailable  # noqa: E402

@dataclass(frozen=True)
class PreparedLog:
    player_id: int
    season: int
    game_no: str
    game_id: str
    game_date: str
    opponent: str
    stats_json: str
    source_player_key: str
    @property
    def natural_key(self) -> Tuple[str, str, int, str]:
        return ("ufc", self.source_player_key, self.season, self.game_no)


@dataclass(frozen=True)
class SourcePayload:
    """Untouched source body carried until the plan's single write transaction."""
    endpoint: str
    payload: dict

@dataclass
class IngestPlan:
    target_count: int
    candidate_count: int = 0
    existing_count: int = 0
    identity_updates: Dict[int, str] = field(default_factory=dict)
    game_links: Dict[int, str] = field(default_factory=dict)
    logs: List[PreparedLog] = field(default_factory=list)
    source_payloads: List[SourcePayload] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    missing_stats: List[str] = field(default_factory=list)
    source_errors: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)

def _prepared_log(player_id: int, athlete_id: str, fight: dict, stats: dict) -> PreparedLog:
    enriched = dict(stats)
    enriched["result"] = fight["result"]
    enriched["method"] = fight["method"]
    if fight.get("fight_time_seconds") is not None:
        enriched["fight_time_seconds"] = fight["fight_time_seconds"]
        enriched["fight_time"] = round(fight["fight_time_seconds"] / 60.0, 2)
        enriched["round"] = fight["round"]
        enriched["clock_display"] = fight["clock_display"]
    date_text = str(fight.get("date") or "")
    season = int(date_text[:4]) if len(date_text) >= 4 and date_text[:4].isdigit() else 0
    return PreparedLog(
        player_id=player_id,
        season=season,
        game_no=date_text,
        game_id=str(fight.get("fight_id") or ""),
        game_date=date_text,
        opponent=str(fight.get("opponent") or ""),
        stats_json=json.dumps(enriched, sort_keys=True, separators=(",", ":")),
        source_player_key=athlete_id,
    )

def _resolve_target_for_plan(
    target: FighterTarget,
    card_cache: Dict[Optional[str], object],
    owner_by_espn: Dict[str, int],
    plan: IngestPlan,
    emit: Callable[[str], None],
) -> Tuple[Optional[CardIdentity], List[dict]]:
    games: List[dict] = []
    card_error = None
    if target.card_date:
        card, card_error = ingest._card_for_date(target.card_date, card_cache)
        games = card or []
    identity: Optional[CardIdentity]
    if target.espn_id:
        identity = ingest._identity_for_existing_id(target.espn_id, games, target.name)
    elif card_error:
        plan.source_errors.append(
            "{}: identity {}".format(target.name, card_error)
        )
        return None, games
    else:
        identity = ingest.resolve_from_card(target.name, target.opponent, games)
    if identity is None:
        plan.unresolved.append(
            "{} (card={}, opponent={})".format(
                target.name, target.card_date or "none", target.opponent or "none"
            )
        )
        emit("  SKIP {}: no unique ESPN card identity".format(target.name))
        return None, games
    owner = owner_by_espn.get(identity.athlete_id)
    if owner is not None and owner != target.player_id:
        plan.conflicts.append(
            "{}: ESPN {} is already owned by player {}".format(
                target.name, identity.athlete_id, owner
            )
        )
        return None, games
    if not target.espn_id:
        plan.identity_updates[target.player_id] = identity.athlete_id
        owner_by_espn[identity.athlete_id] = target.player_id
    if target.prop_game_id and identity.fight_id:
        stored_link = str(target.prop_game_espn_id or "")
        prior_link = plan.game_links.get(target.prop_game_id)
        if stored_link and stored_link != identity.fight_id:
            plan.conflicts.append(
                "prop_game {} stores {} but resolved to {}".format(
                    target.prop_game_id, stored_link, identity.fight_id
                )
            )
            return None, games
        if prior_link and prior_link != identity.fight_id:
            plan.conflicts.append(
                "prop_game {} resolved to both {} and {}".format(
                    target.prop_game_id, prior_link, identity.fight_id
                )
            )
            return None, games
        if not stored_link:
            plan.game_links[target.prop_game_id] = identity.fight_id
    emit(
        "  resolved {} -> ESPN {} ({})".format(
            target.name, identity.athlete_id, identity.method
        )
    )
    return identity, games

def build_plan(
    targets: Sequence[FighterTarget],
    existing_keys: Set[Tuple[str, str, int, str]],
    owner_by_espn: Dict[str, int],
    limit: int,
    emit: Callable[[str], None] = print,
) -> IngestPlan:
    """Complete all source work and return an immutable-to-DB write plan."""
    plan = IngestPlan(target_count=len(targets))
    card_cache: Dict[Optional[str], object] = {}
    prepared_by_key: Dict[Tuple[str, str, int, str], PreparedLog] = {}
    for target in targets:
        identity, _ = _resolve_target_for_plan(
            target, card_cache, owner_by_espn, plan, emit
        )
        if identity is None:
            continue
        try:
            fights = ingest.fetch_fight_history(identity.athlete_id, limit=limit)
        except SourceUnavailable as exc:
            plan.source_errors.append("{}: {}".format(target.name, str(exc)))
            continue
        if not fights:
            emit("  {}: no completed fights in ESPN history".format(target.name))
            continue
        fighter_candidates = 0
        for fight in fights:
            date_text = str(fight.get("date") or "")
            season = (
                int(date_text[:4])
                if len(date_text) >= 4 and date_text[:4].isdigit()
                else 0
            )
            natural_key = ("ufc", identity.athlete_id, season, date_text)
            if natural_key in existing_keys:
                plan.candidate_count += 1
                plan.existing_count += 1
                fighter_candidates += 1
                emit(
                    "  KEEP {} vs {} ({}): existing row".format(
                        target.name, fight.get("opponent"), date_text
                    )
                )
                continue
            try:
                stats = ingest.fetch_stats(
                    str(fight["event_id"]),
                    str(fight["fight_id"]),
                    identity.athlete_id,
                )
            except SourceUnavailable as exc:
                plan.source_errors.append(
                    "{}: {} for fight {}".format(
                        target.name, str(exc), fight.get("fight_id")
                    )
                )
                continue
            if not stats:
                plan.missing_stats.append(
                    "{}:{}:{}".format(
                        target.name, fight.get("fight_id"), fight.get("date")
                    )
                )
                emit(
                    "  {}: no stats for {} vs {} (fight_id={})".format(
                        target.name,
                        fight.get("date"),
                        fight.get("opponent"),
                        fight.get("fight_id"),
                    )
                )
                continue
            row = _prepared_log(target.player_id, identity.athlete_id, fight, stats)
            plan.candidate_count += 1
            fighter_candidates += 1
            prior = prepared_by_key.get(row.natural_key)
            if prior and prior != row:
                plan.conflicts.append(
                    "{}: duplicate candidate key {} has different data".format(
                        target.name, row.natural_key
                    )
                )
                continue
            prepared_by_key[row.natural_key] = row
            emit(
                "  DRY-RUN {} vs {} ({}): {} stats, result={}, method={}".format(
                    target.name,
                    fight.get("opponent"),
                    fight.get("date"),
                    len(json.loads(row.stats_json)),
                    fight.get("result"),
                    fight.get("method"),
                )
            )
        if fighter_candidates:
            emit("  {}: {} candidate fights".format(target.name, fighter_candidates))
    for key, row in prepared_by_key.items():
        if key not in existing_keys:
            plan.logs.append(row)
    plan.source_errors = sorted(set(plan.source_errors))
    plan.conflicts = sorted(set(plan.conflicts))
    plan.unresolved = sorted(set(plan.unresolved))
    plan.missing_stats = sorted(set(plan.missing_stats))
    return plan

def build_current_card_plan(
    targets: Sequence[FighterTarget],
    existing_keys: Set[Tuple[str, str, int, str]],
    owner_by_espn: Dict[str, int],
    emit: Callable[[str], None] = print,
) -> IngestPlan:
    """Plan only completed fights on the scoped card, without athlete-history calls."""
    plan = IngestPlan(target_count=len(targets))
    card_cache: Dict[Optional[str], object] = {}
    status_cache: Dict[Tuple[str, str], object] = {}
    prepared_by_key: Dict[Tuple[str, str, int, str], PreparedLog] = {}
    for target in targets:
        identity, games = _resolve_target_for_plan(
            target, card_cache, owner_by_espn, plan, emit
        )
        if identity is None:
            continue
        game = next(
            (
                row
                for row in games
                if str(row.get("game_id") or "") == str(identity.fight_id or "")
            ),
            None,
        )
        if game is None and identity.method == "stored_id":
            emit(
                "  SKIP {}: durable fighter is not on the final ESPN card".format(
                    target.name
                )
            )
            continue
        if game is None or not identity.event_id or not identity.fight_id:
            plan.conflicts.append(
                "{}: resolved identity lacks a durable card fight/event id".format(
                    target.name
                )
            )
            continue
        if game.get("state") != "post":
            emit(
                "  WAIT {}: card fight {} is {}".format(
                    target.name, identity.fight_id, game.get("state") or "unknown"
                )
            )
            continue
        fighter = next(
            (
                game.get(side) or {}
                for side in ("home", "away")
                if str((game.get(side) or {}).get("id") or "")
                == identity.athlete_id
            ),
            None,
        )
        opponent = next(
            (
                game.get(side) or {}
                for side in ("home", "away")
                if str((game.get(side) or {}).get("id") or "")
                != identity.athlete_id
            ),
            {},
        )
        if fighter is None:
            plan.conflicts.append(
                "{}: ESPN {} is absent from resolved fight {}".format(
                    target.name, identity.athlete_id, identity.fight_id
                )
            )
            continue
        date_text = str(game.get("date") or "")[:10]
        season = (
            int(date_text[:4])
            if len(date_text) >= 4 and date_text[:4].isdigit()
            else 0
        )
        natural_key = ("ufc", identity.athlete_id, season, date_text)
        if natural_key in existing_keys:
            plan.candidate_count += 1
            plan.existing_count += 1
            emit(
                "  KEEP {} vs {} ({}): existing row".format(
                    target.name, opponent.get("name"), date_text
                )
            )
            continue
        status_key = (identity.event_id, identity.fight_id)
        status = status_cache.get(status_key)
        if status is None:
            try:
                status = ingest.fetch_fight_status(*status_key)
            except SourceUnavailable as exc:
                status = exc
            status_cache[status_key] = status
            if not isinstance(status, SourceUnavailable):
                plan.source_payloads.append(SourcePayload(
                    endpoint=ingest._STATUS_URL.format(
                        event_id=identity.event_id, fight_id=identity.fight_id
                    ),
                    payload=status,
                ))
        if isinstance(status, SourceUnavailable):
            plan.source_errors.append(
                "{}: {} for fight {}".format(
                    target.name, str(status), identity.fight_id
                )
            )
            continue
        if (status.get("type") or {}).get("state") != "post":
            plan.conflicts.append(
                "{}: scoreboard says post but status endpoint does not".format(
                    target.name
                )
            )
            continue
        if fighter.get("winner") is True:
            outcome = "W"
        elif opponent.get("winner") is True:
            outcome = "L"
        else:
            result_text = str(
                (status.get("result") or {}).get("displayName") or ""
            ).lower()
            outcome = "D" if "draw" in result_text else "NC"
        round_num = status.get("period")
        clock_seconds = status.get("clock")
        fight_time_seconds = (
            (round_num - 1) * 300 + clock_seconds
            if isinstance(round_num, int)
            and isinstance(clock_seconds, (int, float))
            else None
        )
        fight = {
            "result": outcome,
            "method": espn._ufc_method(status.get("result") or {}),
            "opponent": str(opponent.get("name") or ""),
            "date": date_text,
            "event_id": identity.event_id,
            "fight_id": identity.fight_id,
            "round": round_num,
            "clock_display": status.get("displayClock"),
            "fight_time_seconds": fight_time_seconds,
        }
        try:
            stats = ingest.fetch_stats(
                identity.event_id, identity.fight_id, identity.athlete_id
            )
        except SourceUnavailable as exc:
            plan.source_errors.append(
                "{}: {} for fight {}".format(
                    target.name, str(exc), identity.fight_id
                )
            )
            continue
        if not stats:
            plan.missing_stats.append(
                "{}:{}:{}".format(target.name, identity.fight_id, date_text)
            )
            emit(
                "  {}: no current-card stats for fight {}".format(
                    target.name, identity.fight_id
                )
            )
            continue
        row = _prepared_log(target.player_id, identity.athlete_id, fight, stats)
        plan.candidate_count += 1
        prior = prepared_by_key.get(row.natural_key)
        if prior and prior != row:
            plan.conflicts.append(
                "{}: duplicate current-card key has different data".format(
                    target.name
                )
            )
            continue
        prepared_by_key[row.natural_key] = row
        emit(
            "  DRY-RUN {} vs {} ({}): current-card result={}, method={}".format(
                target.name,
                fight["opponent"],
                date_text,
                fight["result"],
                fight["method"],
            )
        )
    plan.logs = list(prepared_by_key.values())
    plan.source_errors = sorted(set(plan.source_errors))
    plan.conflicts = sorted(set(plan.conflicts))
    plan.unresolved = sorted(set(plan.unresolved))
    plan.missing_stats = sorted(set(plan.missing_stats))
    return plan
