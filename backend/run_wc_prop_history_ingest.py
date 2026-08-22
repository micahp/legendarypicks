#!/usr/bin/env python3
"""Guarded, prop-scoped World Cup history refresh.

Only ESPN athletes that uniquely resolve to an existing production WC player
are persisted. All scoreboards and summaries are fetched before an
integrity-checked backup and one short SQLite transaction. A durable cursor
prevents repeated tournament-wide source scans once the current prop slate has
been covered.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time
from contextlib import closing
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import espn_client as espn
import history_refresh_common as common
from ingest_wc_logs import (
    WCPlayerResolver,
    _boxscore_players,
    _opponent,
    _roster_players,
)


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "data", "picks.db")
NaturalKey = Tuple[str, str, int, str]


@dataclass(frozen=True)
class SourceRow:
    athlete_id: str
    name: str
    season: int
    game_id: str
    game_date: str
    team: Optional[str]
    opponent: Optional[str]
    home_away: Optional[str]
    stats: dict

    @property
    def natural_key(self) -> NaturalKey:
        return ("wc", self.athlete_id, self.season, self.game_id)


@dataclass(frozen=True)
class PlannedUpdate:
    row_id: int
    old_stats: str
    new_stats: str


@dataclass(frozen=True)
class PlannedInsert:
    player_id: int
    row: SourceRow


@dataclass
class WcPlan:
    cursor: str
    completed_game_ids: Set[str] = field(default_factory=set)
    expected_game_ids: Set[str] = field(default_factory=set)
    source_rows: List[SourceRow] = field(default_factory=list)
    inserts: List[PlannedInsert] = field(default_factory=list)
    updates: List[PlannedUpdate] = field(default_factory=list)
    identity_updates: Dict[int, str] = field(default_factory=dict)
    resolved_source_rows: int = 0
    ignored_non_prop_rows: int = 0
    uncovered_prop_players: List[str] = field(default_factory=list)
    existing_rows: int = 0
    source_errors: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)


def _cursor_state(connection: sqlite3.Connection) -> Optional[str]:
    table = connection.execute(
        """SELECT 1 FROM sqlite_master
           WHERE type='table' AND name='history_refresh_state'"""
    ).fetchone()
    if not table:
        return None
    row = connection.execute(
        """SELECT source_cursor FROM history_refresh_state
           WHERE league='wc' AND status='ok'"""
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def target_window(
    connection: sqlite3.Connection,
    lookback_days: int = 45,
) -> Tuple[Optional[dt.date], Optional[dt.date], Set[str], Optional[str]]:
    row = connection.execute(
        """SELECT MIN(date),MAX(date) FROM prop_games WHERE league='wc'"""
    ).fetchone()
    if not row or not row[1]:
        return None, None, set(), None
    end = dt.datetime.strptime(str(row[1]), "%Y-%m-%d").date()
    start = end - dt.timedelta(days=lookback_days)
    expected = {
        str(item[0])
        for item in connection.execute(
            """SELECT DISTINCT espn_event_id FROM prop_games
               WHERE league='wc' AND date BETWEEN ? AND ?
                 AND COALESCE(espn_event_id,'')<>''""",
            (start.isoformat(), end.isoformat()),
        )
    }
    return start, end, expected, _cursor_state(connection)


def fetch_source_rows(
    start: dt.date,
    end: dt.date,
    games_fetcher: Callable[[str, str], list] = espn.games,
    summary_fetcher: Callable[[str, str], dict] = espn.summary,
) -> Tuple[List[SourceRow], Set[str], List[str]]:
    rows: List[SourceRow] = []
    completed_game_ids: Set[str] = set()
    errors: List[str] = []
    day = start
    while day <= end:
        date_text = day.isoformat()
        try:
            games = [
                game
                for game in games_fetcher("wc", date_text)
                if game.get("state") == "post"
            ]
        except Exception as exc:
            errors.append("scoreboard {}: {}".format(date_text, exc))
            day += dt.timedelta(days=1)
            continue
        for game in games:
            game_id = str(game.get("game_id") or "")
            if not game_id:
                errors.append("scoreboard {} has a final game without id".format(date_text))
                continue
            completed_game_ids.add(game_id)
            try:
                summary = summary_fetcher("wc", game_id)
            except Exception as exc:
                errors.append("summary {}: {}".format(game_id, exc))
                continue
            player_lines = {}
            for line in _boxscore_players(summary):
                player_lines[line[0]] = line
            for line in _roster_players(summary):
                player_lines[line[0]] = line

            home = (game.get("home") or {}).get("abbrev") or ""
            away = (game.get("away") or {}).get("abbrev") or ""
            game_date = str(game.get("date") or date_text)[:10]
            for athlete_id, name, team, home_away, stats in player_lines.values():
                resolved_home_away = home_away
                if not resolved_home_away:
                    if team and home and team.upper() == home.upper():
                        resolved_home_away = "home"
                    elif team and away and team.upper() == away.upper():
                        resolved_home_away = "away"
                rows.append(
                    SourceRow(
                        athlete_id=str(athlete_id),
                        name=str(name),
                        season=int(game_date[:4]),
                        game_id=game_id,
                        game_date=game_date,
                        team=team or None,
                        opponent=_opponent(
                            team, resolved_home_away, home, away
                        ),
                        home_away=resolved_home_away,
                        stats=dict(stats),
                    )
                )
            time.sleep(0.05)
        day += dt.timedelta(days=1)
    return rows, completed_game_ids, sorted(set(errors))


def build_plan(
    connection: sqlite3.Connection,
    cursor: str,
    expected_game_ids: Set[str],
    completed_game_ids: Set[str],
    source_rows: Sequence[SourceRow],
    target_start: Optional[str] = None,
    target_end: Optional[str] = None,
) -> WcPlan:
    plan = WcPlan(
        cursor=cursor,
        expected_game_ids=set(expected_game_ids),
        completed_game_ids=set(completed_game_ids),
        source_rows=list(source_rows),
    )
    missing_expected = sorted(expected_game_ids - completed_game_ids)
    if missing_expected:
        plan.source_errors.append(
            "source did not return linked final games {}".format(
                ",".join(missing_expected)
            )
        )

    players = {
        int(row["id"]): dict(row)
        for row in connection.execute(
            "SELECT id,name,team,espn_id FROM players WHERE league='wc'"
        )
    }
    prop_scope = ""
    prop_params: Tuple[str, ...] = ()
    if target_start is not None and target_end is not None:
        prop_scope = " AND pg.date BETWEEN ? AND ?"
        prop_params = (target_start, target_end)
    prop_player_ids = {
        int(row["player_id"])
        for row in connection.execute(
            """SELECT DISTINCT p.player_id
               FROM props p
               JOIN prop_games pg ON pg.id=p.game_id
               WHERE pg.league='wc' AND p.player_id IS NOT NULL{}""".format(
                prop_scope
            ),
            prop_params,
        )
    }
    resolver = WCPlayerResolver(
        connection, allowed_player_ids=prop_player_ids
    )
    espn_owners = {
        str(row["espn_id"]): int(row["id"])
        for row in connection.execute(
            """SELECT id,espn_id FROM players
               WHERE league='wc' AND COALESCE(espn_id,'')<>''"""
        )
    }
    existing = {}
    for row in connection.execute(
        "SELECT * FROM player_game_logs WHERE league='wc'"
    ):
        key = (
            str(row["league"]),
            str(row["source_player_key"]),
            int(row["season"]),
            str(row["game_no"]),
        )
        existing[key] = row

    athlete_by_player: Dict[int, str] = {}
    prepared: Dict[NaturalKey, Tuple[int, SourceRow]] = {}
    for source_row in source_rows:
        player_id = resolver.resolve(
            source_row.name, source_row.team or ""
        )
        if player_id is None:
            plan.ignored_non_prop_rows += 1
            continue
        if player_id not in prop_player_ids:
            plan.ignored_non_prop_rows += 1
            continue
        plan.resolved_source_rows += 1
        current_player = players[player_id]
        current_espn = str(current_player.get("espn_id") or "")
        owner = espn_owners.get(source_row.athlete_id)
        if owner is not None and owner != player_id:
            plan.conflicts.append(
                "ESPN athlete {} belongs to WC players {} and {}".format(
                    source_row.athlete_id, owner, player_id
                )
            )
            continue
        prior_athlete = athlete_by_player.get(player_id)
        if prior_athlete and prior_athlete != source_row.athlete_id:
            plan.conflicts.append(
                "WC player {} resolved to ESPN athletes {} and {}".format(
                    player_id, prior_athlete, source_row.athlete_id
                )
            )
            continue
        athlete_by_player[player_id] = source_row.athlete_id
        if current_espn and current_espn != source_row.athlete_id:
            plan.conflicts.append(
                "WC player {} stores ESPN {} but resolved to {}".format(
                    player_id, current_espn, source_row.athlete_id
                )
            )
            continue
        if not current_espn:
            plan.identity_updates[player_id] = source_row.athlete_id

        prior = prepared.get(source_row.natural_key)
        if prior and (prior[0] != player_id or prior[1] != source_row):
            plan.conflicts.append(
                "duplicate WC natural key {} differs".format(
                    source_row.natural_key
                )
            )
            continue
        prepared[source_row.natural_key] = (player_id, source_row)

    resolved_player_ids = {
        player_id for player_id, _source_row in prepared.values()
    }
    plan.uncovered_prop_players = sorted(
        "{}:{} ({})".format(
            player_id,
            players[player_id]["name"],
            players[player_id].get("team") or "no team",
        )
        for player_id in prop_player_ids - resolved_player_ids
        if player_id in players
    )

    for key, (player_id, source_row) in prepared.items():
        current = existing.get(key)
        if current is None:
            plan.inserts.append(
                PlannedInsert(player_id=player_id, row=source_row)
            )
            continue
        plan.existing_rows += 1
        try:
            prod_stats = json.loads(current["stats"])
        except (TypeError, ValueError):
            plan.source_errors.append(
                "production row {} has invalid stats JSON".format(current["id"])
            )
            continue
        if not isinstance(prod_stats, dict):
            plan.source_errors.append(
                "production row {} stats are not an object".format(current["id"])
            )
            continue
        added = {
            key: value
            for key, value in source_row.stats.items()
            if key not in prod_stats
        }
        if not added:
            continue
        merged = dict(source_row.stats)
        merged.update(prod_stats)
        plan.updates.append(
            PlannedUpdate(
                row_id=int(current["id"]),
                old_stats=str(current["stats"]),
                new_stats=common.json_dump(merged),
            )
        )

    plan.source_errors = sorted(set(plan.source_errors))
    plan.conflicts = sorted(set(plan.conflicts))
    return plan


def apply_plan(db_path: str, plan: WcPlan) -> dict:
    if plan.source_errors or plan.conflicts:
        raise RuntimeError("refusing apply: WC plan validation failed")
    connection = sqlite3.connect(db_path, timeout=5)
    try:
        journal_mode = str(
            connection.execute("PRAGMA journal_mode").fetchone()[0]
        ).lower()
        if journal_mode != "delete":
            raise RuntimeError(
                "production journal_mode is {}, expected delete".format(
                    journal_mode
                )
            )
        connection.execute("BEGIN IMMEDIATE")

        before = connection.total_changes
        connection.executemany(
            """UPDATE players SET espn_id=?
               WHERE id=? AND league='wc' AND COALESCE(espn_id,'')=''""",
            [
                (athlete_id, player_id)
                for player_id, athlete_id in sorted(
                    plan.identity_updates.items()
                )
            ],
        )
        identity_updates = connection.total_changes - before
        if identity_updates != len(plan.identity_updates):
            raise RuntimeError(
                "planned {} identity updates but applied {}".format(
                    len(plan.identity_updates), identity_updates
                )
            )

        before = connection.total_changes
        connection.executemany(
            "UPDATE player_game_logs SET stats=? WHERE id=? AND stats=?",
            [
                (row.new_stats, row.row_id, row.old_stats)
                for row in plan.updates
            ],
        )
        updated = connection.total_changes - before
        if updated != len(plan.updates):
            raise RuntimeError(
                "planned {} updates but applied {}".format(
                    len(plan.updates), updated
                )
            )

        before = connection.total_changes
        connection.executemany(
            """INSERT OR IGNORE INTO player_game_logs
               (player_id,league,season,game_no,game_id,game_date,team,
                opponent,home_away,stats,source,source_player_key)
               VALUES(?,'wc',?,?,?,?,?,?,?,?, 'espn',?)""",
            [
                (
                    item.player_id,
                    item.row.season,
                    item.row.game_id,
                    item.row.game_id,
                    item.row.game_date,
                    item.row.team,
                    item.row.opponent,
                    item.row.home_away,
                    common.json_dump(item.row.stats),
                    item.row.athlete_id,
                )
                for item in plan.inserts
            ],
        )
        inserted = connection.total_changes - before
        if inserted != len(plan.inserts):
            raise RuntimeError(
                "planned {} inserts but applied {}".format(
                    len(plan.inserts), inserted
                )
            )

        connection.execute(
            """CREATE TABLE IF NOT EXISTS history_refresh_state(
                 league TEXT PRIMARY KEY,
                 source_cursor TEXT,
                 refreshed_at TEXT NOT NULL,
                 status TEXT NOT NULL,
                 details TEXT
               )"""
        )
        connection.execute(
            """INSERT INTO history_refresh_state
                 (league,source_cursor,refreshed_at,status,details)
               VALUES('wc',?,datetime('now'),'ok',?)
               ON CONFLICT(league) DO UPDATE SET
                 source_cursor=excluded.source_cursor,
                 refreshed_at=excluded.refreshed_at,
                 status=excluded.status,
                 details=excluded.details""",
            (
                plan.cursor,
                common.json_dump(
                    {
                        "completed_games": len(plan.completed_game_ids),
                        "resolved_source_rows": plan.resolved_source_rows,
                        "ignored_non_prop_rows": plan.ignored_non_prop_rows,
                        "identity_updates": identity_updates,
                        "updated": updated,
                        "inserted": inserted,
                    }
                ),
            ),
        )
        connection.commit()
        return {
            "identity_updates": identity_updates,
            "updated": updated,
            "inserted": inserted,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def run(
    db_path: str,
    apply: bool,
    emit: Callable[[str], None] = print,
    games_fetcher: Callable[[str, str], list] = espn.games,
    summary_fetcher: Callable[[str, str], dict] = espn.summary,
) -> dict:
    db_path = os.path.abspath(db_path)
    if common.integrity_check(db_path) != "ok":
        raise RuntimeError("production integrity_check failed")
    with closing(common.read_only_connection(db_path)) as connection:
        start, end, expected_game_ids, current_cursor = target_window(connection)
    if start is None or end is None:
        emit("WC has no production prop slate; nothing to refresh")
        return {"status": "no_targets"}
    if current_cursor and current_cursor >= end.isoformat():
        emit("WC prop history is current through {}".format(current_cursor))
        return {"status": "current", "cursor": current_cursor}

    emit(
        "WC source plan {}..{} for {} linked prop games".format(
            start, end, len(expected_game_ids)
        )
    )
    source_rows, completed_game_ids, source_errors = fetch_source_rows(
        start,
        end,
        games_fetcher=games_fetcher,
        summary_fetcher=summary_fetcher,
    )
    with closing(common.read_only_connection(db_path)) as connection:
        plan = build_plan(
            connection,
            end.isoformat(),
            expected_game_ids,
            completed_game_ids,
            source_rows,
            target_start=start.isoformat(),
            target_end=end.isoformat(),
        )
    plan.source_errors.extend(source_errors)
    plan.source_errors = sorted(set(plan.source_errors))
    emit(
        "WC plan: {} completed games, {} source rows, {} resolved rows, "
        "{} ignored non-prop rows, {} identities, {} updates, {} inserts, "
        "{} uncovered prop players, {} source errors, {} conflicts".format(
            len(plan.completed_game_ids),
            len(plan.source_rows),
            plan.resolved_source_rows,
            plan.ignored_non_prop_rows,
            len(plan.identity_updates),
            len(plan.updates),
            len(plan.inserts),
            len(plan.uncovered_prop_players),
            len(plan.source_errors),
            len(plan.conflicts),
        )
    )
    for player in plan.uncovered_prop_players:
        emit("  uncovered WC prop player: {}".format(player))
    if plan.source_errors or plan.conflicts:
        for error in plan.source_errors:
            emit("  source error: {}".format(error))
        for conflict in plan.conflicts:
            emit("  conflict: {}".format(conflict))
        raise RuntimeError("WC plan validation failed; no writes attempted")
    if not apply:
        return {
            "status": "dry_run",
            "cursor": plan.cursor,
            "completed_games": len(plan.completed_game_ids),
            "source_rows": len(plan.source_rows),
            "resolved_rows": plan.resolved_source_rows,
            "uncovered_prop_players": list(plan.uncovered_prop_players),
            "identity_updates": len(plan.identity_updates),
            "updates": len(plan.updates),
            "inserts": len(plan.inserts),
        }

    backup_path = common.backup_database(db_path, "wc-history-timer")
    result = apply_plan(db_path, plan)
    emit(
        "WC applied: {identity_updates} identities, {updated} updates, "
        "{inserted} inserts; backup {backup}".format(
            backup=backup_path, **result
        )
    )
    return {
        "status": "applied",
        "cursor": plan.cursor,
        "backup": backup_path,
        **result,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--db", default=os.environ.get("LP_DB_PATH") or DEFAULT_DB)
    args = parser.parse_args(argv)
    try:
        run(args.db, apply=args.apply)
    except Exception as exc:
        print("ERROR: {}: {}".format(type(exc).__name__, exc))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
