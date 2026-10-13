#!/usr/bin/env python3
"""Consolidate upcoming unlinked NCAAF prop games onto their ESPN event.

Dry-run by default. The durable ``scoreboard_snapshots`` table is the fixture
authority, and a row is actionable only when its school pair resolves to exactly
one event on the same local slate day. The published kickoff replaces a stale
source time. The time window matches the props slate, so this repair cannot
silently widen into historical cleanup.

Usage:
    LP_DB_PATH=/path/to/picks.dev.db python repair_ncaaf_prop_games.py
    LP_DB_PATH=/path/to/picks.dev.db python repair_ncaaf_prop_games.py --apply
"""
import argparse
import collections
import datetime as dt
import json
import os
import sqlite3

from link_prop_games import link_prop_game
from prop_game_merge import fold_prop_game


def _table_exists(connection, table):
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _prop_merge_summary(connection, loser_id, winner_id):
    """Count prop-key overlaps and refuse folds that would discard linked history."""
    total = connection.execute(
        "SELECT COUNT(*) FROM props WHERE game_id=?", (loser_id,)
    ).fetchone()[0]
    columns = {row[1] for row in connection.execute("PRAGMA table_info(props)")}
    key_columns = {"player_id", "market", "line", "side", "source"}
    if not key_columns <= columns:
        return {"rows": total, "overlap": 0, "new": total,
                "safe": True, "reason": None}

    select = (
        "SELECT id,player_id,market,line,side,source,captured_at,odds,"
        "odds_captured_at FROM props WHERE game_id=?"
    )
    loser_rows = connection.execute(select, (loser_id,)).fetchall()
    winner_rows = connection.execute(select, (winner_id,)).fetchall()

    def key(row):
        return tuple(row[name] for name in
                     ("player_id", "market", "line", "side", "source"))

    loser_keys = collections.Counter(key(row) for row in loser_rows)
    winner_keys = collections.Counter(key(row) for row in winner_rows)
    reasons = []
    if any(count > 1 for count in loser_keys.values()):
        reasons.append("duplicate prop keys on losing game")
    if any(count > 1 for count in winner_keys.values()):
        reasons.append("duplicate prop keys on canonical game")
    overlap_keys = {prop_key for prop_key in loser_keys
                    if winner_keys.get(prop_key, 0)}
    duplicate_prop_ids = [row["id"] for row in loser_rows
                          if key(row) in overlap_keys]
    by_winner_key = {key(row): row for row in winner_rows}

    for row in loser_rows:
        keeper = by_winner_key.get(key(row))
        if keeper and row["odds_captured_at"] == keeper["odds_captured_at"] \
                and row["odds"] != keeper["odds"]:
            reasons.append("conflicting odds at the same capture time")
            break

    if duplicate_prop_ids:
        placeholders = ",".join("?" for _ in duplicate_prop_ids)
        for table in ("prop_results", "prop_odds_snapshots"):
            if _table_exists(connection, table):
                count = connection.execute(
                    "SELECT COUNT(*) FROM {} WHERE prop_id IN ({})".format(
                        table, placeholders
                    ), duplicate_prop_ids,
                ).fetchone()[0]
                if count:
                    reasons.append("overlapping props have {} history rows".format(table))

    if _table_exists(connection, "prop_game_source_ids"):
        conflict = connection.execute(
            """SELECT COUNT(*) FROM prop_game_source_ids losing
               JOIN prop_game_source_ids keeping
                 ON keeping.source=losing.source
                AND keeping.league=losing.league
                AND keeping.source_game_key=losing.source_game_key
               WHERE losing.game_id=? AND keeping.game_id=?""",
            (loser_id, winner_id),
        ).fetchone()[0]
        if conflict:
            reasons.append("conflicting source-game mappings")

    overlap = len(overlap_keys)
    return {
        "rows": len(loser_rows),
        "overlap": overlap,
        "new": len(loser_rows) - overlap,
        "safe": not reasons,
        "reason": "; ".join(reasons) if reasons else None,
    }


def _merge_duplicate_props(connection, loser_id, winner_id):
    """Move props and keep the freshest captured quote for an already-held key."""
    summary = _prop_merge_summary(connection, loser_id, winner_id)
    if not summary["safe"]:
        raise RuntimeError(
            "unsafe prop merge {} -> {}: {}".format(
                loser_id, winner_id, summary["reason"]
            )
        )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(props)")}
    key_columns = {"player_id", "market", "line", "side", "source"}
    if not key_columns <= columns:
        return 0

    select = (
        "SELECT id,player_id,market,line,side,source,captured_at,odds,"
        "odds_captured_at FROM props WHERE game_id=?"
    )
    loser_rows = connection.execute(select, (loser_id,)).fetchall()
    winner_rows = connection.execute(select, (winner_id,)).fetchall()

    def key(row):
        return tuple(row[name] for name in
                     ("player_id", "market", "line", "side", "source"))

    winner_by_key = {key(row): row for row in winner_rows}
    removed = 0
    for row in loser_rows:
        keeper = winner_by_key.get(key(row))
        if keeper is None:
            connection.execute(
                "UPDATE props SET game_id=? WHERE id=?", (winner_id, row["id"])
            )
            continue

        captured_at = max(row["captured_at"] or "", keeper["captured_at"] or "")
        odds_at = max(row["odds_captured_at"] or "",
                      keeper["odds_captured_at"] or "")
        odds = keeper["odds"]
        if row["odds_captured_at"] and row["odds_captured_at"] >= (
                keeper["odds_captured_at"] or ""):
            odds = row["odds"]
        connection.execute(
            "UPDATE props SET captured_at=?,odds=?,odds_captured_at=? WHERE id=?",
            (captured_at, odds, odds_at or None, keeper["id"]),
        )
        connection.execute("DELETE FROM props WHERE id=?", (row["id"],))
        removed += 1
    return removed


def _minutes_apart(first, second):
    try:
        a = dt.datetime.fromisoformat(str(first).replace("Z", "+00:00"))
        b = dt.datetime.fromisoformat(str(second).replace("Z", "+00:00"))
        if a.tzinfo is None:
            a = a.replace(tzinfo=dt.timezone.utc)
        if b.tzinfo is None:
            b = b.replace(tzinfo=dt.timezone.utc)
        return int((a - b).total_seconds() / 60)
    except (TypeError, ValueError):
        return None


def _published_games(connection):
    games = {}
    for row in connection.execute(
        "SELECT payload FROM scoreboard_snapshots WHERE LOWER(league)='ncaaf'"
    ):
        try:
            game = json.loads(row[0])
        except (TypeError, ValueError):
            raise RuntimeError("malformed NCAAF scoreboard snapshot payload")
        game_id = str(game.get("game_id") or "")
        if not game_id:
            raise RuntimeError("NCAAF scoreboard snapshot is missing game_id")
        prior = games.setdefault(game_id, game)
        if prior != game:
            raise RuntimeError(
                "NCAAF scoreboard event {} has conflicting snapshots".format(game_id)
            )
    if not games:
        raise RuntimeError("NCAAF scoreboard snapshot population is empty")
    return games


def plan(connection):
    """Return exact links/folds plus rows that cannot be proved."""
    published = _published_games(connection)
    rows = connection.execute(
        """SELECT pg.id,pg.league,pg.date,pg.home,pg.away,
                  pg.espn_event_id,pg.start_time,COUNT(p.id) AS prop_count
           FROM prop_games pg
           LEFT JOIN props p ON p.game_id=pg.id
           WHERE pg.league='ncaaf'
             AND COALESCE(pg.espn_event_id,'')=''
             AND p.id IS NOT NULL
             AND datetime(COALESCE(NULLIF(pg.start_time,''),
                 date(pg.date,'+1 day') || 'T05:00:00'))
                 >= datetime('now','-3 hours')
           GROUP BY pg.id
           ORDER BY pg.date,pg.start_time,pg.id"""
    ).fetchall()
    actions, unresolved = [], []
    espn_games = list(published.values())
    for row in rows:
        event_id = str(link_prop_game(connection, row, espn_games) or "")
        if not event_id:
            unresolved.append(row["id"])
            continue
        holders = connection.execute(
            "SELECT id FROM prop_games WHERE league='ncaaf' AND espn_event_id=?",
            (event_id,),
        ).fetchall()
        if len(holders) > 1:
            raise RuntimeError(
                "ESPN event {} has {} prop_game holders".format(event_id, len(holders))
            )
        game = published[event_id]
        holder_id = holders[0]["id"] if holders else None
        if holder_id is not None:
            prop_summary = _prop_merge_summary(connection, row["id"], holder_id)
            if not prop_summary["safe"]:
                unresolved.append(row["id"])
                continue
        actions.append({
            "loser_id": row["id"],
            "winner_id": holder_id,
            "event_id": event_id,
            "home": (game.get("home") or {}).get("name"),
            "away": (game.get("away") or {}).get("name"),
            "start_time": game.get("date"),
            "prop_count": row["prop_count"],
        })
    return actions, unresolved


def apply(connection, actions):
    """Apply a previously inspected plan in one transaction."""
    connection.execute("BEGIN IMMEDIATE")
    current_actions, unresolved = plan(connection)
    if unresolved:
        connection.rollback()
        raise RuntimeError(
            "repair plan changed; unresolved rows appeared: {}".format(
                ",".join(map(str, unresolved))
            )
        )
    requested_keys = sorted(
        (action["loser_id"], action["winner_id"], action["event_id"])
        for action in actions
    )
    current_keys = sorted(
        (action["loser_id"], action["winner_id"], action["event_id"])
        for action in current_actions
    )
    if current_keys != requested_keys:
        connection.rollback()
        raise RuntimeError("repair plan changed before apply; no rows were written")
    actions = current_actions
    props_before = connection.execute("SELECT COUNT(*) FROM props").fetchone()[0]
    source_ids_before = (
        connection.execute("SELECT COUNT(*) FROM prop_game_source_ids").fetchone()[0]
        if _table_exists(connection, "prop_game_source_ids") else None
    )
    expected_removed = 0
    with connection:
        for action in actions:
            if action["winner_id"] is None:
                connection.execute(
                    """UPDATE prop_games
                       SET espn_event_id=?,home=?,away=?,start_time=?
                       WHERE id=? AND league='ncaaf'
                         AND COALESCE(espn_event_id,'')=''""",
                    (action["event_id"], action["home"], action["away"],
                     action["start_time"], action["loser_id"]),
                )
            else:
                prop_summary = _prop_merge_summary(
                    connection, action["loser_id"], action["winner_id"]
                )
                if not prop_summary["safe"]:
                    raise RuntimeError(
                        "unsafe prop merge {} -> {}: {}".format(
                            action["loser_id"], action["winner_id"],
                            prop_summary["reason"],
                        )
                    )
                removed = _merge_duplicate_props(
                    connection, action["loser_id"], action["winner_id"]
                )
                if removed != prop_summary["overlap"]:
                    raise RuntimeError(
                        "prop overlap changed during apply: planned {}, merged {}".format(
                            prop_summary["overlap"], removed
                        )
                    )
                expected_removed += removed
                connection.execute(
                    "UPDATE prop_games SET home=?,away=?,start_time=? WHERE id=?",
                    (action["home"], action["away"], action["start_time"],
                     action["winner_id"]),
                )
                fold_prop_game(
                    connection, action["loser_id"], action["winner_id"]
                )
        props_after = connection.execute("SELECT COUNT(*) FROM props").fetchone()[0]
        if props_after != props_before - expected_removed:
            raise RuntimeError(
                "prop conservation failed: {} before, {} expected after, {} actual".format(
                    props_before, props_before - expected_removed, props_after
                )
            )
        if source_ids_before is not None:
            source_ids_after = connection.execute(
                "SELECT COUNT(*) FROM prop_game_source_ids"
            ).fetchone()[0]
            if source_ids_after != source_ids_before:
                raise RuntimeError(
                    "source-game mapping conservation failed: {} before, {} after".format(
                        source_ids_before, source_ids_after
                    )
                )
        for action in actions:
            if action["winner_id"] is None:
                continue
            loser_id = action["loser_id"]
            if connection.execute(
                    "SELECT 1 FROM prop_games WHERE id=?", (loser_id,)
            ).fetchone():
                raise RuntimeError("losing prop_game {} remains after fold".format(loser_id))
            if connection.execute(
                    "SELECT 1 FROM props WHERE game_id=? LIMIT 1", (loser_id,)
            ).fetchone():
                raise RuntimeError("props still reference losing game {}".format(loser_id))
            if _table_exists(connection, "prop_game_source_ids") and connection.execute(
                    "SELECT 1 FROM prop_game_source_ids WHERE game_id=? LIMIT 1",
                    (loser_id,),
            ).fetchone():
                raise RuntimeError(
                    "source-game mappings still reference losing game {}".format(loser_id)
                )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    db_path = os.environ.get("LP_DB_PATH")
    if not db_path:
        raise SystemExit("LP_DB_PATH is required")
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        actions, unresolved = plan(connection)
        folds = sum(action["winner_id"] is not None for action in actions)
        links = len(actions) - folds
        print(
            "NCAAF unlinked plan: {} folds, {} links, {} unresolved".format(
                folds, links, len(unresolved)
            )
        )
        for action in actions:
            verb = "FOLD" if action["winner_id"] is not None else "LINK"
            old = connection.execute(
                "SELECT start_time FROM prop_games WHERE id=?",
                (action["loser_id"],),
            ).fetchone()
            old_start = old["start_time"] if old else None
            kickoff_delta = _minutes_apart(old_start, action["start_time"])
            prop_summary = (
                _prop_merge_summary(
                    connection, action["loser_id"], action["winner_id"]
                ) if action["winner_id"] is not None else
                {"rows": action["prop_count"], "overlap": 0,
                 "new": action["prop_count"]}
            )
            print(
                "  {} {} -> {} event={} props={} overlap={} new={} "
                "kickoff_delta={}m {} @ {}".format(
                    verb, action["loser_id"], action["winner_id"] or "self",
                    action["event_id"], prop_summary["rows"],
                    prop_summary["overlap"], prop_summary["new"],
                    kickoff_delta if kickoff_delta is not None else "unknown",
                    action["away"], action["home"],
                )
            )
        if unresolved:
            print("  unresolved ids: {}".format(",".join(map(str, unresolved))))
        if args.apply:
            if unresolved:
                raise SystemExit(
                    "REFUSED apply: {} upcoming NCAAF rows are unresolved".format(
                        len(unresolved)
                    )
                )
            apply(connection, actions)
            print("APPLIED {} NCAAF prop-game repairs".format(len(actions)))
        else:
            print("dry run: nothing written")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
