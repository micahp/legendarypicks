#!/usr/bin/env python3
"""Assemble the CP4 evaluation inputs in an evaluation copy: verified outcomes joined to the frozen ledger (research only).

The evaluation copy is a separate database file. This step:
- opens the research database read-only and copies its verified outcome rows into the evaluation copy;
- reports, per tour, the matches with a frozen distribution, the matches with verified outcomes, and the
  matches that have both (the only ones the grader can use).

It never writes the research database, and it refuses the live database as the evaluation copy. The
evaluation copy's outcome table is a derived copy, so it is replaced on each run; the research table is not.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import research_evidence as rpe  # noqa: E402
import research_player_outcomes as rpo  # noqa: E402


def assemble(evaluation_path: str, research_path: str) -> dict:
    if evaluation_path.endswith("picks.dev.db") or os.path.abspath(evaluation_path) == os.path.abspath(research_path):
        raise SystemExit("the evaluation copy must be a separate file, not the live or research database")
    con = sqlite3.connect(f"file:{evaluation_path}?mode=rw", uri=True)
    con.row_factory = sqlite3.Row
    con.executescript(rpo.DDL)
    rpe.ensure(con)
    con.execute("ATTACH DATABASE ? AS research", (f"file:{research_path}?mode=ro",))
    copied = con.execute("SELECT COUNT(*) FROM research.research_player_match_outcomes").fetchone()[0]
    con.execute("DELETE FROM main.research_player_match_outcomes")
    con.execute("INSERT INTO main.research_player_match_outcomes SELECT * FROM research.research_player_match_outcomes")
    con.commit()
    report = {"outcome_rows_copied": copied, "per_tour": {}}
    for tour in ("atp", "wta"):
        distribution_table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='tennis_model_lock_distributions'"
        ).fetchone()
        if distribution_table:
            frozen = {r[0] for r in con.execute(
                "SELECT DISTINCT d.game_id FROM tennis_model_lock_distributions d JOIN tennis_model_locks l "
                "ON l.league=d.league AND l.game_id=d.game_id WHERE d.league=? AND d.model_version=?",
                (tour, "tennis-counts/2026-10-20"))}
        else:
            frozen = set()
        verified = {r[0] for r in con.execute(
            "SELECT DISTINCT espn_game_id FROM main.research_player_match_outcomes WHERE tour=? AND eligible_cp4=1", (tour,))}
        report["per_tour"][tour] = {"frozen_distribution_games": len(frozen), "verified_outcome_games": len(verified),
                                    "gradable_both": len(frozen & verified)}
    con.execute("DETACH DATABASE research")
    con.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--evaluation-db", required=True)
    parser.add_argument("--research-db", required=True)
    args = parser.parse_args()
    print(json.dumps(assemble(args.evaluation_db, args.research_db), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
