#!/usr/bin/env python3
"""Guarded additive MLB R/RBI merge from dev into production.

For matching natural keys, only JSON keys absent from production are added.
Production wins every collision. Dev-only rows reuse the production player's
existing game-log link when available, after validating that link against
``players.mlbam_id``. A unique ``players.mlbam_id`` row is the fallback for
players with no production logs. Unresolved source keys remain
``player_id=NULL`` and are reported.

All rows are materialized before one short production transaction begins.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import quote


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROD = os.path.join(HERE, "data", "picks.db")
DEFAULT_DEV = os.path.join(HERE, "data", "picks.dev.db")
NaturalKey = Tuple[str, str, int, str]


def _ro_connection(path: str) -> sqlite3.Connection:
    absolute = os.path.abspath(path)
    con = sqlite3.connect(
        "file:{}?mode=ro".format(quote(absolute, safe="/")), uri=True
    )
    con.row_factory = sqlite3.Row
    return con


def _integrity(con: sqlite3.Connection) -> str:
    row = con.execute("PRAGMA integrity_check").fetchone()
    return str(row[0]) if row else "no result"


def _natural_key(row: sqlite3.Row) -> NaturalKey:
    return (
        str(row["league"]),
        str(row["source_player_key"]),
        int(row["season"]),
        str(row["game_no"]),
    )


def _stats(value: str) -> Optional[dict]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _json_dump(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class PlannedUpdate:
    row_id: int
    key: NaturalKey
    old_stats: str
    new_stats: str
    added_keys: Tuple[str, ...]
    conflicting_keys: Tuple[str, ...]


@dataclass(frozen=True)
class PlannedInsert:
    player_id: Optional[int]
    league: str
    season: int
    game_no: str
    game_id: Optional[str]
    game_date: Optional[str]
    team: Optional[str]
    opponent: Optional[str]
    home_away: Optional[str]
    stats: str
    source: Optional[str]
    source_player_key: str
    ingested_at: Optional[str]


@dataclass
class MergePlan:
    prod_rows: int = 0
    dev_rows: int = 0
    common_rows: int = 0
    exact_rrbi_updates: int = 0
    updates: List[PlannedUpdate] = field(default_factory=list)
    inserts: List[PlannedInsert] = field(default_factory=list)
    collision_rows: List[str] = field(default_factory=list)
    collision_key_count: int = 0
    missing_prod_counterparts: List[str] = field(default_factory=list)
    invalid_rows: List[str] = field(default_factory=list)
    dev_player_keys: int = 0
    resolved_player_keys: int = 0
    unresolved_player_keys: Dict[str, str] = field(default_factory=dict)
    added_key_patterns: Counter = field(default_factory=Counter)
    player_identity_conflicts: List[str] = field(default_factory=list)


def _load_logs(con: sqlite3.Connection) -> List[sqlite3.Row]:
    return con.execute(
        """
        SELECT * FROM player_game_logs
        WHERE league='mlb'
        ORDER BY source_player_key, season, game_no, id
        """
    ).fetchall()


def _prod_players_by_mlbam(
    con: sqlite3.Connection,
    source_keys: Set[str],
    plan: MergePlan,
) -> Dict[str, int]:
    players_by_mlbam: Dict[str, List[int]] = defaultdict(list)
    mlbam_by_player_id: Dict[int, str] = {}
    for row in con.execute(
        """
        SELECT id,mlbam_id FROM players
        WHERE league='mlb' AND mlbam_id IS NOT NULL
        """
    ):
        player_id = int(row["id"])
        source_key = str(row["mlbam_id"])
        players_by_mlbam[source_key].append(player_id)
        mlbam_by_player_id[player_id] = source_key

    log_players_by_source: Dict[str, Set[int]] = defaultdict(set)
    for row in con.execute(
        """
        SELECT source_player_key,player_id
        FROM player_game_logs
        WHERE league='mlb'
          AND source_player_key IS NOT NULL
          AND player_id IS NOT NULL
        GROUP BY source_player_key,player_id
        """
    ):
        log_players_by_source[str(row["source_player_key"])].add(
            int(row["player_id"])
        )

    result: Dict[str, int] = {}
    for key in sorted(source_keys):
        linked_player_ids = sorted(log_players_by_source.get(key, set()))
        if len(linked_player_ids) > 1:
            plan.player_identity_conflicts.append(
                "MLBAM {} has production log links {}".format(
                    key, linked_player_ids
                )
            )
            continue
        if linked_player_ids:
            player_id = linked_player_ids[0]
            linked_mlbam = mlbam_by_player_id.get(player_id)
            if linked_mlbam != key:
                plan.player_identity_conflicts.append(
                    "MLBAM {} production log player {} has mlbam_id {}".format(
                        key, player_id, linked_mlbam
                    )
                )
                continue
            result[key] = player_id
            continue

        player_ids = sorted(players_by_mlbam.get(key, []))
        if len(player_ids) == 1:
            result[key] = player_ids[0]
        elif len(player_ids) > 1:
            plan.player_identity_conflicts.append(
                "MLBAM {} has no log link and production players {}".format(
                    key, player_ids
                )
            )
    return result


def _dev_names_by_source(con: sqlite3.Connection) -> Dict[str, str]:
    names: Dict[str, Set[str]] = defaultdict(set)
    for row in con.execute(
        """
        SELECT l.source_player_key,p.name
        FROM player_game_logs l
        LEFT JOIN players p ON p.id=l.player_id
        WHERE l.league='mlb' AND l.source_player_key IS NOT NULL
        GROUP BY l.source_player_key,p.name
        """
    ):
        names[str(row["source_player_key"])].add(str(row["name"] or "unknown"))
    return {
        key: " / ".join(sorted(values))
        for key, values in names.items()
    }


def build_plan(
    prod_con: sqlite3.Connection,
    dev_con: sqlite3.Connection,
) -> MergePlan:
    plan = MergePlan()
    prod_rows = _load_logs(prod_con)
    dev_rows = _load_logs(dev_con)
    plan.prod_rows = len(prod_rows)
    plan.dev_rows = len(dev_rows)

    prod_by_key: Dict[NaturalKey, sqlite3.Row] = {}
    for row in prod_rows:
        key = _natural_key(row)
        if key in prod_by_key:
            plan.invalid_rows.append("duplicate production natural key {}".format(key))
        prod_by_key[key] = row

    dev_by_key: Dict[NaturalKey, sqlite3.Row] = {}
    for row in dev_rows:
        key = _natural_key(row)
        if key in dev_by_key:
            plan.invalid_rows.append("duplicate dev natural key {}".format(key))
        dev_by_key[key] = row

    dev_source_keys = {
        str(row["source_player_key"])
        for row in dev_rows
        if row["source_player_key"] is not None
    }
    prod_players = _prod_players_by_mlbam(
        prod_con, dev_source_keys, plan
    )
    dev_names = _dev_names_by_source(dev_con)
    plan.dev_player_keys = len(dev_source_keys)
    plan.resolved_player_keys = sum(
        1 for source_key in dev_source_keys if source_key in prod_players
    )
    plan.unresolved_player_keys = {
        source_key: dev_names.get(source_key, "unknown")
        for source_key in sorted(dev_source_keys)
        if source_key not in prod_players
    }

    seen_prod_keys: Set[NaturalKey] = set()
    for key, dev_row in dev_by_key.items():
        dev_stats = _stats(dev_row["stats"])
        if dev_stats is None:
            plan.invalid_rows.append("dev row {} has invalid stats JSON".format(dev_row["id"]))
            continue

        prod_row = prod_by_key.get(key)
        if prod_row is None:
            source_key = str(dev_row["source_player_key"])
            plan.inserts.append(
                PlannedInsert(
                    player_id=prod_players.get(source_key),
                    league="mlb",
                    season=int(dev_row["season"]),
                    game_no=str(dev_row["game_no"]),
                    game_id=dev_row["game_id"],
                    game_date=dev_row["game_date"],
                    team=dev_row["team"],
                    opponent=dev_row["opponent"],
                    home_away=dev_row["home_away"],
                    stats=_json_dump(dev_stats),
                    source=dev_row["source"],
                    source_player_key=source_key,
                    ingested_at=dev_row["ingested_at"],
                )
            )
            continue

        seen_prod_keys.add(key)
        plan.common_rows += 1
        prod_stats = _stats(prod_row["stats"])
        if prod_stats is None:
            plan.invalid_rows.append(
                "production row {} has invalid stats JSON".format(prod_row["id"])
            )
            continue

        added = {
            stat_key: value
            for stat_key, value in dev_stats.items()
            if stat_key not in prod_stats
        }
        conflicting = tuple(
            sorted(
                stat_key
                for stat_key in dev_stats.keys() & prod_stats.keys()
                if dev_stats[stat_key] != prod_stats[stat_key]
            )
        )
        if conflicting:
            plan.collision_rows.append(
                "{}:{}:{} keys={}".format(
                    key[1], key[2], key[3], ",".join(conflicting)
                )
            )
            plan.collision_key_count += len(conflicting)

        if not added:
            continue
        added_keys = tuple(sorted(added))
        plan.added_key_patterns[added_keys] += 1
        if set(added_keys) == {"R", "RBI"}:
            plan.exact_rrbi_updates += 1
        merged = dict(dev_stats)
        merged.update(prod_stats)
        plan.updates.append(
            PlannedUpdate(
                row_id=int(prod_row["id"]),
                key=key,
                old_stats=str(prod_row["stats"]),
                new_stats=_json_dump(merged),
                added_keys=added_keys,
                conflicting_keys=conflicting,
            )
        )

    for key in prod_by_key.keys() - seen_prod_keys:
        plan.missing_prod_counterparts.append(str(key))
    return plan


def print_plan(
    plan: MergePlan,
    prod_integrity: str,
    dev_integrity: str,
) -> None:
    print("MLB R/RBI additive merge plan")
    print("  prod integrity: {}".format(prod_integrity))
    print("  dev integrity: {}".format(dev_integrity))
    print("  production MLB rows: {}".format(plan.prod_rows))
    print("  dev MLB rows: {}".format(plan.dev_rows))
    print("  common natural-key rows: {}".format(plan.common_rows))
    print("  production rows missing in dev: {}".format(len(plan.missing_prod_counterparts)))
    print("  rows that would update: {}".format(len(plan.updates)))
    print("  rows gaining exactly R+RBI: {}".format(plan.exact_rrbi_updates))
    print("  dev-only rows that would insert: {}".format(len(plan.inserts)))
    print("  skipped collision rows (prod keys win): {}".format(len(plan.collision_rows)))
    print("  skipped conflicting JSON keys: {}".format(plan.collision_key_count))
    print("  dev player source keys: {}".format(plan.dev_player_keys))
    print("  source keys resolved by prod mlbam_id: {}".format(plan.resolved_player_keys))
    print("  unresolved source keys: {}".format(len(plan.unresolved_player_keys)))
    print("  player identity conflicts: {}".format(len(plan.player_identity_conflicts)))
    print("  invalid rows: {}".format(len(plan.invalid_rows)))
    print("  added-key patterns:")
    for keys, count in plan.added_key_patterns.most_common():
        print("    - {}: {}".format("+".join(keys), count))
    if plan.unresolved_player_keys:
        print("  unresolved source-key detail:")
        for source_key, name in plan.unresolved_player_keys.items():
            print("    - {}: {}".format(source_key, name))
    if plan.collision_rows:
        print("  first collision rows:")
        for item in plan.collision_rows[:10]:
            print("    - {}".format(item))
    if plan.player_identity_conflicts:
        print("  player identity conflict detail:")
        for item in plan.player_identity_conflicts:
            print("    - {}".format(item))
    if plan.invalid_rows:
        print("  invalid row detail:")
        for item in plan.invalid_rows[:20]:
            print("    - {}".format(item))


def apply_plan(prod_path: str, plan: MergePlan) -> dict:
    if (
        plan.invalid_rows
        or plan.player_identity_conflicts
        or plan.missing_prod_counterparts
    ):
        raise RuntimeError("refusing apply: plan validation failed")

    con = sqlite3.connect(prod_path, timeout=5)
    try:
        journal_mode = str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if journal_mode != "delete":
            raise RuntimeError(
                "production journal_mode is {}, expected delete".format(journal_mode)
            )
        con.execute("BEGIN IMMEDIATE")

        before_updates = con.total_changes
        con.executemany(
            "UPDATE player_game_logs SET stats=? WHERE id=? AND stats=?",
            [
                (row.new_stats, row.row_id, row.old_stats)
                for row in plan.updates
            ],
        )
        updated = con.total_changes - before_updates
        if updated != len(plan.updates):
            raise RuntimeError(
                "planned {} updates but applied {}; rolling back".format(
                    len(plan.updates), updated
                )
            )

        before_inserts = con.total_changes
        con.executemany(
            """
            INSERT OR IGNORE INTO player_game_logs
              (player_id,league,season,game_no,game_id,game_date,team,opponent,
               home_away,stats,source,source_player_key,ingested_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,COALESCE(?,datetime('now')))
            """,
            [
                (
                    row.player_id,
                    row.league,
                    row.season,
                    row.game_no,
                    row.game_id,
                    row.game_date,
                    row.team,
                    row.opponent,
                    row.home_away,
                    row.stats,
                    row.source,
                    row.source_player_key,
                    row.ingested_at,
                )
                for row in plan.inserts
            ],
        )
        inserted = con.total_changes - before_inserts
        if inserted != len(plan.inserts):
            raise RuntimeError(
                "planned {} inserts but applied {}; rolling back".format(
                    len(plan.inserts), inserted
                )
            )
        con.commit()
        return {"updated": updated, "inserted": inserted}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _non_negative(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return number


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--prod-db", default=DEFAULT_PROD)
    parser.add_argument("--dev-db", default=DEFAULT_DEV)
    parser.add_argument("--backup")
    parser.add_argument("--expect-prod-rows", type=_non_negative)
    parser.add_argument("--expect-common", type=_non_negative)
    parser.add_argument("--expect-exact-rrbi", type=_non_negative)
    parser.add_argument("--expect-updates", type=_non_negative)
    parser.add_argument("--expect-inserts", type=_non_negative)
    parser.add_argument("--expect-collisions", type=_non_negative)
    parser.add_argument("--expect-dev-player-keys", type=_non_negative)
    parser.add_argument("--expect-resolved-player-keys", type=_non_negative)
    parser.add_argument("--expect-unresolved-player-keys", type=_non_negative)
    args = parser.parse_args(argv)

    prod_path = os.path.abspath(args.prod_db)
    dev_path = os.path.abspath(args.dev_db)
    if prod_path == dev_path:
        parser.error("prod and dev paths must differ")
    for label, path in (("prod", prod_path), ("dev", dev_path)):
        if not os.path.isfile(path) or os.path.getsize(path) <= 0:
            parser.error("{} database is missing or empty: {}".format(label, path))

    backup_integrity = None
    if args.apply:
        expected_names = (
            "expect_prod_rows",
            "expect_common",
            "expect_exact_rrbi",
            "expect_updates",
            "expect_inserts",
            "expect_collisions",
            "expect_dev_player_keys",
            "expect_resolved_player_keys",
            "expect_unresolved_player_keys",
        )
        missing = [
            "--{}".format(name.replace("_", "-"))
            for name in expected_names
            if getattr(args, name) is None
        ]
        if not args.backup:
            missing.insert(0, "--backup")
        if missing:
            parser.error("--apply requires {}".format(", ".join(missing)))
        backup_path = os.path.abspath(args.backup)
        if backup_path in (prod_path, dev_path):
            parser.error("backup must differ from prod and dev")
        if not os.path.isfile(backup_path) or os.path.getsize(backup_path) <= 0:
            parser.error("backup is missing or empty: {}".format(backup_path))
        with closing(_ro_connection(backup_path)) as backup_con:
            backup_integrity = _integrity(backup_con)
        if backup_integrity != "ok":
            parser.error(
                "backup integrity_check returned {}".format(backup_integrity)
            )

    with closing(_ro_connection(prod_path)) as prod_con, closing(
        _ro_connection(dev_path)
    ) as dev_con:
        prod_integrity = _integrity(prod_con)
        dev_integrity = _integrity(dev_con)
        plan = build_plan(prod_con, dev_con)
    print_plan(plan, prod_integrity, dev_integrity)

    if (
        prod_integrity != "ok"
        or dev_integrity != "ok"
        or plan.invalid_rows
        or plan.player_identity_conflicts
        or plan.missing_prod_counterparts
    ):
        print("\nABORTED: plan validation failed; no writes attempted")
        return 2
    if len(plan.collision_rows) != 51:
        print(
            "\nABORTED: expected the required 51 collision rows, got {}; "
            "no writes attempted".format(len(plan.collision_rows))
        )
        return 2
    if args.dry_run:
        print("\nDone (dry-run; both databases opened read-only)")
        return 0

    actual = {
        "expect_prod_rows": plan.prod_rows,
        "expect_common": plan.common_rows,
        "expect_exact_rrbi": plan.exact_rrbi_updates,
        "expect_updates": len(plan.updates),
        "expect_inserts": len(plan.inserts),
        "expect_collisions": len(plan.collision_rows),
        "expect_dev_player_keys": plan.dev_player_keys,
        "expect_resolved_player_keys": plan.resolved_player_keys,
        "expect_unresolved_player_keys": len(plan.unresolved_player_keys),
    }
    mismatches = [
        "{} expected {}, got {}".format(
            name, getattr(args, name), value
        )
        for name, value in actual.items()
        if getattr(args, name) != value
    ]
    if mismatches:
        print("\nABORTED: plan changed; no writes attempted")
        for mismatch in mismatches:
            print("  - {}".format(mismatch))
        return 2

    result = apply_plan(prod_path, plan)
    print(
        "\nApplied MLB merge: {updated} JSON unions, {inserted} additive rows, "
        "{} collision rows preserved production values".format(
            len(plan.collision_rows), **result
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
