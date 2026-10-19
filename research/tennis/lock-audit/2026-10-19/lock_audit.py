#!/usr/bin/env python3
"""Lock-table audit: which forecast rule wrote each row of tennis_model_locks.

For every locked tennis match, the Elo state is rebuilt from matches dated from 2020-01-01 up to, but not
including, the match day, as in backend/tennis_daily_projections.py (HISTORY_START and the cutoff). The stored
probability is then compared with two rules: global Elo alone, and the 50/50 logit blend of global and surface
Elo for each surface. The rule that reproduces the stored probability (to 1e-9) is the rule that wrote the row.
The Elo replay reuses research/tennis/rolling/2026-10-18/rolling_origin.py. Read-only on every database.
  python3 -I research/tennis/lock-audit/2026-10-19/lock_audit.py --db prod=<DB> --db dev=<DB> \
      --out research/tennis/lock-audit/2026-10-19/lock_audit.json
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from itertools import groupby
from operator import itemgetter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "research" / "tennis" / "rolling" / "2026-10-18"))
import rolling_origin as ro  # noqa: E402

TOLERANCE = 1e-9
SURFACES = ("Hard", "Clay", "Grass")
SCALE = math.log(10.0) / 400.0


def live_state(con: sqlite3.Connection, tour: str, cutoff: int) -> tuple[dict, dict]:
    """Global and surface Elo from 2020-01-01 to the day before `cutoff`, with the live update rule."""
    # Ids are text in the live code (str(row[2])); the match tables store integers.
    rows = con.execute(
        f"SELECT tourney_date, surface, CAST(winner_id AS TEXT), CAST(loser_id AS TEXT) FROM tennis_{tour}_matches "
        f"WHERE {ro.tpm.TOUR_FILTER[tour]} AND tourney_date BETWEEN ? AND ? "
        "AND winner_id IS NOT NULL AND loser_id IS NOT NULL ORDER BY tourney_date, match_num",
        (ro.LIVE_HISTORY_START, cutoff - 1),
    ).fetchall()
    g: dict = defaultdict(lambda: ro.ELO_START)
    s: dict = defaultdict(lambda: ro.ELO_START)
    for _, group_iter in groupby(rows, key=itemgetter(0)):
        group = list(group_iter)
        global_updates = [(w, lo, ro.ELO_K * (1.0 - ro.elo_p(g[w], g[lo]))) for _, _, w, lo in group]
        surface_updates = [(w, lo, surf, ro.ELO_K * (1.0 - ro.elo_p(s[(w, surf)], s[(lo, surf)])))
                           for _, surf, w, lo in group if surf]
        for w, lo, delta in global_updates:
            g[w] += delta
            g[lo] -= delta
        for w, lo, surf, delta in surface_updates:
            s[(w, surf)] += delta
            s[(lo, surf)] -= delta
    return g, s


def rules(g: dict, s: dict, home: str, away: str) -> dict[str, float]:
    """Home-side probability under each rule. Returned as the probability of the favourite, as stored."""
    p_global = ro.tdp._logistic((g[home] - g[away]) * SCALE)
    out = {"global_only": p_global}
    for surf in SURFACES:
        p_surface = ro.tdp._logistic((s[(home, surf)] - s[(away, surf)]) * SCALE)
        out[f"blend_{surf}"] = ro.tdp._logistic(0.5 * (ro.tdp._logit(p_global) + ro.tdp._logit(p_surface)))
    return {k: max(p, 1.0 - p) for k, p in out.items()}


def event_of(con: sqlite3.Connection, league: str, game_id: str) -> dict[str, Any]:
    row = con.execute("SELECT payload FROM scoreboard_snapshots WHERE league=? AND game_id=? LIMIT 1",
                      (league, game_id)).fetchone()
    payload = json.loads(row[0]) if row else {}
    return {"tournament_id": payload.get("tournament_id"), "event": payload.get("event")}


def audit(label: str, path: str) -> dict[str, Any]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        locks = con.execute(
            "SELECT league, game_id, game_date, start_time, locked_at, projection, model_version "
            "FROM tennis_model_locks ORDER BY locked_at, league, game_id"
        ).fetchall()
        states: dict[tuple[str, int], tuple[dict, dict]] = {}
        records = []
        for league, game_id, game_date, start_time, locked_at, projection, model_version in locks:
            proj = json.loads(projection)
            ids = proj.get("_sackmannPlayerIds") or {}
            rec: dict[str, Any] = {"league": league, "game_id": game_id, "game_date": game_date,
                                   "locked_at": locked_at, "model_version": model_version,
                                   "projection_modelVersion": proj.get("modelVersion"),
                                   "stored_probability": proj.get("probability"),
                                   **event_of(con, league, game_id)}
            if not ids.get("home") or not ids.get("away") or proj.get("probability") is None:
                rec["rule"] = "unresolved"
                records.append(rec)
                continue
            cutoff = int(game_date.replace("-", ""))
            if (league, cutoff) not in states:
                states[(league, cutoff)] = live_state(con, league, cutoff)
            g, s = states[(league, cutoff)]
            candidates = rules(g, s, ids["home"], ids["away"])
            matched = [k for k, v in candidates.items() if abs(v - proj["probability"]) < TOLERANCE]
            rec["rule_values"] = {k: round(v, 12) for k, v in candidates.items()}
            rec["matched_rules"] = matched
            rec["rule"] = matched[0] if len(matched) == 1 else ("ambiguous" if matched else "none")
            records.append(rec)
    finally:
        con.close()
    tally = Counter((r["model_version"], r["rule"]) for r in records)
    return {"db": label, "rows": len(records), "tally": {f"{v} | {r}": n for (v, r), n in sorted(tally.items())},
            "records": records}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", action="append", required=True, help="label=path, read-only")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = {"tolerance": TOLERANCE, "databases": []}
    for item in args.db:
        label, path = item.split("=", 1)
        result["databases"].append(audit(label, path))
    Path(args.out).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    for db in result["databases"]:
        print(db["db"], "rows", db["rows"])
        for key, n in db["tally"].items():
            print("  ", key, n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
