#!/usr/bin/env python3
"""Aggregate saved V1.7 completed outcomes; never runs a simulation."""
import argparse
import csv
import gzip
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARSER = argparse.ArgumentParser()
PARSER.add_argument("--completed", type=Path, default=HERE / "v1.7-1000-pr43-completed-seeds.jsonl.gz")
PARSER.add_argument("--errors", type=Path, default=HERE / "v1.7-1000-pr43-errors.jsonl.gz")
PARSER.add_argument("--directory", type=Path, default=HERE)
ARGS = PARSER.parse_args()

def read_jsonl_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]

def quantile(values, p):
    xs = sorted(values)
    pos = (len(xs) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)

records = read_jsonl_gz(ARGS.completed)
manifest = records[0]
games = records[1:]
seeds = [r["seed"] for r in games]
assert manifest["requested_seeds"] == 1000
assert len(games) == 953, f"expected 953 mechanically completed games, got {len(games)}"
assert len(set(seeds)) == 953, "completed seed IDs must be distinct"
assert all(r["outcome"].get("mechanically_complete_game") is True for r in games)
# Keep the runner's gate metadata intact; it is not the inclusion criterion here.
gate_statuses = Counter(str(r["outcome"].get("valid_full_game")) for r in games)

failure_records = read_jsonl_gz(ARGS.errors)
failure_manifest, failure_rows = failure_records[0], failure_records[1:]
failed_seeds = [r["seed"] for r in failure_rows]
assert len(failed_seeds) == 47 and len(set(failed_seeds)) == 47
assert set(seeds).isdisjoint(failed_seeds)
assert failure_manifest["failure_record_count"] == 47

METRICS = {
    "pass_yards": ("passing", "yds"), "pass_attempts": ("passing", "att"),
    "pass_completions": ("passing", "comp"), "pass_tds": ("passing", "td"),
    "interceptions": ("passing", "int"), "rush_yards": ("rushing", "yds"),
    "carries": ("rushing", "att"), "rush_tds": ("rushing", "td"),
    "receiving_yards": ("receiving", "yds"), "receptions": ("receiving", "rec"),
    "targets": ("receiving", "tgt"), "receiving_tds": ("receiving", "td"),
    "fumbles_lost": ("miscellaneous", "fumbles_lost"),
}
players = {}
score = {"WAS": [], "NYG": []}
wins = Counter()
team_sums = {t: Counter() for t in ("WAS", "NYG")}
drive_ends = {t: Counter() for t in ("WAS", "NYG")}
team_stat_keys = (
    "drives", "plays", "sacks_taken", "turnovers", "interceptions", "fumbles_lost",
    "punts", "touchdowns", "field_goal_attempts", "field_goals_made", "turnovers_on_downs",
    "rush_attempts", "rushing_yards", "pass_attempts", "passing_yards", "completions",
    "third_down_attempts", "third_down_conversions", "fourth_down_attempts", "fourth_down_conversions",
)

for record in games:
    outcome = record["outcome"]
    box = outcome["boxscore"]
    by_team = {x["team"]: x["stats"] for x in box["teams"]}
    for team in ("WAS", "NYG"):
        stat = by_team[team]
        score[team].append(stat["points"])
        for key in team_stat_keys:
            if stat.get(key) is not None:
                team_sums[team][key] += stat[key]
    wp, hp = by_team["WAS"]["points"], by_team["NYG"]["points"]
    wins["WAS" if wp > hp else "NYG" if hp > wp else "tie"] += 1
    for drive in (box.get("quarter_by_quarter") or {}).get("drive_summaries", []):
        team = drive.get("offense_team")
        if team in drive_ends:
            drive_ends[team][str(drive.get("terminal"))] += 1
    for p in box.get("players", []):
        pid = p.get("stable_player_id")
        if not pid:
            continue
        if pid not in players:
            players[pid] = {"base": p, "values": {m: [] for m in METRICS}}
        row = players[pid]
        if (row["base"].get("name"), row["base"].get("team")) != (p.get("name"), p.get("team")):
            raise ValueError(f"identity mismatch for {pid}")
        for metric, (group, field) in METRICS.items():
            value = (p.get(group) or {}).get(field)
            if value is not None:
                row["values"][metric].append(value)

n = len(games)
assert wins.total() == n
was, nyg = score["WAS"], score["NYG"]
totals = [a + h for a, h in zip(was, nyg)]
margins = [h - a for a, h in zip(was, nyg)]
p_nyg = wins["NYG"] / n
batch_diagnostics = []
for batch_name in sorted({r["batch"] for r in games}):
    batch_rows = [r["outcome"] for r in games if r["batch"] == batch_name]
    batch_was = [x["away_points"] for x in batch_rows]
    batch_nyg = [x["home_points"] for x in batch_rows]
    batch_was_wins = sum(a > h for a, h in zip(batch_was, batch_nyg))
    batch_nyg_wins = sum(h > a for a, h in zip(batch_was, batch_nyg))
    batch_diagnostics.append({
        "batch": batch_name, "n": len(batch_rows),
        "WAS_win_pct": 100 * batch_was_wins / len(batch_rows),
        "NYG_win_pct": 100 * batch_nyg_wins / len(batch_rows),
        "tie_pct": 100 * (len(batch_rows) - batch_was_wins - batch_nyg_wins) / len(batch_rows),
        "WAS_mean_points": statistics.mean(batch_was), "NYG_mean_points": statistics.mean(batch_nyg),
        "mean_total": statistics.mean(a + h for a, h in zip(batch_was, batch_nyg)),
    })
game_summary = {
    "game_id": manifest["game_id"], "analysis_sample": "mechanically_complete_saved_outcomes",
    "requested_seeds": 1000, "mechanically_completed_seeds": n,
    "distinct_excluded_error_or_blocker_seeds": len(failed_seeds),
    "original_valid_full_game_flags": dict(gate_statuses),
    "full_game_validity_gate_used_for_selection": False,
    "original_status_counts": dict(Counter(r["outcome"].get("status") for r in games)),
    "score_wins": dict(wins),
    "win_frequencies": {"WAS": wins["WAS"] / n, "NYG": p_nyg, "tie": wins["tie"] / n},
    "home_win_brier_against_actual_WAS_24_NYG_21": p_nyg ** 2,
    "team_scores": {
        t: {"mean": statistics.mean(vals), "median": statistics.median(vals),
            "p10": quantile(vals, .1), "p90": quantile(vals, .9)}
        for t, vals in (("WAS", was), ("NYG", nyg))
    },
    "total_points": {"mean": statistics.mean(totals), "median": statistics.median(totals),
                     "p10": quantile(totals, .1), "p90": quantile(totals, .9)},
    "NYG_minus_WAS_margin": {"mean": statistics.mean(margins), "median": statistics.median(margins),
                              "p10": quantile(margins, .1), "p90": quantile(margins, .9)},
    "actual": {"WAS": 24, "NYG": 21, "total": 45, "NYG_minus_WAS_margin": -3},
    "mean_score_absolute_errors": {"WAS": abs(statistics.mean(was) - 24),
                                   "NYG": abs(statistics.mean(nyg) - 21),
                                   "total": abs(statistics.mean(totals) - 45)},
    "batch_diagnostics": batch_diagnostics,
    "team_boxscore_averages": {},
    "provenance": {"completed_seed_artifact": ARGS.completed.name,
                   "completed_artifact_sha256": __import__("hashlib").sha256(ARGS.completed.read_bytes()).hexdigest(),
                   "errors_artifact": ARGS.errors.name,
                   "errors_artifact_sha256": __import__("hashlib").sha256(ARGS.errors.read_bytes()).hexdigest(),
                   "source_run_manifest": manifest},
}
for team in ("WAS", "NYG"):
    sums = team_sums[team]
    game_summary["team_boxscore_averages"][team] = {
        "per_game": {k: v / n for k, v in sums.items()},
        "completion_pct": 100 * sums["completions"] / sums["pass_attempts"] if sums["pass_attempts"] else None,
        "yards_per_rush": sums["rushing_yards"] / sums["rush_attempts"] if sums["rush_attempts"] else None,
        "yards_per_pass_attempt": sums["passing_yards"] / sums["pass_attempts"] if sums["pass_attempts"] else None,
        "drive_ends_per_game": {k: v / n for k, v in drive_ends[team].items()},
    }
ARGS.directory.joinpath("v1.7-game-summary.json").write_text(json.dumps(game_summary, indent=2, sort_keys=True) + "\n")

# Per-player distribution export follows player-projections.py exactly:
# empirical mean/median, linearly interpolated P10/P90, P(>0), and histogram.
distribution_rows = []
for player in players.values():
    vals = player["values"]
    if len(vals["pass_yards"]) == len(vals["rush_yards"]):
        vals["passing_rushing_yards"] = [a + b for a, b in zip(vals["pass_yards"], vals["rush_yards"])]
    if len(vals["rush_yards"]) == len(vals["receiving_yards"]):
        vals["rushing_receiving_yards"] = [a + b for a, b in zip(vals["rush_yards"], vals["receiving_yards"])]
    if len(vals["rush_tds"]) == len(vals["receiving_tds"]):
        vals["total_touchdowns"] = [a + b for a, b in zip(vals["rush_tds"], vals["receiving_tds"])]
    base = player["base"]
    for metric, values in vals.items():
        if not values:
            continue
        hist = Counter(str(x) for x in values)
        distribution_rows.append({
            "model": "v1.7", "team": base.get("team"), "name": base.get("name"),
            "position": base.get("position"), "stable_player_id": base.get("stable_player_id"),
            "starter": base.get("starter"), "metric": metric, "n": len(values),
            "mean": statistics.mean(values), "median": statistics.median(values),
            "p10": quantile(values, .1), "p90": quantile(values, .9),
            "probability_gt_zero": sum(x > 0 for x in values) / len(values),
            "histogram_json": json.dumps(dict(sorted(hist.items(), key=lambda item: float(item[0]))), separators=(",", ":")),
        })
proj_path = ARGS.directory / "player-projections.csv"
with proj_path.open(newline="", encoding="utf-8") as stream:
    old_rows = [r for r in csv.DictReader(stream) if r["model"] != "v1.7"]
fields = list(old_rows[0])
with proj_path.open("w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\r\n"); writer.writeheader(); writer.writerows(old_rows + distribution_rows)

market_metric = {
    "passing_yards": "pass_yards", "pass_attempts": "pass_attempts", "pass_completions": "pass_completions",
    "passing_touchdowns": "pass_tds", "interceptions_thrown": "interceptions", "rushing_yards": "rush_yards",
    "rush_attempts": "carries", "receiving_yards": "receiving_yards", "receptions": "receptions",
    "targets": "targets", "rushing_receiving_yards": "rushing_receiving_yards",
    "passing_rushing_yards": "passing_rushing_yards", "total_touchdowns": "total_touchdowns",
}
histograms = {(r["stable_player_id"], r["metric"]): json.loads(r["histogram_json"]) for r in distribution_rows}
graded_path = ARGS.directory / "graded-player-props.csv"
with graded_path.open(newline="", encoding="utf-8") as stream:
    graded = list(csv.DictReader(stream))
assert len(graded) == 323, f"expected same 323 prop cohort, got {len(graded)}"
prob_by_line = {}
for r in graded:
    metric = market_metric.get(r["market"])
    hist = histograms.get((r["stable_player_id"], metric)) if metric else None
    p_over = None
    if hist:
        denom = sum(int(v) for v in hist.values())
        p_over = sum(int(v) for x, v in hist.items() if float(x) > float(r["line"])) / denom
    r["v1.7_p_over"] = "" if p_over is None else p_over
    r["v1.7_brier"] = "" if p_over is None else (p_over - int(r["over_hit"])) ** 2
    prob_by_line[(r["stable_player_id"], r["market"], float(r["line"]))] = p_over
fields = list(graded[0])
with graded_path.open("w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\r\n"); writer.writeheader(); writer.writerows(graded)

quote_path = ARGS.directory / "pregame-prop-quotes.csv"
with quote_path.open(newline="", encoding="utf-8") as stream:
    quotes = list(csv.DictReader(stream))
for r in quotes:
    p = prob_by_line.get((r["stable_player_id"], r["market"], float(r["line"])))
    r["v1.7_p_over"] = "" if p is None else p
with quote_path.open("w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(quotes[0]), lineterminator="\r\n"); writer.writeheader(); writer.writerows(quotes)

covered = [r for r in graded if r["v1.7_brier"] != ""]
common_rows = []
recon_path = ARGS.directory / "reconstructed-player-prop-probabilities.csv"
with recon_path.open(newline="", encoding="utf-8") as stream:
    specb_keys = {(r["stable_player_id"], r["market"], float(r["line"])) for r in csv.DictReader(stream) if r["spec_b_v2_p_over"]}
common_rows = [r for r in covered if (r["stable_player_id"], r["market"], float(r["line"])) in specb_keys]
def mean_brier(rows, key):
    return statistics.mean(float(r[key]) for r in rows) if rows else None

summary_path = ARGS.directory / "graded-player-props-summary.json"
prop_summary = json.loads(summary_path.read_text())
prop_summary.setdefault("brier_all_matched_lines", {})["v1.7"] = mean_brier(covered, "v1.7_brier")
prop_summary.setdefault("brier_same_lines_with_two_sided_market_odds", {})["v1.7"] = mean_brier(covered, "v1.7_brier")
specb_forecasts = {}
for row in csv.DictReader(recon_path.open(newline="", encoding="utf-8")):
    key = (row["stable_player_id"], row["market"], float(row["line"]))
    specb_forecasts[key] = row
common_briers = {
    model: mean_brier(common_rows, f"{model}_brier")
    for model in ("v1", "v1.5", "v1.6", "v1.7", "v2")
}
common_briers["devigged_market"] = statistics.mean(float(r["market_brier"]) for r in common_rows)
for model, column in (("spec_b_v2", "spec_b_v2_brier"), ("forward_platt", "forward_platt_brier")):
    vals = []
    for row in common_rows:
        source = specb_forecasts[(row["stable_player_id"], row["market"], float(row["line"]))]
        vals.append(float(source[column]))
    common_briers[model] = statistics.mean(vals)
prop_summary["brier_same_lines_with_spec_b_coverage"] = common_briers
prop_summary["v1.7_coverage"] = {"matched_lines": len(covered), "cohort_lines": len(graded), "spec_b_common_lines": len(common_rows)}
for market in sorted({r["market"] for r in covered}):
    market_rows = [r for r in covered if r["market"] == market]
    prop_summary["brier_by_market_same_market_lines"].setdefault(market, {})["v1.7"] = mean_brier(market_rows, "v1.7_brier")
summary_path.write_text(json.dumps(prop_summary, indent=2, sort_keys=True) + "\n")

comparison_path = ARGS.directory / "player-model-comparison.csv"
with comparison_path.open(newline="", encoding="utf-8") as stream:
    comparisons = [r for r in csv.DictReader(stream) if r["model"] != "v1.7"]
comparisons.append({"comparison_type": "prop_probability_brier", "model": "v1.7", "stat": "",
                    "probability_items": len(covered), "probability_coverage_pct": round(100 * len(covered) / len(graded), 2),
                    "brier_on_covered_items": mean_brier(covered, "v1.7_brier"),
                    "common_spec_b_coverage_items": len(common_rows),
                    "brier_on_common_coverage": mean_brier(common_rows, "v1.7_brier"),
                    "point_forecast_count": 0, "point_mae": "",
                    "provenance": "mechanically completed saved V1.7 batch outcomes; reconstructed postgame"})
with comparison_path.open("w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(comparisons[0]), lineterminator="\r\n"); writer.writeheader(); writer.writerows(comparisons)

print(json.dumps({"mechanically_completed": n, "distinct_excluded": len(failed_seeds),
                  "player_rows_added": len(distribution_rows), "unique_players": len(players),
                  "prop_lines_covered": len(covered), "prop_cohort": len(graded),
                  "prop_brier": mean_brier(covered, "v1.7_brier"),
                  "spec_b_common_coverage": len(common_rows),
                  "spec_b_common_brier": mean_brier(common_rows, "v1.7_brier"),
                  "game_summary": str(ARGS.directory / "v1.7-game-summary.json")}, indent=2))
