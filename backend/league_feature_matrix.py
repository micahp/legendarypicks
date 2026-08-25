#!/usr/bin/env python3
"""Leagues x features, measured from a database rather than asserted.

    venv/bin/python league_feature_matrix.py --db data/picks.dev.db
    venv/bin/python league_feature_matrix.py --db data/picks.db --compare data/picks.dev.db

Every count cell is paired with the explicit season keys behind that surface. That
is the point: a hand-maintained feature matrix is a claim about the product, and the
claims in this repo have a habit of outliving the code
(`docs/DATA-SPINE.md` asserted MLB carried no espn_id for a week after 783 landed).
This one cannot drift, because it is derived on every run.

Marks:

    OK      the surface has rows behind it
    --      no rows: the surface renders its honest empty state
    n/a     the league does not have this surface by design
    HIDDEN  the league is not offered by this database at all

`offered` comes from `league_offering.offered_leagues`, the same registry the hub
and the search gate read. A league can be populated and still HIDDEN — ATP and
WTA on the copied 2026-08-24 database carry identities and props while remaining
unoffered, and the row shows both facts at once rather than letting one hide the
other.

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
    ("player game logs", "player_game_logs",  ""),
    ("player stats", "player_stats",        ""),
    ("team game results", "team_game_results", ""),
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
    "ufc":   {"team game results", "team stats", "coverage row", "scoring plays", "game context"},
    "wc":    {"team stats"},
    "atp":   {"team game results", "team stats", "coverage row", "scoring plays",
              "game context", "player stats"},
    "wta":   {"team game results", "team stats", "coverage row", "scoring plays",
              "game context", "player stats"},
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


def _prop_inventory(con, league: str, tables: set[str]):
    """Counts by source and market: total, graded, and reachable graded rows."""
    if not {"props", "prop_games", "prop_results"} <= tables:
        return None
    prop_columns = {row[1] for row in con.execute("PRAGMA table_info(props)")}
    game_columns = {row[1] for row in con.execute("PRAGMA table_info(prop_games)")}
    result_columns = {
        row[1] for row in con.execute("PRAGMA table_info(prop_results)")
    }
    if not {"game_id", "market", "source"} <= prop_columns:
        return None
    if not {"id", "league", "espn_event_id"} <= game_columns:
        return None
    if not {"prop_id", "actual_value"} <= result_columns:
        return None
    rows = con.execute(
        """SELECT COALESCE(NULLIF(TRIM(p.source), ''), '(blank)') AS source,
                  COALESCE(NULLIF(TRIM(p.market), ''), '(blank)') AS market,
                  COUNT(*) AS total,
                  SUM(EXISTS(SELECT 1 FROM prop_results r
                              WHERE r.prop_id=p.id AND r.actual_value IS NOT NULL)) AS graded,
                  SUM(EXISTS(SELECT 1 FROM prop_results r
                              WHERE r.prop_id=p.id AND r.actual_value IS NOT NULL)
                      AND g.espn_event_id IS NOT NULL
                      AND g.espn_event_id != '') AS reachable
             FROM props p
             JOIN prop_games g ON g.id=p.game_id
            WHERE LOWER(g.league)=?
            GROUP BY source, market
            ORDER BY source, total DESC, market""",
        (league,),
    ).fetchall()
    return [
        {
            "source": row[0],
            "market": row[1],
            "total": row[2],
            "graded": row[3] or 0,
            "reachable": row[4] or 0,
        }
        for row in rows
    ]


YEAR_SURFACES = {
    "player game logs": ("player_game_logs", "season"),
    "player stats": ("player_stats", "season"),
    "team game results": ("team_game_results", "season"),
    # team_game_stats has no season column. Its only durable season evidence is
    # the reciprocal result row for the same league/game. Report rows that
    # cannot make that join instead of assigning captured_at's calendar year.
    "team stats": ("team_game_stats", None),
}


def _years(con, label: str, league: str, tables: set[str]):
    """Return explicit season set plus rows with no season evidence."""
    table, season_column = YEAR_SURFACES[label]
    if table not in tables:
        return None
    columns = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    if "league" not in columns:
        return None
    if season_column is not None:
        if season_column not in columns:
            return None
        years = tuple(
            row[0]
            for row in con.execute(
                f"SELECT DISTINCT {season_column} FROM {table} "
                f"WHERE LOWER(league)=? AND {season_column} IS NOT NULL "
                f"ORDER BY {season_column}",
                (league,),
            )
        )
        unassigned = con.execute(
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE LOWER(league)=? AND {season_column} IS NULL",
            (league,),
        ).fetchone()[0]
        return {"years": years, "unassigned": unassigned, "basis": "explicit"}

    if "team_game_results" not in tables:
        return None
    result_columns = {
        row[1] for row in con.execute("PRAGMA table_info(team_game_results)")
    }
    if not {"league", "game_id", "season"} <= result_columns or "game_id" not in columns:
        return None
    years = tuple(
        row[0]
        for row in con.execute(
            """SELECT DISTINCT r.season
                 FROM team_game_stats s
                 JOIN team_game_results r
                   ON LOWER(r.league)=LOWER(s.league) AND r.game_id=s.game_id
                WHERE LOWER(s.league)=? AND r.season IS NOT NULL
                ORDER BY r.season""",
            (league,),
        )
    )
    unassigned = con.execute(
        """SELECT COUNT(*) FROM team_game_stats s
             WHERE LOWER(s.league)=?
               AND NOT EXISTS(
                   SELECT 1 FROM team_game_results r
                    WHERE LOWER(r.league)=LOWER(s.league)
                      AND r.game_id=s.game_id AND r.season IS NOT NULL)""",
        (league,),
    ).fetchone()[0]
    return {"years": years, "unassigned": unassigned, "basis": "result join"}


# ── product surfaces ──────────────────────────────────────────────────────────
#
# Rows in a table do not prove a page works. These ask the next question: is
# there anything BEHIND each surface a user actually opens, and can they reach
# it? Every one is measured from the database, deliberately — the ESPN-backed
# surfaces (standings, scoreboard) cannot be probed without spending a request
# budget that is a count per host, so they are listed as UNPROBED rather than
# guessed at. See .claude/skills/espn-request-budget.
SURFACE_SQL = {
    # A player page is worth opening if the person has anything on it at all.
    "player detail": """
        SELECT COUNT(*) FROM players p WHERE LOWER(p.league)=?
          AND (EXISTS(SELECT 1 FROM player_game_logs g WHERE g.player_id=p.id)
            OR EXISTS(SELECT 1 FROM player_stats s WHERE s.player_id=p.id)
            OR EXISTS(SELECT 1 FROM props pr WHERE pr.player_id=p.id))""",
    # The game-log tab specifically.
    "  w/ game log": """
        SELECT COUNT(DISTINCT g.player_id) FROM player_game_logs g
         WHERE LOWER(g.league)=? AND g.player_id IS NOT NULL""",
    # Leaders / season-stats tab.
    "  w/ season stats": """
        SELECT COUNT(DISTINCT s.player_id) FROM player_stats s
         WHERE LOWER(s.league)=? AND s.player_id IS NOT NULL""",
    # A game page needs a finished game with a score to show anything.
    "game detail": """
        SELECT COUNT(DISTINCT game_id) FROM team_game_results
         WHERE LOWER(league)=? AND status='completed' AND score_for IS NOT NULL""",
    # Props anywhere for the league.
    "props (any)": """
        SELECT COUNT(*) FROM props p JOIN prop_games g ON g.id=p.game_id
         WHERE LOWER(g.league)=?""",
    # SETTLED props — the half of the product that shows how the board did.
    #
    # `settled_at IS NOT NULL` is NOT the test, and using it was this file's own
    # instance of the mistake it exists to prevent. settlement.py stamps
    # settled_at on a prop it could not map, leaving hit and actual_value NULL —
    # so a prop that FAILED to settle is recorded in the same shape as one that
    # landed. Measured 2026-08-14: every one of the World Cup's 1,128 "settled"
    # props has a NULL outcome, i.e. WC settles nothing and has been reported at
    # 100% by every count anyone has taken, this one included. Production MLB is
    # 279,404 of 700,549 the same way. The outcome is the claim; the timestamp is
    # only evidence that something ran.
    #
    # The test is `actual_value IS NOT NULL`, not `hit IS NOT NULL`. A PUSH — the
    # stat landing exactly on the line — is a graded prop that correctly stores
    # hit=NULL beside a real actual_value (settlement.py:_grade_actual), so
    # keying on `hit` would count a legitimate result as a failed settlement.
    # There are zero pushes in either database today, because these books price
    # almost everything at .5, so this changes no current number — it is the
    # difference between a filter that is right and one that happens to agree.
    "settled props": """
        SELECT COUNT(*) FROM props p
          JOIN prop_games g ON g.id=p.game_id
          JOIN prop_results r ON r.prop_id=p.id
         WHERE LOWER(g.league)=? AND r.settled_at IS NOT NULL AND r.actual_value IS NOT NULL""",
    # Settled props REACHABLE on a game page: the page joins on espn_event_id,
    # so a settled prop on an unlinked game exists and is invisible. This is the
    # cell that separates "we have the data" from "a user can see it".
    "  on game detail": """
        SELECT COUNT(*) FROM props p
          JOIN prop_games g ON g.id=p.game_id
          JOIN prop_results r ON r.prop_id=p.id
         WHERE LOWER(g.league)=? AND r.settled_at IS NOT NULL AND r.actual_value IS NOT NULL
           AND g.espn_event_id IS NOT NULL AND g.espn_event_id!=''""",
    # The recap/preview on the game page.
    "game story": """
        SELECT COUNT(*) FROM game_story WHERE LOWER(league)=?""",
}

# ── the game page is not one surface, it is four ──────────────────────────────
#
# "prop games: 15" says props exist for a league. It does not say a reader ever
# sees them, and it says nothing at all about the three other things that page is
# supposed to do. A game detail page has a life cycle:
#
#   before   the preview text, and the props posted for the game
#   during   what is happening right now
#   after    the recap text, and how those props actually landed
#
# A league can pass one state and fail the rest — MLS carried 714 props against
# 2 of 15 linked games and zero settlements, which the old single "prop games"
# cell rendered as a healthy 15.
#
# On preview-vs-recap: `core_stories._story_is_stale_preview` decides that from
# the game's live state and start time, which are scoreboard values, not columns.
# From the database alone the honest split is whether we hold a COMPLETED result
# row for the game the story is attached to — so these two rows are named for
# what they measure and not for what we wish they measured. A story on a game
# with no result row is a preview OR a recap of a game we never ingested, and
# those are not distinguishable here.
LIFECYCLE_SQL = {
    "BEFORE — props posted": """
        SELECT COUNT(*) FROM props p JOIN prop_games g ON g.id=p.game_id
         WHERE LOWER(g.league)=? AND g.date >= DATE('now')""",
    "  reachable on the page": """
        SELECT COUNT(*) FROM props p JOIN prop_games g ON g.id=p.game_id
         WHERE LOWER(g.league)=? AND g.date >= DATE('now')
           AND g.espn_event_id IS NOT NULL AND g.espn_event_id!=''""",
    "BEFORE — story, no final": """
        SELECT COUNT(*) FROM game_story s WHERE LOWER(s.league)=?
           AND NOT EXISTS(SELECT 1 FROM team_game_results r
                           WHERE r.game_id=s.game_id AND LOWER(r.league)=LOWER(s.league)
                             AND r.status='completed')""",
    "AFTER — story, w/ final": """
        SELECT COUNT(*) FROM game_story s WHERE LOWER(s.league)=?
           AND EXISTS(SELECT 1 FROM team_game_results r
                       WHERE r.game_id=s.game_id AND LOWER(r.league)=LOWER(s.league)
                         AND r.status='completed')""",
    "AFTER — props settled": """
        SELECT COUNT(*) FROM props p
          JOIN prop_games g ON g.id=p.game_id
          JOIN prop_results r ON r.prop_id=p.id
         WHERE LOWER(g.league)=? AND r.settled_at IS NOT NULL AND r.actual_value IS NOT NULL""",
    "  shown on the page": """
        SELECT COUNT(*) FROM props p
          JOIN prop_games g ON g.id=p.game_id
          JOIN prop_results r ON r.prop_id=p.id
         WHERE LOWER(g.league)=? AND r.settled_at IS NOT NULL AND r.actual_value IS NOT NULL
           AND g.espn_event_id IS NOT NULL AND g.espn_event_id!=''""",
}

# Surfaces we cannot measure without an ESPN request. Never render these as a
# pass or a fail: "evidence unavailable" is neither.
UNPROBED = ("standings", "scoreboard / scores", "live game state")

# The DURING state is one of them, and it is not an oversight. Whether a page
# says anything useful mid-game is answered by the live scoreboard, and probing
# it costs a request budget that is a COUNT per host. Rendered as UNPROBED so the
# gap stays visible instead of reading as a zero.
LIFECYCLE_UNPROBED = "DURING — live state"


def _surface(con, sql: str, league: str, tables: set[str]) -> int | None:
    try:
        return con.execute(sql, (league,)).fetchone()[0]
    except sqlite3.Error:
        return None


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
        for t in {table for _, table, _ in FEATURES} | {"prop_games"}:
            if t in tables:
                leagues |= {r[0] for r in con.execute(
                    f"SELECT DISTINCT LOWER(league) FROM {t}")
                    if r[0] and r[0] not in NOT_A_LEAGUE}
        out = {}
        for lg in sorted(leagues):
            cells = {label: _count(con, table, lg, tables)
                     for label, table, _ in FEATURES}
            cells["props"] = _props_count(con, lg, tables)
            surfaces = {k: _surface(con, q, lg, tables) for k, q in SURFACE_SQL.items()}
            lifecycle = {k: _surface(con, q, lg, tables) for k, q in LIFECYCLE_SQL.items()}
            years = {
                label: _years(con, label, lg, tables) for label in YEAR_SURFACES
            }
            out[lg] = {
                "offered": lg in offered,
                "cells": cells,
                "prop_link": _linked_prop_games(con, lg, tables),
                "surfaces": surfaces,
                "lifecycle": lifecycle,
                "years": years,
                "prop_inventory": _prop_inventory(con, lg, tables),
            }
        return out


def mark(label: str, league: str, n: int | None) -> str:
    if label in NOT_APPLICABLE.get(league, ()):
        return "n/a"
    if n is None:
        return "n/a"
    return f"{n:,}" if n else "--"


def render(data: dict, title: str, *, props_detail: bool = False) -> None:
    labels = [l for l, _, _ in FEATURES] + ["props"]
    # Every block shares one label column so the league columns line up down the
    # whole page — a row that shifts by two characters is a row you read wrong.
    width = max(len(l) for l in
                labels + list(SURFACE_SQL) + list(LIFECYCLE_SQL) + [LIFECYCLE_UNPROBED]) + 2
    leagues = list(data)
    year_width = max(
        (
            len(_format_years(data[league]["years"].get(label)))
            for league in leagues
            for label in YEAR_SURFACES
        ),
        default=0,
    )
    colw = max(9, max(len(l) for l in leagues) + 2, year_width + 2)

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

    print("\nyears by data surface — explicit sets; gaps stay visible")
    print("-" * (width + colw * len(leagues)))
    for label in YEAR_SURFACES:
        row = "".join(
            f"{_format_years(data[league]['years'].get(label)):>{colw}}"
            for league in leagues
        )
        print(f"{label:<{width}}{row}")

    # Everything above counts rows. Everything below asks whether a reader can
    # reach them — which is a different question and the one that kept being
    # answered by assumption. These were computed on every run since this file
    # was written and never printed.
    _block(data, leagues, width, colw, "player surfaces — is the page worth opening",
           list(SURFACE_SQL)[:3])
    _block(data, leagues, width, colw,
           "game detail, by state — the page does four jobs, not one",
           list(LIFECYCLE_SQL), unprobed=LIFECYCLE_UNPROBED)

    print("\nprop_games linked to an ESPN event (unlinked props never reach a game page):")
    for l in leagues:
        pl = data[l]["prop_link"]
        if pl and pl[1]:
            flag = "" if pl[0] == pl[1] else "   <-- gap"
            print(f"  {l:<8} {pl[0]:>4} / {pl[1]:<4}{flag}")

    print("\nprops by source / market (graded, reachable, total):")
    for league in leagues:
        inventory = data[league].get("prop_inventory")
        if inventory is None:
            print(f"  {league}: n/a")
            continue
        if not inventory:
            print(f"  {league}: --")
            continue
        markets = {row["market"] for row in inventory}
        print(f"  {league}: {len(markets)} distinct market(s)")
        sources = []
        for row in inventory:
            if row["source"] not in sources:
                sources.append(row["source"])
        for source in sources:
            source_rows = [row for row in inventory if row["source"] == source]
            graded = sum(row["graded"] for row in source_rows)
            reachable = sum(row["reachable"] for row in source_rows)
            total = sum(row["total"] for row in source_rows)
            print(
                f"    {source}: {graded:,} graded / {reachable:,} reachable / "
                f"{total:,} total"
            )
            if props_detail:
                for row in source_rows:
                    print(
                        f"      {row['market']}: {row['graded']:,} / "
                        f"{row['reachable']:,} / {row['total']:,}"
                    )
        if not props_detail:
            print("    market rows hidden; pass --props-detail to print every stored value")

    print(f"\nnot measured here: {', '.join(UNPROBED)} — every one is an ESPN read,")
    print("and the budget is a count per host. Absent evidence is not a zero.")


def _block(data, leagues, width, colw, title, labels, unprobed=None):
    """One titled section of rows, drawn against the same league columns."""
    print(f"\n{title}")
    print("-" * (width + colw * len(leagues)))
    for label in labels:
        key = "lifecycle" if label in LIFECYCLE_SQL else "surfaces"
        row = "".join(f"{mark(label, l, data[l][key].get(label)):>{colw}}"
                      for l in leagues)
        print(f"{label:<{width}}{row}")
    if unprobed:
        print(f"{unprobed:<{width}}" + "".join(f"{'UNPROBED':>{colw}}" for _ in leagues))


def _format_years(value) -> str:
    if value is None:
        return "n/a"
    years = ",".join(str(year) for year in value["years"]) or "--"
    if value["unassigned"]:
        years += f" +{value['unassigned']}?"
    return years


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--compare", help="second database to render alongside")
    ap.add_argument(
        "--props-detail",
        action="store_true",
        help="print every source/market row (MLB alone can exceed 1,000 rows)",
    )
    args = ap.parse_args()
    for path in filter(None, (args.db, args.compare)):
        if not os.path.exists(path):
            print(f"no such database: {path}", file=sys.stderr)
            return 2
        render(measure(path), os.path.basename(path), props_detail=args.props_detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
