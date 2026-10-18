#!/usr/bin/env python3
"""Independent recomputation of the M1 global Elo Brier and log loss on 2023 to 2026 complete best-of-three matches.

The Elo update is written from the protocol (start 1500, K = 32, no surface term, updated after each event-start
date group), not copied from backend/tennis_match_backtest.py. Only the main-tour row filter is shared, so the
population matches the published one. Read-only.

  python3 -I research/tennis/match/2026-10-18/elo_m1_independent.py --db <dev DB>
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from collections import defaultdict
from itertools import groupby
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
import tennis_point_model as tpm  # noqa: E402  (shared main-tour filter only)

START, END = 20230101, 20261231
INCOMPLETE = ("RET", "W/O", "DEF", "ABD")
ELO_START, ELO_K = 1500.0, 32.0


def evaluate(db: str, tour: str) -> tuple[int, float, float]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            f"SELECT tourney_date, surface, winner_id, loser_id, best_of, score FROM tennis_{tour}_matches "
            f"WHERE {tpm.TOUR_FILTER[tour]} AND tourney_date >= 20000101 AND surface IS NOT NULL "
            f"AND winner_id IS NOT NULL AND loser_id IS NOT NULL ORDER BY tourney_date"
        ).fetchall()
    finally:
        con.close()
    elo: dict = defaultdict(lambda: ELO_START)
    n, brier_sum, log_sum = 0, 0.0, 0.0
    for date, group in groupby(rows, key=lambda r: r[0]):
        group = list(group)
        if START <= date <= END:
            for _, _, winner, loser, best_of, score in group:
                if best_of != 3 or score is None or any(token in score for token in INCOMPLETE):
                    continue
                p = 1.0 / (1.0 + 10 ** ((elo[loser] - elo[winner]) / 400.0))  # P(winner wins)
                brier_sum += (p - 1.0) ** 2
                log_sum += -math.log(min(max(p, 1e-9), 1.0 - 1e-9))
                n += 1
        updates = []
        for _, _, winner, loser, _, _ in group:
            expected = 1.0 / (1.0 + 10 ** ((elo[loser] - elo[winner]) / 400.0))
            updates.append((winner, loser, ELO_K * (1.0 - expected)))
        for winner, loser, delta in updates:
            elo[winner] += delta
            elo[loser] -= delta
    return n, brier_sum / n, log_sum / n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    for tour in ("atp", "wta"):
        n, brier, log_loss = evaluate(args.db, tour)
        print(f"{tour.upper()} n={n} brier={brier:.5f} log_loss={log_loss:.5f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
