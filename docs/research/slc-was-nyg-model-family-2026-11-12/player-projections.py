#!/usr/bin/env python3
"""Export per-player empirical distributions from the saved WAS-NYG model batches."""
import argparse
import csv
import glob
import json
import math
import statistics
from pathlib import Path

PARSER = argparse.ArgumentParser()
PARSER.add_argument("--run-root", type=Path, required=True)
PARSER.add_argument("--out", type=Path, required=True)
ARGS = PARSER.parse_args()
MODELS = ("v1", "v1.5", "v1.6", "v2")
METRICS = {
    "pass_yards": ("passing", "yds"), "pass_attempts": ("passing", "att"),
    "pass_completions": ("passing", "comp"),
    "pass_tds": ("passing", "td"), "interceptions": ("passing", "int"),
    "rush_yards": ("rushing", "yds"), "carries": ("rushing", "att"),
    "rush_tds": ("rushing", "td"), "receiving_yards": ("receiving", "yds"),
    "receptions": ("receiving", "rec"), "targets": ("receiving", "tgt"),
    "receiving_tds": ("receiving", "td"), "fumbles_lost": ("miscellaneous", "fumbles_lost"),
}

def quantile(values, p):
    xs = sorted(values)
    pos = (len(xs) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)

rows = []
for model in MODELS:
    games = {}
    for path in glob.glob(str(ARGS.run_root / "runs" / model / "*.boxscores.jsonl")):
        with open(path) as stream:
            for line in stream:
                row = json.loads(line)
                if row.get("status") == "valid_complete":
                    if row["seed"] in games:
                        raise ValueError(f"duplicate seed {row['seed']} for {model}")
                    games[row["seed"]] = row
    if not games:
        raise ValueError(f"no valid games for {model}")
    players = {}
    for game in games.values():
        for player in game.get("players", []):
            if not player.get("stable_player_id"):
                continue
            key = player["stable_player_id"]
            if key not in players:
                players[key] = {"base": player, "values": {name: [] for name in METRICS}}
            elif (players[key]["base"].get("name"), players[key]["base"].get("team")) != (player.get("name"), player.get("team")):
                raise ValueError(f"identity mismatch for {key}")
            for metric, (group, field) in METRICS.items():
                value = (player.get(group) or {}).get(field)
                if value is not None:
                    players[key]["values"][metric].append(value)
    # Combined markets must be formed per simulated game to preserve covariance.
    for player in players.values():
        vals = player["values"]
        if len(vals["pass_yards"]) == len(vals["rush_yards"]):
            vals["passing_rushing_yards"] = [a + b for a, b in zip(vals["pass_yards"], vals["rush_yards"])]
        if len(vals["rush_yards"]) == len(vals["receiving_yards"]):
            vals["rushing_receiving_yards"] = [a + b for a, b in zip(vals["rush_yards"], vals["receiving_yards"])]
        if len(vals["rush_tds"]) == len(vals["receiving_tds"]):
            vals["total_touchdowns"] = [a + b for a, b in zip(vals["rush_tds"], vals["receiving_tds"])]
    for player in players.values():
        base = player["base"]
        for metric, values in player["values"].items():
            if not values:
                continue
            counts = {}
            for value in values:
                key = str(value)
                counts[key] = counts.get(key, 0) + 1
            rows.append({
                "model": model, "team": base.get("team"), "name": base.get("name"),
                "position": base.get("position"), "stable_player_id": base.get("stable_player_id"),
                "starter": base.get("starter"), "metric": metric, "n": len(values),
                "mean": statistics.mean(values), "median": statistics.median(values),
                "p10": quantile(values, .1), "p90": quantile(values, .9),
                "probability_gt_zero": sum(x > 0 for x in values) / len(values),
                "histogram_json": json.dumps(counts, sort_keys=True, separators=(",", ":")),
            })
ARGS.out.parent.mkdir(parents=True, exist_ok=True)
with ARGS.out.open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
print(json.dumps({"models": MODELS, "rows": len(rows), "players_per_model": {m: len({r['stable_player_id'] for r in rows if r['model'] == m}) for m in MODELS}, "output": str(ARGS.out)}))
