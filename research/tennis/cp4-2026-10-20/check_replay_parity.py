#!/usr/bin/env python3
"""Check that the lock-path distributions reproduce the replays' own scores on real rows.

For each replay row in the window, the PMF rebuilt from history dated before that day must give
the same CRPS and log score the replay recorded. Read-only on the database. One history is held
at a time, so memory stays bounded.

  python3 research/tennis/cp4-2026-10-20/check_replay_parity.py --db /root/picks.tennis-cp4.db --max-days 12
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend"))

import tennis_count_distributions as tcd  # noqa: E402
import tennis_props_rate_backtest as rb  # noqa: E402
import tennis_total_games_backtest as tgb  # noqa: E402


def iso(day):
    return f"{day // 10000:04d}-{(day // 100) % 100:02d}-{day % 100:02d}"


def history(db, tour, day):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return tcd.build_history(con, tour, iso(day))
    finally:
        con.close()


def replay_games(db, tour, start, end):
    """The total-games replay with its simulator stubbed (not a candidate) and the CP4 history start."""
    original_simulator = tgb.simulator_distribution
    original_start = tgb.HISTORY_START
    tgb.simulator_distribution = lambda a, b, rules, support: (
        [1.0 / len(support)] * len(support), 0.0,
        {"expected_sets": 0.0, "p_deciding_set": 0.0, "p_any_tiebreak": 0.0,
         "expected_set_games": 0.0, "expected_tiebreak_sets": 0.0})
    tgb.HISTORY_START = tcd.HISTORY_START
    try:
        records, _ = tgb.run(db, tour, start=start, end=end)
    finally:
        tgb.HISTORY_START = original_start
        tgb.simulator_distribution = original_simulator
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--db", required=True)
    parser.add_argument("--start", type=int, default=20260401)
    parser.add_argument("--end", type=int, default=20260601)
    parser.add_argument("--max-days", type=int, default=12, help="first N replay days per tour to check")
    args = parser.parse_args()

    worst = {"count": 0.0, "games": 0.0}
    checked = {"count": 0, "games": 0}
    for tour in ("atp", "wta"):
        count_rows = list(rb.run(args.db, tour, start=args.start, end=args.end))
        game_records = replay_games(args.db, tour, args.start, args.end)
        days = sorted({int(row["date"]) for row in count_rows} | {int(r["date"]) for r in game_records})
        days = days[:args.max_days]
        for day in days:
            history_for_day = history(args.db, tour, day)
            for row in (r for r in count_rows if int(r["date"]) == day):
                for target in ("aces", "double_faults"):
                    if row["target"] != target:
                        continue
                    parameters = tcd.count_parameters(history_for_day, target, str(row["player_id"]),
                                                      row["surface"], iso(day))
                    scores = rb.score_pmf(tcd.count_pmf_from_parameters(parameters), int(row["actual"]))
                    worst["count"] = max(worst["count"],
                                         abs(scores["crps"] - row["p1_gamma_poisson_crps"]),
                                         abs(scores["log_score"] - row["p1_gamma_poisson_log_score"]))
                    checked["count"] += 1
            for record in (r for r in game_records if int(r["date"]) == day):
                pmf, _ = tcd.games_distribution(history_for_day, record["format"], record["surface"],
                                                record["elo_gap"], iso(day))
                scores = tgb.pmf_scores(pmf, tgb.support_for(record["format"]), int(record["actual_games"]))
                worst["games"] = max(worst["games"],
                                     abs(scores["crps"] - record["direct_surface_competitive_crps"]),
                                     abs(scores["log_score"] - record["direct_surface_competitive_log_score"]))
                checked["games"] += 1
            print(f"{tour} day {iso(day)} done", flush=True)
    print(f"count targets checked {checked['count']}, max abs diff {worst['count']!r}")
    print(f"games rows checked {checked['games']}, max abs diff {worst['games']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
