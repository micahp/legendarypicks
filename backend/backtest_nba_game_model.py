#!/usr/bin/env python3
"""Reproduce the NBA Phase 1 chronological benchmark from pinned free releases."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nba_game_model import backtest
from nba_model_data import load_release_data

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = Path(__file__).resolve().parent / "data" / "nba-model-source"
DEFAULT_OUTPUT = ROOT / "research" / "nba-game-model" / "benchmark.json"


def run(data_dir: str | Path, output_path: str | Path, download: bool = False) -> dict:
    release = load_release_data(data_dir, download=download)
    report = backtest(release.games, release.coverage)
    report["source_asset_hashes"] = release.asset_hashes
    report["sources"] = {
        "team_boxes": "SportsDataverse espn_nba_team_boxscores; one ESPN-ID team row per side",
        "game_phases": "SportsDataverse nba_stats_schedules; season_type identifies regular season and NBA Cup final",
        "game_crosswalk": "canonical date/home/away tuple within one day, exact score pair, unique match required",
        "downloaded_bytes": sum(path.stat().st_size for path in Path(data_dir).glob("*.parquet")),
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA),
                        help="cache directory for pinned Parquet assets")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help="benchmark JSON output path")
    parser.add_argument("--download", action="store_true",
                        help="download missing pinned releases serially")
    args = parser.parse_args()
    report = run(args.data_dir, args.output, download=args.download)
    print("NBA game-model benchmark: source_sha256_verified=true")
    print("eligible regular-season games:", report["eligible_games"])
    print("coverage by SportsDataverse ending-year season:")
    for row in report["coverage"]:
        print("  {season}: schedule={regular_schedule_games} boxscore="
              "{regular_boxscore_games_crosswalked} eligible="
              "{regular_games_with_complete_efficiency_inputs} missing_schedule_box="
              "{regular_schedule_games_without_boxscore} missing_efficiency="
              "{regular_games_missing_efficiency_inputs} cup_final_excluded="
              "{nba_cup_finals_excluded}".format(**row))
    for period in ("validation", "test"):
        print(f"{period} metrics:")
        for model, metrics in report["metrics"][period].items():
            print("  {model}: n={games} Brier={winner_brier:.5f} logloss={winner_log_loss:.5f} "
                  "ECE10={ece:.5f} home_MAE={home_mae} away_MAE={away_mae} "
                  "spread_MAE={spread_mae} total_MAE={total_mae}".format(
                      model=model, games=metrics["games"],
                      winner_brier=metrics["winner_brier"],
                      winner_log_loss=metrics["winner_log_loss"],
                      ece=metrics["calibration"]["ece_10_bin"],
                      home_mae=("—" if metrics.get("home_points_mae") is None
                                else f"{metrics['home_points_mae']:.3f}"),
                      away_mae=("—" if metrics.get("away_points_mae") is None
                                else f"{metrics['away_points_mae']:.3f}"),
                      spread_mae=("—" if metrics.get("spread_mae") is None
                                  else f"{metrics['spread_mae']:.3f}"),
                      total_mae=("—" if metrics.get("total_mae") is None
                                 else f"{metrics['total_mae']:.3f}"),
                  ))
            if metrics.get("distribution"):
                d = metrics["distribution"]
                print("    G3 distribution: margin_CRPS={:.3f} total_CRPS={:.3f} "
                      "joint_NLL={:.3f} margin80_coverage={:.3f} total80_coverage={:.3f}".format(
                          d["margin_crps"], d["total_crps"], d["joint_score_gaussian_nll"],
                          d["margin_80pct_coverage"], d["total_80pct_coverage"],
                      ))
    uncertainty = report["uncertainty"]
    print("paired date-cluster bootstrap: {replicates} replicates, seed {seed}; "
          "95% percentile intervals".format(**uncertainty))
    for period in ("validation", "test"):
        period_result = uncertainty[period]
        print(f"{period} paired comparisons: {period_result['date_clusters']} NBA local game dates")
        for comparison in period_result["comparisons"]:
            low, high = comparison["ci95_percentile"]
            print("  {metric}: {candidate} - {comparator} delta={delta:+.6f} "
                  "CI95=[{low:+.6f}, {high:+.6f}] P(better)={p_better:.3f}".format(
                      metric=comparison["metric"],
                      candidate=comparison["candidate"],
                      comparator=comparison["comparator"],
                      delta=comparison["delta_candidate_minus_comparator"],
                      low=low, high=high,
                      p_better=comparison["p_candidate_better"],
                  ))
    print("report:", Path(args.output).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
