#!/usr/bin/env python3
"""Consolidate upcoming unlinked NCAAF prop games onto their ESPN event.

Dry-run by default. The durable ``scoreboard_snapshots`` table is the fixture
authority, and a row is actionable only when school pair plus kickoff resolves
to exactly one stored event. The time window matches the props slate, so this
repair cannot silently widen into historical cleanup.

Usage:
    LP_DB_PATH=/path/to/picks.dev.db python repair_ncaaf_prop_games.py
    LP_DB_PATH=/path/to/picks.dev.db python repair_ncaaf_prop_games.py --apply
"""
import argparse
import json
import os
import sqlite3

from link_prop_games import link_prop_game
from prop_game_merge import fold_prop_game


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
    props_before = connection.execute("SELECT COUNT(*) FROM props").fetchone()[0]
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
                connection.execute(
                    "UPDATE prop_games SET home=?,away=?,start_time=? WHERE id=?",
                    (action["home"], action["away"], action["start_time"],
                     action["winner_id"]),
                )
                fold_prop_game(
                    connection, action["loser_id"], action["winner_id"]
                )
        props_after = connection.execute("SELECT COUNT(*) FROM props").fetchone()[0]
        if props_after != props_before:
            raise RuntimeError(
                "prop conservation failed: {} before, {} after".format(
                    props_before, props_after
                )
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
            print(
                "  {} {} -> {} event={} props={} {} @ {}".format(
                    verb, action["loser_id"], action["winner_id"] or "self",
                    action["event_id"], action["prop_count"],
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
