"""Identity-safe UFCStats history plan and transactional publication."""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from .names import _name_key, _parse_date
from .schema import _read_only_connection
from .targets import FighterTarget
from .ufcstats_source import (
    FighterProfile,
    SourceCardFight,
    SourceEvent,
    UfcStatsClient,
    UfcStatsSourceError,
)


SOURCE = "ufcstats"
TABLE = "player_game_logs_ufcstats"


@dataclass(frozen=True)
class PreparedUfcStatsLog:
    player_id: int
    source_player_key: str
    source_fight_key: str
    source_event_key: str
    season: int
    game_date: str
    opponent: str
    stats_json: str

    @property
    def natural_key(self) -> Tuple[str, str]:
        return self.source_player_key, self.source_fight_key


@dataclass
class UfcStatsPlan:
    target_count: int
    published_event_count: int = 0
    scoped_card_fight_count: int = 0
    resolved_count: int = 0
    profile_count: int = 0
    candidate_count: int = 0
    existing_count: int = 0
    mappings: Dict[int, str] = field(default_factory=dict)
    inserts: List[PreparedUfcStatsLog] = field(default_factory=list)
    updates: List[PreparedUfcStatsLog] = field(default_factory=list)
    no_history: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    source_errors: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _accepted_name_keys(con: sqlite3.Connection) -> Dict[int, Set[str]]:
    accepted: Dict[int, Set[str]] = {}
    for row in con.execute("SELECT id,name FROM players WHERE league='ufc'"):
        accepted[int(row["id"])] = {_name_key(row["name"])}
    if _table_exists(con, "name_alias"):
        for row in con.execute(
            """SELECT a.player_id,a.alias_norm
                 FROM name_alias a JOIN players p ON p.id=a.player_id
                WHERE p.league='ufc'"""
        ):
            accepted.setdefault(int(row["player_id"]), set()).add(
                _name_key(row["alias_norm"])
            )
    return accepted


def _source_mappings(con: sqlite3.Connection) -> Tuple[Dict[int, str], Dict[str, int]]:
    by_player: Dict[int, str] = {}
    by_source: Dict[str, int] = {}
    if not _table_exists(con, "player_source_ids"):
        return by_player, by_source
    for row in con.execute(
        """SELECT player_id,source_player_key FROM player_source_ids
            WHERE source=? AND league='ufc'""",
        (SOURCE,),
    ):
        player_id = int(row["player_id"])
        source_key = str(row["source_player_key"])
        prior_source = by_player.get(player_id)
        prior_player = by_source.get(source_key)
        if prior_source is not None and prior_source != source_key:
            raise RuntimeError(
                "player {} owns multiple UFCStats ids".format(player_id)
            )
        if prior_player is not None and prior_player != player_id:
            raise RuntimeError(
                "UFCStats id {} has multiple owners".format(source_key)
            )
        by_player[player_id] = source_key
        by_source[source_key] = player_id
    return by_player, by_source


def _existing_logs(con: sqlite3.Connection) -> Dict[Tuple[str, str], PreparedUfcStatsLog]:
    if not _table_exists(con, TABLE):
        return {}
    existing = {}
    for row in con.execute(
        """SELECT player_id,source_player_key,game_id,source_event_key,
                  season,game_date,opponent,stats
             FROM player_game_logs_ufcstats"""
    ):
        prepared = PreparedUfcStatsLog(
            player_id=int(row["player_id"]),
            source_player_key=str(row["source_player_key"]),
            source_fight_key=str(row["game_id"]),
            source_event_key=str(row["source_event_key"] or ""),
            season=int(row["season"]),
            game_date=str(row["game_date"]),
            opponent=str(row["opponent"]),
            stats_json=str(row["stats"]),
        )
        if prepared.natural_key in existing:
            raise RuntimeError(
                "duplicate UFCStats natural key {}".format(prepared.natural_key)
            )
        existing[prepared.natural_key] = prepared
    return existing


def _load_numeric_prop_targets(
    con: sqlite3.Connection,
    as_of: dt.date,
    accepted: Dict[int, Set[str]],
    lookback_days: int,
    lookahead_days: int,
) -> List[FighterTarget]:
    start = as_of - dt.timedelta(days=max(0, lookback_days))
    end = as_of + dt.timedelta(days=max(0, lookahead_days))
    associations = con.execute(
        """SELECT DISTINCT p.player_id,pl.name,pl.espn_id,pg.id AS prop_game_id,
                  pg.date,pg.home,pg.away,pg.espn_event_id
             FROM props p
             JOIN players pl ON pl.id=p.player_id
             JOIN prop_games pg ON pg.id=p.game_id
            WHERE pg.league='ufc'
              AND p.market IN ('significant_strikes','fight_time')
            ORDER BY pg.date DESC,pg.id,p.player_id"""
    ).fetchall()
    players_by_game: Dict[int, Set[int]] = {}
    for row in con.execute(
        """SELECT DISTINCT p.game_id,p.player_id
             FROM props p JOIN prop_games pg ON pg.id=p.game_id
            WHERE pg.league='ufc'"""
    ):
        players_by_game.setdefault(int(row["game_id"]), set()).add(int(row["player_id"]))
    names = {
        int(row["id"]): str(row["name"])
        for row in con.execute("SELECT id,name FROM players WHERE league='ufc'")
    }

    choices: Dict[int, List[Tuple[int, int, sqlite3.Row]]] = {}
    for row in associations:
        card_date = _parse_date(row["date"])
        if card_date is None or not start <= card_date <= end:
            continue
        choices.setdefault(int(row["player_id"]), []).append(
            (abs((card_date - as_of).days), -card_date.toordinal(), row)
        )

    targets = []
    for player_id, rows in choices.items():
        rows.sort(key=lambda item: (item[0], item[1], int(item[2]["prop_game_id"])))
        row = rows[0][2]
        game_players = players_by_game.get(int(row["prop_game_id"]), set()) - {player_id}
        opponent = names[next(iter(game_players))] if len(game_players) == 1 else None
        if opponent is None:
            own_keys = accepted.get(player_id, {_name_key(row["name"])})
            home, away = str(row["home"] or ""), str(row["away"] or "")
            if _name_key(home) in own_keys:
                opponent = away
            elif _name_key(away) in own_keys:
                opponent = home
        targets.append(
            FighterTarget(
                player_id=player_id,
                name=str(row["name"]),
                espn_id=str(row["espn_id"] or "").strip() or None,
                card_date=str(row["date"])[:10],
                prop_game_id=int(row["prop_game_id"]),
                opponent=opponent,
                prop_game_espn_id=str(row["espn_event_id"] or "").strip() or None,
            )
        )
    return sorted(targets, key=lambda target: target.name)


def load_ufcstats_state(
    db_path: str,
    as_of: dt.date,
    lookback_days: int = 14,
    lookahead_days: int = 21,
) -> Tuple[
    List[FighterTarget],
    Dict[int, Set[str]],
    Dict[int, str],
    Dict[str, int],
    Dict[Tuple[str, str], PreparedUfcStatsLog],
]:
    with closing(_read_only_connection(db_path)) as con:
        accepted = _accepted_name_keys(con)
        targets = _load_numeric_prop_targets(
            con, as_of, accepted, lookback_days, lookahead_days
        )
        by_player, by_source = _source_mappings(con)
        existing = _existing_logs(con)
    return targets, accepted, by_player, by_source, existing


def _profile_log(player_id: int, profile: FighterProfile, fight) -> PreparedUfcStatsLog:
    stats = {
        "sigStrikesLanded": fight.significant_strikes,
        "fight_time_seconds": fight.fight_time_seconds,
        "fight_time": round(fight.fight_time_seconds / 60.0, 2),
        "round": fight.round_number,
        "clock_display": fight.clock_display,
        "result": fight.result,
        "method": fight.method,
    }
    return PreparedUfcStatsLog(
        player_id=player_id,
        source_player_key=profile.source_player_key,
        source_fight_key=fight.source_fight_key,
        source_event_key=fight.source_event_key,
        season=int(fight.game_date[:4]),
        game_date=fight.game_date,
        opponent=fight.opponent,
        stats_json=json.dumps(stats, sort_keys=True, separators=(",", ":")),
    )


def _candidate_card_mapping(
    target: FighterTarget,
    fights: Sequence[SourceCardFight],
    accepted: Dict[int, Set[str]],
    owner_by_name: Dict[str, Optional[int]],
) -> List[str]:
    own_keys = accepted.get(target.player_id, {_name_key(target.name)})
    opponent_keys = {_name_key(target.opponent)} if target.opponent else set()
    opponent_owner = owner_by_name.get(_name_key(target.opponent)) if target.opponent else None
    if opponent_owner is not None:
        opponent_keys.update(accepted.get(opponent_owner, set()))
    matches = []
    for fight in fights:
        left, right = fight.fighters
        left_key, right_key = _name_key(left.name), _name_key(right.name)
        if left_key in own_keys and right_key in opponent_keys:
            matches.append(left.source_player_key)
        elif right_key in own_keys and left_key in opponent_keys:
            matches.append(right.source_player_key)
    matched = sorted(set(matches))
    if matched:
        return matched
    # A publisher abbreviation on the opponent must not strand an otherwise
    # exact identity. At this point the event date is already exact; accept the
    # fighter only when his reviewed canonical/alias key appears in exactly one
    # fight on that published card. This resolved Ding Meng while refusing any
    # same-name ambiguity, and does not bind the Cam/Cameron opponent split.
    exact_on_card = []
    for fight in fights:
        for fighter in fight.fighters:
            if _name_key(fighter.name) in own_keys:
                exact_on_card.append(fighter.source_player_key)
    return sorted(set(exact_on_card))


def build_ufcstats_plan(
    targets: Sequence[FighterTarget],
    accepted: Dict[int, Set[str]],
    stored_by_player: Dict[int, str],
    owner_by_source: Dict[str, int],
    existing: Dict[Tuple[str, str], PreparedUfcStatsLog],
    client: UfcStatsClient,
    limit: int = 5,
    emit: Callable[[str], None] = print,
) -> UfcStatsPlan:
    """Fetch the entire bounded source set before returning a write plan."""
    plan = UfcStatsPlan(target_count=len(targets))
    if not targets:
        return plan
    try:
        events = client.completed_events()
    except UfcStatsSourceError as exc:
        plan.source_errors.append(str(exc))
        return plan
    plan.published_event_count = len(events)
    events_by_date: Dict[str, List[SourceEvent]] = {}
    for event in events:
        events_by_date.setdefault(event.date, []).append(event)

    card_by_date: Dict[str, List[SourceCardFight]] = {}
    fetched_cards: Dict[str, List[SourceCardFight]] = {}
    scoped_fight_keys: Set[str] = set()
    for date_text in sorted({target.card_date for target in targets if target.card_date}):
        target_date = _parse_date(date_text)
        neighbor_dates = (
            [
                (target_date + dt.timedelta(days=offset)).isoformat()
                for offset in (-1, 0, 1)
            ]
            if target_date is not None
            else [str(date_text)]
        )
        scoped_events = [
            event
            for neighbor_date in neighbor_dates
            for event in events_by_date.get(neighbor_date, [])
        ]
        if not scoped_events:
            plan.source_errors.append(
                "no UFCStats event published within one day of target date {}".format(
                    date_text
                )
            )
            continue
        card_fights: List[SourceCardFight] = []
        for event in scoped_events:
            if event.source_event_key not in fetched_cards:
                try:
                    fetched_cards[event.source_event_key] = client.event_card(event)
                except UfcStatsSourceError as exc:
                    plan.source_errors.append(
                        "event {}: {}".format(event.source_event_key, str(exc))
                    )
                    fetched_cards[event.source_event_key] = []
            card_fights.extend(fetched_cards[event.source_event_key])
            scoped_fight_keys.update(
                fight.source_fight_key for fight in fetched_cards[event.source_event_key]
            )
        card_by_date[str(date_text)] = card_fights
    plan.scoped_card_fight_count = len(scoped_fight_keys)

    owner_by_name: Dict[str, Optional[int]] = {}
    for player_id, keys in accepted.items():
        for key in keys:
            if not key:
                continue
            owner_by_name[key] = (
                None if key in owner_by_name and owner_by_name[key] != player_id else player_id
            )

    resolved: Dict[int, str] = {}
    for target in targets:
        stored = stored_by_player.get(target.player_id)
        candidates = _candidate_card_mapping(
            target,
            card_by_date.get(str(target.card_date or ""), []),
            accepted,
            owner_by_name,
        )
        if len(candidates) > 1:
            plan.conflicts.append(
                "{} matched multiple UFCStats fighters on {}: {}".format(
                    target.name, target.card_date, ",".join(candidates)
                )
            )
            continue
        published = candidates[0] if candidates else None
        if stored and published and stored != published:
            plan.conflicts.append(
                "{} stores UFCStats {} but card publishes {}".format(
                    target.name, stored, published
                )
            )
            continue
        source_key = stored or published
        if not source_key:
            plan.unresolved.append(
                "{} (card={}, opponent={})".format(
                    target.name, target.card_date or "none", target.opponent or "none"
                )
            )
            continue
        owner = owner_by_source.get(source_key)
        if owner is not None and owner != target.player_id:
            plan.conflicts.append(
                "UFCStats {} for {} is already owned by player {}".format(
                    source_key, target.name, owner
                )
            )
            continue
        owner_by_source[source_key] = target.player_id
        resolved[target.player_id] = source_key
        if stored != source_key:
            plan.mappings[target.player_id] = source_key
        emit("  resolved {} -> UFCStats {}".format(target.name, source_key))
    plan.resolved_count = len(resolved)

    target_by_id = {target.player_id: target for target in targets}
    for player_id, source_key in sorted(resolved.items(), key=lambda item: target_by_id[item[0]].name):
        target = target_by_id[player_id]
        try:
            profile = client.fighter_profile(source_key, limit=limit)
        except UfcStatsSourceError as exc:
            plan.source_errors.append("{}: {}".format(target.name, str(exc)))
            continue
        plan.profile_count += 1
        if _name_key(profile.name) not in accepted.get(player_id, {_name_key(target.name)}):
            plan.conflicts.append(
                "UFCStats {} publishes {!r}, canonical player {} is {!r}".format(
                    source_key, profile.name, player_id, target.name
                )
            )
            continue
        if not profile.fights:
            plan.no_history.append("{} ({})".format(target.name, source_key))
            emit("  {}: published profile has no completed fights".format(target.name))
            continue
        for fight in profile.fights:
            prepared = _profile_log(player_id, profile, fight)
            plan.candidate_count += 1
            prior = existing.get(prepared.natural_key)
            if prior is None:
                plan.inserts.append(prepared)
                continue
            if prior.player_id != player_id:
                plan.conflicts.append(
                    "fight {} for UFCStats {} is stored on player {}".format(
                        prepared.source_fight_key, source_key, prior.player_id
                    )
                )
            elif prior == prepared:
                plan.existing_count += 1
            else:
                plan.updates.append(prepared)
        emit(
            "  {}: {} published fights ({} new)".format(
                target.name,
                len(profile.fights),
                sum(1 for row in plan.inserts if row.player_id == player_id),
            )
        )

    plan.no_history = sorted(set(plan.no_history))
    plan.unresolved = sorted(set(plan.unresolved))
    plan.source_errors = sorted(set(plan.source_errors))
    plan.conflicts = sorted(set(plan.conflicts))
    return plan


def apply_ufcstats_plan(db_path: str, plan: UfcStatsPlan) -> dict:
    if plan.source_errors or plan.conflicts or plan.unresolved:
        raise RuntimeError(
            "refusing UFCStats write: errors={}, conflicts={}, unresolved={}".format(
                len(plan.source_errors), len(plan.conflicts), len(plan.unresolved)
            )
        )
    absolute = os.path.abspath(db_path)
    con = sqlite3.connect(absolute, timeout=60)
    con.row_factory = sqlite3.Row
    try:
        con.execute("BEGIN IMMEDIATE")
        if not _table_exists(con, TABLE):
            raise RuntimeError(
                "{} is missing; apply the UFCStats history migration first".format(TABLE)
            )
        if not _table_exists(con, "player_source_ids"):
            raise RuntimeError("player_source_ids is missing")
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        mappings_inserted = 0
        mappings_refreshed = 0
        for player_id, source_key in sorted(plan.mappings.items()):
            owner = con.execute(
                """SELECT player_id FROM player_source_ids
                    WHERE source=? AND league='ufc' AND source_player_key=?""",
                (SOURCE, source_key),
            ).fetchone()
            if owner is not None and int(owner["player_id"]) != player_id:
                raise RuntimeError(
                    "UFCStats {} became owned by player {}".format(
                        source_key, owner["player_id"]
                    )
                )
            if owner is None:
                con.execute(
                    """INSERT INTO player_source_ids
                       (source,league,source_player_key,player_id,first_seen,last_seen)
                       VALUES(?,'ufc',?,?,?,?)""",
                    (SOURCE, source_key, player_id, now, now),
                )
                mappings_inserted += 1
            else:
                con.execute(
                    """UPDATE player_source_ids SET last_seen=?
                        WHERE source=? AND league='ufc' AND source_player_key=?""",
                    (now, SOURCE, source_key),
                )
                mappings_refreshed += 1

        con.executemany(
            """INSERT INTO player_game_logs_ufcstats
               (player_id,league,season,game_no,game_id,game_date,opponent,
                stats,source,source_player_key,source_event_key)
               VALUES(?,'ufc',?,?,?,?,?,?,'ufcstats',?,?)""",
            [
                (
                    row.player_id,
                    row.season,
                    row.source_fight_key,
                    row.source_fight_key,
                    row.game_date,
                    row.opponent,
                    row.stats_json,
                    row.source_player_key,
                    row.source_event_key,
                )
                for row in plan.inserts
            ],
        )
        for row in plan.updates:
            cursor = con.execute(
                """UPDATE player_game_logs_ufcstats
                      SET player_id=?,season=?,game_date=?,opponent=?,stats=?,
                          source_event_key=?,ingested_at=datetime('now')
                    WHERE source_player_key=? AND game_id=?""",
                (
                    row.player_id,
                    row.season,
                    row.game_date,
                    row.opponent,
                    row.stats_json,
                    row.source_event_key,
                    row.source_player_key,
                    row.source_fight_key,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    "UFCStats update lost natural key {}".format(row.natural_key)
                )
        con.commit()
        return {
            "mappings_inserted": mappings_inserted,
            "mappings_refreshed": mappings_refreshed,
            "inserted_logs": len(plan.inserts),
            "updated_logs": len(plan.updates),
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
