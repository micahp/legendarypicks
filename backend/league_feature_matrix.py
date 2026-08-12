#!/usr/bin/env python3
"""Leagues x features, measured from a database rather than asserted.

    venv/bin/python league_feature_matrix.py --db data/picks.dev.db
    venv/bin/python league_feature_matrix.py --db data/picks.db --compare data/picks.dev.db

Every cell is a COUNT of the rows that back a surface, turned into a mark. That is
the point: a hand-maintained feature matrix is a claim about the product, and the
claims in this repo have a habit of outliving the code
(`docs/DATA-SPINE.md` asserted MLB carried no espn_id for a week after 783 landed).
This one cannot drift, because it is derived on every run.

Marks:

    OK      the surface has rows behind it
    --      no rows: the surface renders its honest empty state
    n/a     the league does not have this surface by design
    HIDDEN  the league is not offered by this database at all

`offered` comes from `league_offering.offered_leagues`, the same registry the hub
and the search gate read. A league can be fully populated and still HIDDEN — that
is exactly NCAAF on production today, and the row shows both facts at once rather
than letting one hide the other.

What this does NOT measure: whether a page renders. Rows are necessary and not
sufficient, and a green row here is a claim about the database, not about the
pixels. See .claude/skills/honest-data-ui.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from contextlib import closing

from league_offering import offered_leagues

# (label, table, extra predicate) — one row per product surface. `None` table
# means the check is computed specially below.
FEATURES = [
    ("players",      "players",             ""),
    ("game logs",    "player_game_logs",    ""),
    ("season stats", "player_stats",        ""),
    ("game detail",  "team_game_results",   ""),
    ("team stats",   "team_game_stats",     ""),
    ("coverage row", "team_stats_coverage", ""),
    ("scoring plays", "scoring_plays",      ""),
    ("game context", "game_context",        ""),
    ("stories",      "game_story",          ""),
    ("news",         "news_items",          ""),
    ("prop games",   "prop_games",          ""),
]

# Surfaces a league does not have by design, so an empty cell is not a gap.
# Stated per league rather than inferred: "we never built it" and "it broke" look
# identical in a count, and only one of them is a defect.
NOT_APPLICABLE = {
    "ufc":   {"game detail", "team stats", "coverage row", "scoring plays", "game context"},
    "wc":    {"team stats"},
    "atp":   {"game detail", "team stats", "coverage row", "scoring plays",
              "game context", "game logs", "season stats"},
    "wta":   {"game detail", "team stats", "coverage row", "scoring plays",
              "game context", "game logs", "season stats"},
    "lcup":  {"team stats", "coverage row"},
}


# news_items classifies by topic, not only by league, so it carries buckets that
# are not leagues at all. Excluded by name rather than by guessing at a shape —
# "esports" is a real product surface, it just is not a league on this matrix.
NOT_A_LEAGUE = {"esports", "unclassified", "", None}


def _tables(con) -> set[str]:
    return {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _count(con, table: str, league: str, tables: set[str]) -> int | None:
    """Rows for this league, or None when the table/column isn't there."""
    if table not in tables:
        return None
    cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    if "league" not in cols:
        return None
    try:
        return con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE LOWER(league)=?", (league,)
        ).fetchone()[0]
    except sqlite3.Error:
        return None


def _props_count(con, league: str, tables: set[str]) -> int | None:
    """Props are only reachable through a linked prop_game, so count the join."""
    if not {"props", "prop_games"} <= tables:
        return None
    return con.execute(
        "SELECT COUNT(*) FROM props p JOIN prop_games g ON g.id=p.game_id "
        "WHERE LOWER(g.league)=?", (league,)
    ).fetchone()[0]


def _linked_prop_games(con, league: str, tables: set[str]) -> tuple[int, int] | None:
    """(linked, total) prop_games — an unlinked game's props never reach a page."""
    if "prop_games" not in tables:
        return None
    row = con.execute(
        "SELECT SUM(espn_event_id IS NOT NULL AND espn_event_id!=''), COUNT(*) "
        "FROM prop_games WHERE LOWER(league)=?", (league,)
    ).fetchone()
    return (row[0] or 0, row[1] or 0)


def measure(path: str) -> dict:
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        tables = _tables(con)
        offered = offered_leagues(con)
        leagues = set()
        # Discover from every table that can carry a league, not a chosen few:
        # Leagues Cup has game_story rows and nothing else, so a narrower probe
        # would leave it off the matrix entirely — the exact blind spot this
        # tool exists to remove.
        for t in ("players", "prop_games", "team_stats_coverage",
                  "game_story", "news_items", "team_game_results"):
            if t in tables:
                leagues |= {r[0] for r in con.execute(
                    f"SELECT DISTINCT LOWER(league) FROM {t}")
                    if r[0] and r[0] not in NOT_A_LEAGUE}
        out = {}
        for lg in sorted(leagues):
            cells = {label: _count(con, table, lg, tables)
                     for label, table, _ in FEATURES}
            cells["props"] = _props_count(con, lg, tables)
            out[lg] = {
                "offered": lg in offered,
                "cells": cells,
                "prop_link": _linked_prop_games(con, lg, tables),
            }
        return out


def mark(label: str, league: str, n: int | None) -> str:
    if label in NOT_APPLICABLE.get(league, ()):
        return "n/a"
    if n is None:
        return "n/a"
    return f"{n:,}" if n else "--"


def render(data: dict, title: str) -> None:
    labels = [l for l, _, _ in FEATURES] + ["props"]
    width = max(len(l) for l in labels) + 2
    leagues = list(data)
    colw = max(9, max(len(l) for l in leagues) + 2)

    print(f"\n{title}")
    print("=" * (width + colw * len(leagues)))
    print(" " * width + "".join(f"{l:>{colw}}" for l in leagues))
    print(" " * width + "".join(
        f"{('OFFERED' if data[l]['offered'] else 'HIDDEN'):>{colw}}" for l in leagues))
    print("-" * (width + colw * len(leagues)))
    for label in labels:
        row = "".join(f"{mark(label, l, data[l]['cells'].get(label)):>{colw}}"
                      for l in leagues)
        print(f"{label:<{width}}{row}")

    print("\nprop_games linked to an ESPN event (unlinked props never reach a game page):")
    for l in leagues:
        pl = data[l]["prop_link"]
        if pl and pl[1]:
            flag = "" if pl[0] == pl[1] else "   <-- gap"
            print(f"  {l:<8} {pl[0]:>4} / {pl[1]:<4}{flag}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--compare", help="second database to render alongside")
    args = ap.parse_args()
    for path in filter(None, (args.db, args.compare)):
        if not os.path.exists(path):
            print(f"no such database: {path}", file=sys.stderr)
            return 2
        render(measure(path), os.path.basename(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
