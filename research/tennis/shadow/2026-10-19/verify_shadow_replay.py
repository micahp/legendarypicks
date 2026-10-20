#!/usr/bin/env python3
"""Check that the shadow replay (backend/tennis_shadow.py) reproduces the A1 forecasts row for row.

An independent A1-style replay runs over the whole scored population and records, for every row, its date, sides,
surface and the rolling_origin forecasts (M1 and M2 on 2000 history). The backend replay is then rebuilt from scratch
for a seeded sample of dates across 2000 to 2026, and every scored row on those dates is compared with the rolling
forecast. A match is never compared with its own result: only forecasts are compared.
Read-only on the database.
  python3 -I research/tennis/shadow/2026-10-19/verify_shadow_replay.py --db <DB, read-only> \
      --out research/tennis/shadow/2026-10-19/verify_shadow_replay.json
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from collections import defaultdict
from itertools import groupby
from operator import itemgetter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "research" / "tennis" / "rolling" / "2026-10-18"))
sys.path.insert(0, str(ROOT / "backend"))
import rolling_origin as ro  # noqa: E402
import tennis_shadow as shadow  # noqa: E402

TOURS = ("atp", "wta")
SAMPLE_DATES = 60
SEED = 20261019
TOLERANCE = 1e-12


def rolling_rows(conn: sqlite3.Connection, tour: str) -> dict[int, list[tuple]]:
    """A1 replay (rolling_origin.winner_records rule) that keeps each scored row's forecast, grouped by date."""
    rows = conn.execute(
        f"SELECT tourney_date, tourney_id, surface, winner_id, loser_id, best_of, score FROM tennis_{tour}_matches "
        f"WHERE {ro.tpm.TOUR_FILTER[tour]} AND tourney_date >= ? AND tourney_date <= ? "
        "AND winner_id IS NOT NULL AND loser_id IS NOT NULL ORDER BY tourney_date, match_num",
        (ro.WINNER_HISTORY_START, ro.EVAL_END),
    ).fetchall()
    full_g: dict = defaultdict(lambda: ro.ELO_START)
    full_s: dict = defaultdict(lambda: ro.ELO_START)
    scored: dict[int, list[tuple]] = defaultdict(list)
    for date, group_iter in groupby(rows, key=itemgetter(0)):
        group = list(group_iter)
        if ro.EVAL_START <= date <= ro.EVAL_END:
            for _, _, surface, winner, loser, best_of, score in group:
                if surface is None or best_of != 3 or not ro.complete(score):
                    continue
                scored[date].append((str(winner), str(loser), surface,
                                     ro.blend_p(full_g, full_s, str(winner), str(loser), surface),
                                     ro.elo_p(full_g[str(winner)], full_g[str(loser)])))
        full_updates, full_surface_updates = [], []
        for _, _, surface, winner, loser, _, _ in group:
            if surface is not None:
                full_updates.append((str(winner), str(loser), ro.ELO_K * (
                    1.0 - ro.elo_p(full_g[str(winner)], full_g[str(loser)]))))
                full_surface_updates.append((str(winner), str(loser), surface, ro.ELO_K * (
                    1.0 - ro.elo_p(full_s[(str(winner), surface)], full_s[(str(loser), surface)]))))
        for winner, loser, delta in full_updates:
            full_g[winner] += delta
            full_g[loser] -= delta
        for winner, loser, surface, delta in full_surface_updates:
            full_s[(winner, surface)] += delta
            full_s[(loser, surface)] -= delta
    return scored


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    result: dict = {"seed": SEED, "sample_dates_per_tour": SAMPLE_DATES, "tolerance": TOLERANCE, "tours": {}}
    try:
        for tour in TOURS:
            scored = rolling_rows(conn, tour)
            dates = sorted(scored)
            rng = random.Random(SEED)
            sample = sorted(rng.sample(dates, SAMPLE_DATES))
            compared = 0
            worst = {"M1": 0.0, "M2_2000": 0.0}
            surfaces = defaultdict(int)
            for date in sample:
                global_r, surface_r = shadow.ratings_before(conn, tour, date)
                for a, b, surface, p_m2_rolling, p_m1_rolling in scored[date]:
                    forecast = shadow.forecasts(global_r, surface_r, a, b, surface)
                    worst["M1"] = max(worst["M1"], abs(forecast[shadow.M1_VERSION] - p_m1_rolling))
                    worst["M2_2000"] = max(worst["M2_2000"], abs(forecast[shadow.M2_VERSION] - p_m2_rolling))
                    compared += 1
                    surfaces[surface] += 1
            if worst["M1"] > TOLERANCE or worst["M2_2000"] > TOLERANCE:
                raise SystemExit(f"{tour}: backend replay differs from the A1 forecasts: {worst}")
            result["tours"][tour] = {
                "scored_dates": len(dates), "sample_dates": len(sample), "rows_compared": compared,
                "max_abs_difference": worst, "rows_by_surface": dict(surfaces),
            }
            print(tour, "dates", len(sample), "rows", compared, "max diff", worst)
    finally:
        conn.close()
    Path(args.out).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
