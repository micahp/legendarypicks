#!/usr/bin/env python3
"""
Ingest durable per-fight UFC statistics from ESPN.

The network phase is completed before a writable database connection is opened.
Writes, when explicitly requested with ``--apply``, are additive and occur in one
short transaction.

Usage:
  LP_DB_PATH=/path/to/picks.db python3 ingest_ufc_fight_stats.py --dry-run
  LP_DB_PATH=/path/to/picks.db python3 ingest_ufc_fight_stats.py --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time
import unicodedata
import re
from contextlib import closing
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import espn_client as espn


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)

_STATS_URL = (
    espn._SPORTS_CORE.format(sport="mma")
    + "/leagues/ufc/events/{event_id}/competitions/{fight_id}"
    + "/competitors/{competitor_id}/statistics?lang=en&region=us"
)
_STATUS_URL = (
    espn._SPORTS_CORE.format(sport="mma")
    + "/leagues/ufc/events/{event_id}/competitions/{fight_id}"
    + "/status?lang=en&region=us"
)


class SourceUnavailable(RuntimeError):
    """An upstream request failed in a way that must not be treated as no data."""


@dataclass(frozen=True)
class FighterTarget:
    player_id: int
    name: str
    espn_id: Optional[str]
    card_date: Optional[str]
    prop_game_id: Optional[int]
    opponent: Optional[str]
    prop_game_espn_id: Optional[str] = None


@dataclass(frozen=True)
class CardIdentity:
    athlete_id: str
    canonical_name: str
    fight_id: Optional[str]
    method: str
    event_id: Optional[str] = None


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


@dataclass
class IngestPlan:
    target_count: int
    candidate_count: int = 0
    existing_count: int = 0
    identity_updates: Dict[int, str] = field(default_factory=dict)
    game_links: Dict[int, str] = field(default_factory=dict)
    logs: List[PreparedLog] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    missing_stats: List[str] = field(default_factory=list)
    source_errors: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)


def ensure_table(con: sqlite3.Connection) -> None:
    """Create the shared log table/indexes inside the caller's transaction."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS player_game_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id         INTEGER,
            league            TEXT NOT NULL,
            season            INTEGER NOT NULL,
            game_no           TEXT,
            game_id           TEXT,
            game_date         TEXT,
            team              TEXT,
            opponent          TEXT,
            home_away         TEXT,
            stats             TEXT NOT NULL,
            source            TEXT,
            source_player_key TEXT,
            ingested_at       TEXT DEFAULT (datetime('now')),
            UNIQUE(league, source_player_key, season, game_no)
        )
        """
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_pgl_player "
        "ON player_game_logs(player_id, league, season, game_no)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_pgl_league_date "
        "ON player_game_logs(league, game_date)"
    )


def _read_only_connection(path: str) -> sqlite3.Connection:
    absolute = os.path.abspath(path)
    uri = "file:{}?mode=ro".format(quote(absolute, safe="/"))
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _name_key(value: Optional[str]) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())


def _name_parts(value: Optional[str]) -> List[str]:
    ascii_value = (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.findall(r"[a-z0-9]+", ascii_value.lower())


def _parse_date(value: Optional[str]) -> Optional[dt.date]:
    try:
        return dt.datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _opponent_for(player_name: str, home: Optional[str], away: Optional[str]) -> Optional[str]:
    player_key = _name_key(player_name)
    if player_key and player_key == _name_key(home):
        return away
    if player_key and player_key == _name_key(away):
        return home
    return None


def load_targets(
    db_path: str,
    as_of: dt.date,
    lookback_days: int = 7,
    lookahead_days: int = 21,
    all_fighters: bool = False,
) -> Tuple[List[FighterTarget], Set[Tuple[str, str, int, str]], Dict[str, int]]:
    """Load a finite fighter work set and existing keys without opening prod writable."""
    with closing(_read_only_connection(db_path)) as con:
        player_rows = con.execute(
            "SELECT id, name, espn_id FROM players WHERE league='ufc' ORDER BY name"
        ).fetchall()
        associations = con.execute(
            """
            SELECT DISTINCT p.player_id, pg.id AS prop_game_id, pg.date, pg.home,
                            pg.away, pg.espn_event_id
            FROM props p
            JOIN prop_games pg ON pg.id=p.game_id
            WHERE pg.league='ufc'
            """
        ).fetchall()
        existing_keys = {
            ("ufc", str(row["source_player_key"]), int(row["season"]), str(row["game_no"]))
            for row in con.execute(
                """
                SELECT source_player_key, season, game_no
                FROM player_game_logs
                WHERE league='ufc'
                  AND source_player_key IS NOT NULL
                  AND game_no IS NOT NULL
                """
            )
        }
        owner_by_espn = {
            str(row["espn_id"]): int(row["id"])
            for row in con.execute(
                """
                SELECT id, espn_id FROM players
                WHERE league='ufc' AND NULLIF(espn_id, '') IS NOT NULL
                """
            )
        }

    by_player: Dict[int, List[sqlite3.Row]] = {}
    for row in associations:
        by_player.setdefault(int(row["player_id"]), []).append(row)

    start_date = as_of - dt.timedelta(days=max(0, lookback_days))
    end_date = as_of + dt.timedelta(days=max(0, lookahead_days))
    targets: List[FighterTarget] = []
    for player in player_rows:
        choices = []
        for row in by_player.get(int(player["id"]), []):
            card_date = _parse_date(row["date"])
            if card_date is None:
                continue
            if all_fighters or start_date <= card_date <= end_date:
                choices.append((abs((card_date - as_of).days), -card_date.toordinal(), row))
        choices.sort(key=lambda item: (item[0], item[1], int(item[2]["prop_game_id"])))
        if not choices and not all_fighters:
            continue
        selected = choices[0][2] if choices else None
        targets.append(
            FighterTarget(
                player_id=int(player["id"]),
                name=str(player["name"]),
                espn_id=str(player["espn_id"] or "").strip() or None,
                card_date=str(selected["date"])[:10] if selected else None,
                prop_game_id=int(selected["prop_game_id"]) if selected else None,
                opponent=(
                    _opponent_for(player["name"], selected["home"], selected["away"])
                    if selected
                    else None
                ),
                prop_game_espn_id=(
                    str(selected["espn_event_id"] or "").strip() or None
                    if selected
                    else None
                ),
            )
        )
    return targets, existing_keys, owner_by_espn


def _dedupe_games(games: Iterable[dict]) -> List[dict]:
    by_id = {}
    for game in games:
        game_id = str(game.get("game_id") or "")
        if game_id:
            by_id[game_id] = game
    return list(by_id.values())


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


def _error_kind(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return "http_{}".format(exc.code)
    if isinstance(exc, URLError):
        return "url_error"
    return type(exc).__name__


def _retry_delay(exc: Exception, attempt: int) -> float:
    if isinstance(exc, HTTPError) and exc.headers:
        raw = exc.headers.get("Retry-After")
        try:
            return min(5.0, max(0.25, float(raw)))
        except (TypeError, ValueError):
            pass
    return 1.0 + attempt


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code == 429 or 500 <= exc.code <= 599
    return isinstance(exc, URLError)


def fetch_fight_history(athlete_id: str, limit: int, attempts: int = 2) -> List[dict]:
    """Fetch overview history with one bounded retry for transient source errors."""
    last_error: Optional[Exception] = None
    for attempt in range(max(1, attempts)):
        try:
            return espn.ufc_fight_history(athlete_id, limit=limit)
        except Exception as exc:
            last_error = exc
            if attempt + 1 >= attempts or not _retryable(exc):
                break
            time.sleep(_retry_delay(exc, attempt))
    assert last_error is not None
    raise SourceUnavailable("fight_history_{}".format(_error_kind(last_error))) from last_error


def fetch_stats(
    event_id: str,
    fight_id: str,
    competitor_id: str,
    attempts: int = 2,
) -> dict:
    """Return raw per-fight stats; distinguish missing data from source failure."""
    url = _STATS_URL.format(
        event_id=event_id, fight_id=fight_id, competitor_id=competitor_id
    )
    data = None
    last_error: Optional[Exception] = None
    for attempt in range(max(1, attempts)):
        try:
            data = espn._get(url, ttl=21600)
            break
        except HTTPError as exc:
            if exc.code == 404:
                return {}
            last_error = exc
        except Exception as exc:
            last_error = exc
        if (
            last_error is None
            or attempt + 1 >= attempts
            or not _retryable(last_error)
        ):
            break
        time.sleep(_retry_delay(last_error, attempt))
    if data is None:
        assert last_error is not None
        raise SourceUnavailable("stats_{}".format(_error_kind(last_error))) from last_error
    categories = (data.get("splits") or {}).get("categories") or []
    if not categories:
        return {}
    stats_list = categories[0].get("stats") or []
    return {
        item["name"]: item.get("value")
        for item in stats_list
        if isinstance(item, dict) and "name" in item
    }


def fetch_fight_status(
    event_id: str,
    fight_id: str,
    attempts: int = 2,
) -> dict:
    """Fetch one completed fight status with bounded transient retries."""
    url = _STATUS_URL.format(event_id=event_id, fight_id=fight_id)
    last_error: Optional[Exception] = None
    for attempt in range(max(1, attempts)):
        try:
            return espn._get(url, ttl=21600)
        except Exception as exc:
            last_error = exc
        if attempt + 1 >= attempts or not _retryable(last_error):
            break
        time.sleep(_retry_delay(last_error, attempt))
    assert last_error is not None
    raise SourceUnavailable("fight_status_{}".format(_error_kind(last_error))) from last_error


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
        card, card_error = _card_for_date(target.card_date, card_cache)
        games = card or []

    identity: Optional[CardIdentity]
    if target.espn_id:
        identity = _identity_for_existing_id(target.espn_id, games, target.name)
    elif card_error:
        plan.source_errors.append(
            "{}: identity {}".format(target.name, card_error)
        )
        return None, games
    else:
        identity = resolve_from_card(target.name, target.opponent, games)

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
            fights = fetch_fight_history(identity.athlete_id, limit=limit)
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
                stats = fetch_stats(
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
                status = fetch_fight_status(*status_key)
            except SourceUnavailable as exc:
                status = exc
            status_cache[status_key] = status
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
            stats = fetch_stats(
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


def apply_plan(db_path: str, plan: IngestPlan) -> dict:
    """Apply a completed plan in one short transaction with no source calls."""
    if plan.source_errors:
        raise RuntimeError("refusing write: source errors are present")
    if plan.conflicts:
        raise RuntimeError("refusing write: identity/data conflicts are present")

    con = sqlite3.connect(db_path, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        con.execute("BEGIN IMMEDIATE")
        ensure_table(con)

        identity_updates = 0
        for player_id, athlete_id in sorted(plan.identity_updates.items()):
            owner = con.execute(
                "SELECT id FROM players WHERE league='ufc' AND espn_id=?",
                (athlete_id,),
            ).fetchone()
            if owner is not None and int(owner["id"]) != player_id:
                raise RuntimeError(
                    "ESPN {} became owned by player {}".format(
                        athlete_id, owner["id"]
                    )
                )
            cursor = con.execute(
                """
                UPDATE players SET espn_id=?
                WHERE id=? AND league='ufc' AND NULLIF(espn_id, '') IS NULL
                """,
                (athlete_id, player_id),
            )
            identity_updates += max(cursor.rowcount, 0)

        game_links = 0
        for prop_game_id, fight_id in sorted(plan.game_links.items()):
            row = con.execute(
                "SELECT espn_event_id FROM prop_games WHERE id=? AND league='ufc'",
                (prop_game_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("UFC prop_game {} disappeared".format(prop_game_id))
            current = str(row["espn_event_id"] or "")
            if current and current != fight_id:
                raise RuntimeError(
                    "UFC prop_game {} is already linked to {}".format(
                        prop_game_id, current
                    )
                )
            if not current:
                cursor = con.execute(
                    "UPDATE prop_games SET espn_event_id=? WHERE id=?",
                    (fight_id, prop_game_id),
                )
                game_links += max(cursor.rowcount, 0)

        before_logs = con.total_changes
        con.executemany(
            """
            INSERT OR IGNORE INTO player_game_logs
              (player_id, league, season, game_no, game_id, game_date,
               team, opponent, home_away, stats, source, source_player_key)
            VALUES (?, 'ufc', ?, ?, ?, ?, NULL, ?, NULL, ?, 'espn_mma_stats', ?)
            """,
            [
                (
                    row.player_id,
                    row.season,
                    row.game_no,
                    row.game_id,
                    row.game_date,
                    row.opponent,
                    row.stats_json,
                    row.source_player_key,
                )
                for row in plan.logs
            ],
        )
        inserted_logs = con.total_changes - before_logs
        con.commit()
        return {
            "identity_updates": identity_updates,
            "game_links": game_links,
            "inserted_logs": inserted_logs,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return number


def _fight_limit(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 5:
        raise argparse.ArgumentTypeError("must be between 1 and 5")
    return number


def _print_summary(plan: IngestPlan, dry_run: bool) -> None:
    print("\nSummary")
    print("  fighters targeted: {}".format(plan.target_count))
    print("  ESPN identities to persist: {}".format(len(plan.identity_updates)))
    print("  UFC prop games to link: {}".format(len(plan.game_links)))
    print("  fight rows with stats: {}".format(plan.candidate_count))
    print("  existing rows preserved: {}".format(plan.existing_count))
    label = "would insert" if dry_run else "planned inserts"
    print("  {}: {}".format(label, len(plan.logs)))
    print("  missing-stat fight references: {}".format(len(plan.missing_stats)))
    print("  unresolved fighters: {}".format(len(plan.unresolved)))
    print("  source errors: {}".format(len(plan.source_errors)))
    print("  conflicts: {}".format(len(plan.conflicts)))
    if plan.unresolved:
        print("  unresolved detail:")
        for item in plan.unresolved:
            print("    - {}".format(item))
    if plan.source_errors:
        print("  source error detail:")
        for item in plan.source_errors:
            print("    - {}".format(item))
    if plan.conflicts:
        print("  conflict detail:")
        for item in plan.conflicts:
            print("    - {}".format(item))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest UFC per-fight stats into player_game_logs"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="fetch and plan; never write")
    mode.add_argument("--apply", action="store_true", help="apply a fully fetched additive plan")
    parser.add_argument("--limit", type=_fight_limit, default=5)
    parser.add_argument("--lookback-days", type=_positive_int, default=7)
    parser.add_argument("--lookahead-days", type=_positive_int, default=21)
    parser.add_argument(
        "--all-fighters",
        action="store_true",
        help="include every durable UFC fighter, not just the current card window",
    )
    parser.add_argument(
        "--current-card-only",
        action="store_true",
        help="ingest only completed scoped-card fights; do not call athlete history",
    )
    parser.add_argument(
        "--as-of",
        help="YYYY-MM-DD target date for reproducible planning (default: today)",
    )
    parser.add_argument(
        "--backup",
        help="required integrity-checked pre-write backup path with --apply",
    )
    parser.add_argument("--expect-inserts", type=_positive_int)
    parser.add_argument("--expect-identity-updates", type=_positive_int)
    parser.add_argument("--expect-game-links", type=_positive_int)
    parser.add_argument("--expect-unresolved", type=_positive_int)
    parser.add_argument("--expect-missing-stats", type=_positive_int)
    args = parser.parse_args(argv)

    if not os.path.isfile(DB) or os.path.getsize(DB) <= 0:
        parser.error("database is missing or empty: {}".format(DB))
    as_of = _parse_date(args.as_of) if args.as_of else dt.date.today()
    if as_of is None:
        parser.error("--as-of must be YYYY-MM-DD")
    if args.apply:
        required = {
            "--backup": args.backup,
            "--expect-inserts": args.expect_inserts,
            "--expect-identity-updates": args.expect_identity_updates,
            "--expect-game-links": args.expect_game_links,
            "--expect-unresolved": args.expect_unresolved,
            "--expect-missing-stats": args.expect_missing_stats,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            parser.error("--apply requires {}".format(", ".join(missing)))
        backup_path = os.path.abspath(args.backup)
        if backup_path == os.path.abspath(DB):
            parser.error("--backup must differ from the production database")
        if not os.path.isfile(backup_path) or os.path.getsize(backup_path) <= 0:
            parser.error("backup is missing or empty: {}".format(backup_path))
        with closing(_read_only_connection(backup_path)) as backup_con:
            backup_integrity = backup_con.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]
        if backup_integrity != "ok":
            parser.error(
                "backup integrity_check returned {}".format(backup_integrity)
            )

    targets, existing_keys, owner_by_espn = load_targets(
        DB,
        as_of,
        lookback_days=args.lookback_days,
        lookahead_days=args.lookahead_days,
        all_fighters=args.all_fighters,
    )
    print(
        "Found {} UFC fighters in the {} work set".format(
            len(targets), "all-fighter" if args.all_fighters else "card-window"
        )
    )
    if not targets:
        print("ERROR: no UFC fighters are linked to the selected card window")
        return 2

    if args.current_card_only:
        plan = build_current_card_plan(
            targets, existing_keys, owner_by_espn
        )
    else:
        plan = build_plan(targets, existing_keys, owner_by_espn, args.limit)
    _print_summary(plan, dry_run=args.dry_run)
    if plan.source_errors or plan.conflicts:
        print("\nABORTED: no database writes were attempted")
        return 2
    if args.dry_run:
        print("\nDone (dry-run, database opened read-only)")
        return 0

    actual = {
        "--expect-inserts": len(plan.logs),
        "--expect-identity-updates": len(plan.identity_updates),
        "--expect-game-links": len(plan.game_links),
        "--expect-unresolved": len(plan.unresolved),
        "--expect-missing-stats": len(plan.missing_stats),
    }
    expected = {
        "--expect-inserts": args.expect_inserts,
        "--expect-identity-updates": args.expect_identity_updates,
        "--expect-game-links": args.expect_game_links,
        "--expect-unresolved": args.expect_unresolved,
        "--expect-missing-stats": args.expect_missing_stats,
    }
    mismatches = [
        "{} expected {}, got {}".format(name, expected[name], actual[name])
        for name in expected
        if expected[name] != actual[name]
    ]
    if mismatches:
        print("\nABORTED: plan changed; no database writes were attempted")
        for mismatch in mismatches:
            print("  - {}".format(mismatch))
        return 2

    result = apply_plan(DB, plan)
    print(
        "\nApplied: {identity_updates} identities, {game_links} game links, "
        "{inserted_logs} new fight rows".format(**result)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
