#!/usr/bin/env python3
"""Strictly check v2 Zf with only the parameter precision preserved in frozen-v2.json."""
import argparse
import importlib
import io
import json
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from statistics import mean


SOURCE_COMMIT = "a9a46bd05ee75456ee906a6f1254ab5176084f13"
PARAM_FILE = "research/nfl/discrete-prop-eval-2026-10-18/frozen-inputs/frozen-v2.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="the immutable SQLite snapshot used for the check")
    ap.add_argument("--tolerance", type=float, default=1e-10)
    a = ap.parse_args()
    repo = Path(__file__).resolve().parents[3]
    frozen = json.loads((repo / PARAM_FILE).read_text())
    con = sqlite3.connect("file:%s?mode=ro" % Path(a.db).resolve(), uri=True)
    con.execute("PRAGMA query_only=ON")

    with tempfile.TemporaryDirectory(prefix="lp-v2-check-") as temp:
        archive = subprocess.run(
            ["git", "archive", SOURCE_COMMIT, "backend/nfl_player_projection_v2.py",
             "backend/nfl_rushing_participation_v2.py"],
            cwd=repo, check=True, stdout=subprocess.PIPE)
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as tf:
            tf.extractall(temp)
        sys.path.insert(0, str(Path(temp) / "backend"))
        mod = importlib.import_module("nfl_rushing_participation_v2")
        hist = mod.eng.History.load(con, [2024, 2025, 2026])

        checks = {}
        for season in (2025, 2026):
            items = mod.build_items(hist, season, weeks=set(range(3, 19)))
            saved = frozen["seasons"][str(season)]
            fit0 = saved["fit"]
            p_cross = {}
            for key, value in fit0["cross_cells"].items():
                recent, status = key.split("|", 1)
                p_cross[(int(recent[0]), bool(int(recent[1])), status)] = value
            fit = {"R": fit0["R"], "p_cross": p_cross}
            vals = {k: [] for k in ("crps", "mae", "cov50", "cov80", "cov90")}
            for item in items:
                pmf = mod.pmf_for("Zf", item, fit)
                cdf = mod.cdf_of(pmf)
                mu = mod.mean_of(pmf)
                y = int(item["y"])
                vals["crps"].append(mod.crps_discrete(cdf, y))
                vals["mae"].append(abs(mu - y))
                for level in (0.5, 0.8, 0.9):
                    vals["cov%d" % int(level * 100)].append(mod.covered(cdf, y, level))
            computed = {k: mean(v) for k, v in vals.items()}
            reported = saved["tables"]["all (pregame candidates)|Zf"]
            delta = {k: computed[k] - reported[k] for k in computed}
            checks[str(season)] = {
                "n": len(items), "games": len({i["game_id"] for i in items}),
                "saved_cross_cell_decimal_places": 4,
                "computed": computed, "reported": {k: reported[k] for k in computed},
                "delta": delta,
                "match": max(abs(x) for x in delta.values()) <= a.tolerance,
                "tolerance": a.tolerance,
                "stop_reason": "saved cross-cell probabilities are rounded to four decimals; no refit or replacement values used",
            }
        con.close()
    print(json.dumps(checks, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
