#!/usr/bin/env python3
"""Guarded one-day MLB batting-history refresh for production.

The runner first compares completed MLB Stats API games with production game
IDs. It fetches at most one missing day's Statcast data with
``parallel=False``, fetches every required boxscore, and builds the complete
mutation plan in memory. Only then does it create an integrity-checked backup
and open one short SQLite write transaction.

Existing JSON keys always win. This is important for the known two-way-player
batting/pitching collisions in legacy rows. Newly scheduled rows use the actual
MLB game ID as ``game_no`` so doubleheaders do not share a natural key.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import history_refresh_common as common


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "data", "picks.db")
SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
BOXSCORE_URL = "https://statsapi.mlb.com/api/v1/game/{}/boxscore"
HEADERS = {"User-Agent": "LegendaryPicks-history-refresh/1.0"}
HIT_EVENTS = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
NaturalKey = Tuple[str, str, int, str]


@dataclass(frozen=True)
class SourceRow:
    source_player_key: str
    player_name: str
    season: int
    game_no: str
    game_id: str
    game_date: str
    team: Optional[str]
    opponent: Optional[str]
    home_away: Optional[str]
    stats: Dict[str, int]

    @property
    def natural_key(self) -> NaturalKey:
        return ("mlb", self.source_player_key, self.season, self.game_no)


@dataclass(frozen=True)
class PlannedUpdate:
    row_id: int
    old_stats: str
    new_stats: str
    conflicting_keys: Tuple[str, ...]


@dataclass(frozen=True)
class PlannedInsert:
    player_id: Optional[int]
    row: SourceRow


@dataclass
class MlbPlan:
    target_date: str
    final_game_ids: Set[str] = field(default_factory=set)
    source_rows: List[SourceRow] = field(default_factory=list)
    updates: List[PlannedUpdate] = field(default_factory=list)
    inserts: List[PlannedInsert] = field(default_factory=list)
    existing_rows: int = 0
    collision_rows: int = 0
    collision_keys: int = 0
    unresolved: Dict[str, str] = field(default_factory=dict)
    identity_conflicts: List[str] = field(default_factory=list)
    source_errors: List[str] = field(default_factory=list)


def _request_json(
    url: str,
    params: Optional[dict] = None,
    retries: int = 2,
) -> dict:
    if params:
        url = "{}?{}".format(url, urllib.parse.urlencode(params))
    last_error = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.5 * (2 ** attempt))
    raise RuntimeError(
        "source request failed after {} attempts: {}".format(
            retries, last_error
        )
    )


def fetch_final_schedule(start: dt.date, end: dt.date) -> Dict[str, Set[str]]:
    payload = _request_json(
        SCHEDULE_URL,
        {
            "sportId": 1,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
        },
    )
    result: Dict[str, Set[str]] = {}
    for date_block in payload.get("dates", []):
        date_text = str(date_block.get("date") or "")
        final_ids = {
            str(game.get("gamePk"))
            for game in date_block.get("games", [])
            if (game.get("status") or {}).get("abstractGameState") == "Final"
            and game.get("gamePk") is not None
        }
        if date_text and final_ids:
            result[date_text] = final_ids
    return result


def fetch_boxscore_batting(
    game_ids: Set[str],
) -> Tuple[Dict[Tuple[str, str], dict], List[str]]:
    batting: Dict[Tuple[str, str], dict] = {}
    errors: List[str] = []
    for game_id in sorted(game_ids):
        try:
            payload = _request_json(BOXSCORE_URL.format(game_id))
        except Exception as exc:
            errors.append("boxscore {}: {}".format(game_id, exc))
            continue
        for side in ("away", "home"):
            team_block = (payload.get("teams") or {}).get(side) or {}
            team = ((team_block.get("team") or {}).get("abbreviation") or "")
            for player in (team_block.get("players") or {}).values():
                person = player.get("person") or {}
                athlete_id = person.get("id")
                stats = ((player.get("stats") or {}).get("batting") or {})
                if athlete_id is None or not stats:
                    continue
                batting[(game_id, str(athlete_id))] = {
                    "name": str(person.get("fullName") or "unknown"),
                    "team": team or None,
                    "R": stats.get("runs"),
                    "RBI": stats.get("rbi"),
                }
    return batting, errors


def fetch_statcast_day(date_text: str):
    from pybaseball import statcast

    return statcast(
        date_text,
        date_text,
        verbose=False,
        parallel=False,
    )


def source_rows_from_frame(
    data,
    date_text: str,
    final_game_ids: Set[str],
    boxscore_batting: Dict[Tuple[str, str], dict],
) -> Tuple[List[SourceRow], List[str], List[str]]:
    errors: List[str] = []
    conflicts: List[str] = []
    required_columns = {"events", "batter", "game_pk", "game_date"}
    missing_columns = sorted(required_columns - set(data.columns))
    if missing_columns:
        return [], [
            "Statcast response missing columns {}".format(
                ",".join(missing_columns)
            )
        ], []

    available_game_ids = {
        str(int(value))
        for value in data["game_pk"].dropna().unique().tolist()
    }
    missing_games = sorted(final_game_ids - available_game_ids)
    if missing_games:
        errors.append(
            "Statcast missing {} final games: {}".format(
                len(missing_games), ",".join(missing_games)
            )
        )

    plate_appearances = data[data["events"].notna()].copy()
    rows_by_key: Dict[NaturalKey, SourceRow] = {}
    for (raw_batter, raw_game_id), group in plate_appearances.groupby(
        ["batter", "game_pk"]
    ):
        game_id = str(int(raw_game_id))
        if game_id not in final_game_ids:
            continue
        athlete_id = str(int(raw_batter))
        box_line = boxscore_batting.get((game_id, athlete_id))
        if (
            not box_line
            or box_line.get("R") is None
            or box_line.get("RBI") is None
        ):
            errors.append(
                "boxscore batting line missing R/RBI for {} in {}".format(
                    athlete_id, game_id
                )
            )
            continue

        events = group["events"].value_counts().to_dict()
        hits = sum(int(events.get(name, 0)) for name in HIT_EVENTS)
        total_bases = sum(
            int(events.get(name, 0)) * value
            for name, value in HIT_EVENTS.items()
        )
        stats = {
            "H": hits,
            "2B": int(events.get("double", 0)),
            "3B": int(events.get("triple", 0)),
            "HR": int(events.get("home_run", 0)),
            "BB": int(events.get("walk", 0)),
            "K": int(events.get("strikeout", 0)),
            "TB": total_bases,
            "PA": int(len(group)),
            "R": int(box_line["R"]),
            "RBI": int(box_line["RBI"]),
        }
        game_date = str(group["game_date"].iloc[0])[:10] or date_text
        team = box_line.get("team")
        opponent = None
        home_away = None
        if {
            "inning_topbot",
            "home_team",
            "away_team",
        }.issubset(group.columns):
            is_away = str(group["inning_topbot"].iloc[0]) == "Top"
            home = str(group["home_team"].iloc[0])
            away = str(group["away_team"].iloc[0])
            inferred_team = away if is_away else home
            team = team or inferred_team
            opponent = home if is_away else away
            home_away = "away" if is_away else "home"
        row = SourceRow(
            source_player_key=athlete_id,
            player_name=str(box_line.get("name") or "unknown"),
            season=int(game_date[:4]),
            game_no=game_id,
            game_id=game_id,
            game_date=game_date,
            team=team,
            opponent=opponent,
            home_away=home_away,
            stats=stats,
        )
        prior = rows_by_key.get(row.natural_key)
        if prior and prior != row:
            conflicts.append(
                "duplicate source rows differ for natural key {}".format(
                    row.natural_key
                )
            )
            continue
        rows_by_key[row.natural_key] = row
    return list(rows_by_key.values()), sorted(set(errors)), sorted(set(conflicts))


def _player_owners(
    connection: sqlite3.Connection,
    source_keys: Set[str],
) -> Tuple[Dict[str, int], List[str]]:
    players_by_mlbam: Dict[str, List[int]] = defaultdict(list)
    mlbam_by_player: Dict[int, str] = {}
    for row in connection.execute(
        """SELECT id,mlbam_id FROM players
           WHERE league='mlb' AND mlbam_id IS NOT NULL"""
    ):
        source_key = str(row["mlbam_id"])
        player_id = int(row["id"])
        players_by_mlbam[source_key].append(player_id)
        mlbam_by_player[player_id] = source_key

    prop_candidates: Dict[str, List[dict]] = defaultdict(list)
    for row in connection.execute(
        """SELECT CAST(pl.mlbam_id AS TEXT) AS source_key,p.player_id,
                  MAX(pg.date) AS latest_game,MAX(p.captured_at) AS latest_capture
           FROM props p
           JOIN players pl ON pl.id=p.player_id
           JOIN prop_games pg ON pg.id=p.game_id
           WHERE pl.league='mlb' AND pl.mlbam_id IS NOT NULL
           GROUP BY CAST(pl.mlbam_id AS TEXT),p.player_id"""
    ):
        prop_candidates[str(row["source_key"])].append(dict(row))

    log_candidates: Dict[str, Set[int]] = defaultdict(set)
    for row in connection.execute(
        """SELECT source_player_key,player_id
           FROM player_game_logs
           WHERE league='mlb' AND source_player_key IS NOT NULL
             AND player_id IS NOT NULL
           GROUP BY source_player_key,player_id"""
    ):
        log_candidates[str(row["source_player_key"])].add(
            int(row["player_id"])
        )

    owners: Dict[str, int] = {}
    conflicts: List[str] = []
    for source_key in sorted(source_keys):
        candidates = prop_candidates.get(source_key, [])
        if candidates:
            latest_game = max(str(row["latest_game"] or "") for row in candidates)
            latest = [
                row
                for row in candidates
                if str(row["latest_game"] or "") == latest_game
            ]
            if len(latest) > 1:
                latest_capture = max(
                    str(row["latest_capture"] or "") for row in latest
                )
                latest = [
                    row
                    for row in latest
                    if str(row["latest_capture"] or "") == latest_capture
                ]
            if len(latest) == 1:
                owners[source_key] = int(latest[0]["player_id"])
                continue
            conflicts.append(
                "MLBAM {} has ambiguous latest prop players {}".format(
                    source_key,
                    sorted(int(row["player_id"]) for row in latest),
                )
            )
            continue

        log_ids = sorted(log_candidates.get(source_key, set()))
        if len(log_ids) == 1:
            player_id = log_ids[0]
            if mlbam_by_player.get(player_id) != source_key:
                conflicts.append(
                    "MLBAM {} log owner {} has mlbam_id {}".format(
                        source_key,
                        player_id,
                        mlbam_by_player.get(player_id),
                    )
                )
            else:
                owners[source_key] = player_id
            continue
        if len(log_ids) > 1:
            conflicts.append(
                "MLBAM {} has production log owners {}".format(
                    source_key, log_ids
                )
            )
            continue

        player_ids = sorted(players_by_mlbam.get(source_key, []))
        if len(player_ids) == 1:
            owners[source_key] = player_ids[0]
        elif len(player_ids) > 1:
            conflicts.append(
                "MLBAM {} has ambiguous production players {}".format(
                    source_key, player_ids
                )
            )
    return owners, conflicts


def build_plan(
    connection: sqlite3.Connection,
    target_date: str,
    final_game_ids: Set[str],
    source_rows: Sequence[SourceRow],
) -> MlbPlan:
    plan = MlbPlan(
        target_date=target_date,
        final_game_ids=set(final_game_ids),
        source_rows=list(source_rows),
    )
    source_keys = {row.source_player_key for row in source_rows}
    owners, conflicts = _player_owners(connection, source_keys)
    plan.identity_conflicts.extend(conflicts)

    existing = {}
    for row in connection.execute(
        """SELECT * FROM player_game_logs
           WHERE league='mlb' AND game_date=?""",
        (target_date,),
    ):
        # Legacy MLB rows use the date as game_no. Match those by their actual
        # stored game_id; all new scheduled rows use game_id directly.
        key = (
            str(row["league"]),
            str(row["source_player_key"]),
            int(row["season"]),
            str(row["game_id"] or row["game_no"]),
        )
        if key in existing and int(existing[key]["id"]) != int(row["id"]):
            plan.source_errors.append(
                "production has duplicate MLB game identity {} in rows {} and {}".format(
                    key, existing[key]["id"], row["id"]
                )
            )
            continue
        existing[key] = row

    for source_row in source_rows:
        player_id = owners.get(source_row.source_player_key)
        if player_id is None:
            plan.unresolved[source_row.source_player_key] = (
                source_row.player_name
            )
        current = existing.get(source_row.natural_key)
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
                "production row {} stats are not an object".format(
                    current["id"]
                )
            )
            continue
        conflicting = tuple(
            sorted(
                key
                for key in source_row.stats.keys() & prod_stats.keys()
                if source_row.stats[key] != prod_stats[key]
            )
        )
        if conflicting:
            plan.collision_rows += 1
            plan.collision_keys += len(conflicting)
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
                conflicting_keys=conflicting,
            )
        )
    return plan


def _logged_games_by_date(
    connection: sqlite3.Connection,
    start: str,
    end: str,
) -> Dict[str, Set[str]]:
    result: Dict[str, Set[str]] = defaultdict(set)
    for row in connection.execute(
        """SELECT game_date,game_id FROM player_game_logs
           WHERE league='mlb' AND game_date BETWEEN ? AND ?
             AND game_id IS NOT NULL
             AND json_extract(stats,'$.H') IS NOT NULL
           GROUP BY game_date,game_id""",
        (start, end),
    ):
        result[str(row["game_date"])].add(str(row["game_id"]))
    return result


def select_target_date(
    connection: sqlite3.Connection,
    as_of: dt.date,
    schedule_fetcher: Callable[
        [dt.date, dt.date], Dict[str, Set[str]]
    ] = fetch_final_schedule,
) -> Tuple[Optional[str], Set[str], dict]:
    yesterday = as_of - dt.timedelta(days=1)
    row = connection.execute(
        """SELECT MAX(game_date) FROM player_game_logs
           WHERE league='mlb' AND json_extract(stats,'$.H') IS NOT NULL"""
    ).fetchone()
    latest = None
    if row and row[0]:
        latest = dt.datetime.strptime(str(row[0]), "%Y-%m-%d").date()
    start = latest or (yesterday - dt.timedelta(days=14))
    start = max(start, yesterday - dt.timedelta(days=14))
    if start > yesterday:
        return None, set(), {"latest_log_date": latest.isoformat() if latest else None}

    schedule = schedule_fetcher(start, yesterday)
    logged = _logged_games_by_date(
        connection, start.isoformat(), yesterday.isoformat()
    )
    for date_text in sorted(schedule):
        missing = schedule[date_text] - logged.get(date_text, set())
        if missing:
            return date_text, schedule[date_text], {
                "latest_log_date": latest.isoformat() if latest else None,
                "missing_game_ids": sorted(missing),
            }
    return None, set(), {
        "latest_log_date": latest.isoformat() if latest else None,
    }


def apply_plan(db_path: str, plan: MlbPlan) -> dict:
    if plan.source_errors or plan.identity_conflicts:
        raise RuntimeError("refusing apply: MLB plan validation failed")
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
               VALUES(?,'mlb',?,?,?,?,?,?,?,?, 'statcast',?)""",
            [
                (
                    item.player_id,
                    item.row.season,
                    item.row.game_no,
                    item.row.game_id,
                    item.row.game_date,
                    item.row.team,
                    item.row.opponent,
                    item.row.home_away,
                    common.json_dump(item.row.stats),
                    item.row.source_player_key,
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

        queued = 0
        for source_key, name in sorted(plan.unresolved.items()):
            existing = connection.execute(
                """SELECT id FROM unresolved_players
                   WHERE source='statcast' AND league='mlb'
                     AND source_player_key=?
                   ORDER BY id LIMIT 1""",
                (source_key,),
            ).fetchone()
            if existing:
                connection.execute(
                    """UPDATE unresolved_players
                       SET count=count+1,reason='missing_production_mlbam_identity'
                       WHERE id=?""",
                    (existing[0],),
                )
            else:
                connection.execute(
                    """INSERT INTO unresolved_players
                       (source,raw_name,league,team,first_seen,count,
                        source_player_key,reason)
                       VALUES('statcast',?,'mlb',?,datetime('now'),1,?,
                              'missing_production_mlbam_identity')""",
                    (
                        name,
                        next(
                            (
                                item.row.team
                                for item in plan.inserts
                                if item.row.source_player_key == source_key
                            ),
                            None,
                        ),
                        source_key,
                    ),
                )
            queued += 1

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
               VALUES('mlb',?,datetime('now'),'ok',?)
               ON CONFLICT(league) DO UPDATE SET
                 source_cursor=excluded.source_cursor,
                 refreshed_at=excluded.refreshed_at,
                 status=excluded.status,
                 details=excluded.details""",
            (
                plan.target_date,
                common.json_dump(
                    {
                        "final_games": len(plan.final_game_ids),
                        "source_rows": len(plan.source_rows),
                        "updated": updated,
                        "inserted": inserted,
                        "unresolved": len(plan.unresolved),
                    }
                ),
            ),
        )
        connection.commit()
        return {
            "updated": updated,
            "inserted": inserted,
            "queued": queued,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def run(
    db_path: str,
    apply: bool,
    as_of: Optional[dt.date] = None,
    emit: Callable[[str], None] = print,
    schedule_fetcher: Callable[
        [dt.date, dt.date], Dict[str, Set[str]]
    ] = fetch_final_schedule,
    statcast_fetcher: Callable[[str], object] = fetch_statcast_day,
    boxscore_fetcher: Callable[
        [Set[str]], Tuple[Dict[Tuple[str, str], dict], List[str]]
    ] = fetch_boxscore_batting,
) -> dict:
    db_path = os.path.abspath(db_path)
    as_of = as_of or dt.date.today()
    if common.integrity_check(db_path) != "ok":
        raise RuntimeError("production integrity_check failed")

    with closing(common.read_only_connection(db_path)) as connection:
        target_date, final_game_ids, target_detail = select_target_date(
            connection, as_of, schedule_fetcher=schedule_fetcher
        )
    if target_date is None:
        emit(
            "MLB batting history is current through {}".format(
                target_detail.get("latest_log_date") or "no completed games"
            )
        )
        return {"status": "current", **target_detail}

    emit(
        "MLB target {}: {} final games, {} missing game IDs".format(
            target_date,
            len(final_game_ids),
            len(target_detail.get("missing_game_ids", [])),
        )
    )
    data = statcast_fetcher(target_date)
    if data is None or len(data) == 0:
        raise RuntimeError(
            "Statcast returned no rows for {}".format(target_date)
        )
    boxscore_batting, boxscore_errors = boxscore_fetcher(final_game_ids)
    source_rows, source_errors, source_conflicts = source_rows_from_frame(
        data, target_date, final_game_ids, boxscore_batting
    )
    del data
    with closing(common.read_only_connection(db_path)) as connection:
        plan = build_plan(
            connection, target_date, final_game_ids, source_rows
        )
    plan.source_errors.extend(boxscore_errors)
    plan.source_errors.extend(source_errors)
    plan.identity_conflicts.extend(source_conflicts)
    plan.source_errors = sorted(set(plan.source_errors))
    plan.identity_conflicts = sorted(set(plan.identity_conflicts))

    emit(
        "MLB plan: {} source rows, {} updates, {} inserts, "
        "{} unresolved, {} collision rows, {} source errors, "
        "{} conflicts".format(
            len(plan.source_rows),
            len(plan.updates),
            len(plan.inserts),
            len(plan.unresolved),
            plan.collision_rows,
            len(plan.source_errors),
            len(plan.identity_conflicts),
        )
    )
    if plan.source_errors or plan.identity_conflicts:
        for error in plan.source_errors:
            emit("  source error: {}".format(error))
        for conflict in plan.identity_conflicts:
            emit("  conflict: {}".format(conflict))
        raise RuntimeError("MLB plan validation failed; no writes attempted")
    for source_key, name in sorted(plan.unresolved.items()):
        emit("  unresolved MLBAM {}: {}".format(source_key, name))
    if not apply:
        return {
            "status": "dry_run",
            "target_date": target_date,
            "source_rows": len(plan.source_rows),
            "updates": len(plan.updates),
            "inserts": len(plan.inserts),
            "unresolved": len(plan.unresolved),
            "collision_rows": plan.collision_rows,
        }

    backup_path = common.backup_database(
        db_path, "mlb-history-timer"
    )
    result = apply_plan(db_path, plan)
    emit(
        "MLB applied: {updated} updates, {inserted} inserts, "
        "{queued} unresolved identities; backup {backup}".format(
            backup=backup_path, **result
        )
    )
    return {
        "status": "applied",
        "target_date": target_date,
        "backup": backup_path,
        **result,
    }


def _date(value: str) -> dt.date:
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be YYYY-MM-DD") from exc


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--db", default=os.environ.get("LP_DB_PATH") or DEFAULT_DB)
    parser.add_argument("--as-of", type=_date)
    args = parser.parse_args(argv)
    try:
        run(
            args.db,
            apply=args.apply,
            as_of=args.as_of,
        )
    except Exception as exc:
        print("ERROR: {}: {}".format(type(exc).__name__, exc))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
