#!/usr/bin/env python3
"""props_coverage.py -- stage-by-stage props pipeline coverage, per league.

Why this exists. "Are props working?" was answered by a different ad-hoc query every
time it was asked, and each one measured a different stage, so the answers were not
comparable across days and no trend existed. Worse, the stage that was actually broken
kept being mis-attributed: identity was blamed for MLB's settlement gap when identity
is 19% of it, and prop LINKAGE was blamed for everything when linkage has been 100% on
every league the whole time.

The pipeline has five stages and a prop can die at any one of them:

  1. ingested    the row exists at all
  2. linked      it has a player_id AND a game_id            (100% everywhere today)
  3. identified  that player carries the publisher's espn_id
  4. fixtured    that game carries an espn_event_id
  5. graded      a prop_results row exists

Stages 3 and 4 are only interesting for props whose game has FINISHED. A pending game
is not a coverage gap, and counting it as one is what made earlier numbers unreadable.
So the settlement table is restricted to games that started more than six hours ago,
and every ungraded row there is attributed to exactly one blocker:

  identity   the player has no espn_id
  fixture    the player has an espn_id but the game has no espn_event_id
  stats      both ids are present, so the stat line is missing or the market is
             unmapped -- this is the residual, and today it is the big one

Run it against both databases. Green on one and broken on the other has hidden real
defects here before.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DBS = [
    os.path.join(HERE, "data", "picks.db"),
    os.path.join(HERE, "data", "picks.dev.db"),
]
BASELINE = os.path.join(HERE, "..", "docs", "props-coverage-baseline.json")

# How far a league's settled-grading rate may fall below its committed baseline before
# this fails. Not zero: the denominator moves as new fixtures land, so a league sitting
# exactly at its baseline would flap. Wide enough to absorb a slate, narrow enough that
# a broken settle path cannot hide inside it.
REGRESSION_TOLERANCE_PCT = 5.0

STAGE_SQL = """
SELECT g.league                                                        AS league,
       COUNT(*)                                                        AS ingested,
       COUNT(DISTINCT p.source)                                        AS sources,
       COUNT(DISTINCT g.id)                                            AS games,
       SUM(p.player_id IS NOT NULL AND p.game_id IS NOT NULL)          AS linked,
       SUM(COALESCE(pl.espn_id,'') <> '')                              AS identified,
       SUM(COALESCE(g.espn_event_id,'') <> '')                         AS fixtured,
       SUM(r.prop_id IS NOT NULL)                                      AS graded
  FROM props p
  LEFT JOIN prop_games   g  ON g.id  = p.game_id
  LEFT JOIN players      pl ON pl.id = p.player_id
  LEFT JOIN prop_results r  ON r.prop_id = p.id
 GROUP BY g.league
"""

SETTLED_SQL = """
SELECT g.league                                                        AS league,
       COUNT(*)                                                        AS settleable,
       SUM(r.prop_id IS NOT NULL)                                      AS graded,
       SUM(r.prop_id IS NULL AND COALESCE(pl.espn_id,'') = '')         AS blocked_identity,
       SUM(r.prop_id IS NULL AND COALESCE(pl.espn_id,'') <> ''
                            AND COALESCE(g.espn_event_id,'') = '')     AS blocked_fixture,
       SUM(r.prop_id IS NULL AND COALESCE(pl.espn_id,'') <> ''
                            AND COALESCE(g.espn_event_id,'') <> '')    AS blocked_stats
  FROM props p
  JOIN prop_games g  ON g.id  = p.game_id
  JOIN players    pl ON pl.id = p.player_id
  LEFT JOIN prop_results r ON r.prop_id = p.id
 WHERE g.start_time < datetime('now','-6 hours')
 GROUP BY g.league
"""

NEVER_GRADED_SQL = """
SELECT g.league AS league, p.market AS market, COUNT(*) AS rows_
  FROM props p
  JOIN prop_games g ON g.id = p.game_id
  LEFT JOIN prop_results r ON r.prop_id = p.id
 WHERE g.start_time < datetime('now','-6 hours')
 GROUP BY g.league, p.market
HAVING SUM(r.prop_id IS NOT NULL) = 0 AND rows_ >= ?
 ORDER BY rows_ DESC
"""


def _pct(part, whole) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def measure(db_path: str, min_market_rows: int = 30) -> dict:
    con = sqlite3.connect("file:{}?mode=ro".format(os.path.abspath(db_path)), uri=True)
    con.row_factory = sqlite3.Row
    try:
        stages = [dict(r) for r in con.execute(STAGE_SQL) if r["league"]]
        settled = {r["league"]: dict(r) for r in con.execute(SETTLED_SQL) if r["league"]}
        never = [dict(r) for r in con.execute(NEVER_GRADED_SQL, (min_market_rows,))
                 if r["league"]]
    finally:
        con.close()

    for row in stages:
        s = settled.get(row["league"], {})
        row["settleable"] = s.get("settleable", 0)
        row["settled_graded"] = s.get("graded", 0)
        row["settled_pct"] = _pct(row["settled_graded"], row["settleable"])
        for key in ("blocked_identity", "blocked_fixture", "blocked_stats"):
            row[key] = s.get(key, 0)
        row["pct_linked"] = _pct(row["linked"], row["ingested"])
        row["pct_identified"] = _pct(row["identified"], row["ingested"])
        row["pct_fixtured"] = _pct(row["fixtured"], row["ingested"])
    stages.sort(key=lambda r: -r["ingested"])
    return {"db": db_path, "leagues": stages, "never_graded_markets": never}


def render(result: dict, emit=print) -> None:
    emit("db: {}".format(result["db"]))
    emit("")
    emit("  {:<7} {:>8} {:>4} {:>6}  {:>7} {:>7} {:>7}".format(
        "league", "props", "src", "games", "linked", "ident", "fixture"))
    for r in result["leagues"]:
        emit("  {:<7} {:>8} {:>4} {:>6}  {:>6.1f}% {:>6.1f}% {:>6.1f}%".format(
            r["league"], r["ingested"], r["sources"], r["games"],
            r["pct_linked"], r["pct_identified"], r["pct_fixtured"]))
    emit("")
    emit("  settlement, games finished >6h ago -- every ungraded row attributed:")
    emit("  {:<7} {:>10} {:>8} {:>7}  {:>8} {:>8} {:>8}".format(
        "league", "settleable", "graded", "pct", "identity", "fixture", "stats"))
    for r in result["leagues"]:
        if not r["settleable"]:
            continue
        emit("  {:<7} {:>10} {:>8} {:>6.1f}%  {:>8} {:>8} {:>8}".format(
            r["league"], r["settleable"], r["settled_graded"], r["settled_pct"],
            r["blocked_identity"], r["blocked_fixture"], r["blocked_stats"]))
    if result["never_graded_markets"]:
        emit("")
        emit("  markets that have NEVER graded a settled row:")
        for m in result["never_graded_markets"]:
            emit("    {:<7} {:<28} {:>6}".format(m["league"], m["market"], m["rows_"]))


def check_baseline(result: dict, baseline: dict, emit=print) -> List[str]:
    """Compare against the committed baseline. Returns the list of regressions.

    The baseline is COMMITTED so that weakening it shows up in git as a diff rather
    than as a number quietly drifting down. A new league is reported, never failed:
    it has no baseline to regress against yet.
    """
    failures = []
    by_league = {r["league"]: r for r in result["leagues"]}
    for league, expected in sorted(baseline.items()):
        row = by_league.get(league)
        if row is None:
            failures.append("{}: baseline expects this league, the database has no props"
                            .format(league))
            continue
        if not row["settleable"]:
            emit("  SKIP {}: no settled props to grade in this window".format(league))
            continue
        drop = expected - row["settled_pct"]
        if drop > REGRESSION_TOLERANCE_PCT:
            failures.append(
                "{}: settled grading {:.1f}% is {:.1f} points below the baseline {:.1f}%"
                .format(league, row["settled_pct"], drop, expected))
    for league in sorted(set(by_league) - set(baseline)):
        emit("  NEW {}: {:.1f}% settled grading, no baseline committed yet"
             .format(league, by_league[league]["settled_pct"]))
    return failures


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", action="append", help="repeatable; defaults to prod and dev")
    ap.add_argument("--json", action="store_true", help="emit the measurement as JSON")
    ap.add_argument("--check", action="store_true",
                    help="compare against the committed baseline and exit 1 on regression")
    ap.add_argument("--write-baseline", action="store_true",
                    help="rewrite the baseline from the FIRST database given")
    ap.add_argument("--min-market-rows", type=int, default=30)
    args = ap.parse_args(argv)

    dbs = args.db or [p for p in DEFAULT_DBS if os.path.isfile(p)]
    if not dbs:
        print("props_coverage: no database found", file=sys.stderr)
        return 2

    results = []
    for db in dbs:
        if not os.path.isfile(db):
            print("props_coverage: missing database {}".format(db), file=sys.stderr)
            return 2
        results.append(measure(db, args.min_market_rows))

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    for result in results:
        render(result)
        print("")

    if args.write_baseline:
        baseline = {r["league"]: r["settled_pct"] for r in results[0]["leagues"]
                    if r["settleable"]}
        with open(BASELINE, "w") as fh:
            json.dump(baseline, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("props_coverage: baseline written from {}".format(results[0]["db"]))
        return 0

    if args.check:
        if not os.path.isfile(BASELINE):
            # A check whose evidence is missing is a FAIL, not a skip.
            print("props_coverage: FAIL no baseline at {} -- a check that cannot run is "
                  "not a check that passed".format(BASELINE), file=sys.stderr)
            return 1
        with open(BASELINE) as fh:
            baseline = json.load(fh)
        failures = []
        for result in results:
            print("props_coverage: checking {} against the committed baseline"
                  .format(result["db"]))
            failures += ["{}  [{}]".format(f, os.path.basename(result["db"]))
                         for f in check_baseline(result, baseline)]
        if failures:
            print("")
            for f in failures:
                print("props_coverage: FAIL {}".format(f), file=sys.stderr)
            return 1
        print("props_coverage: no league regressed against its baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
