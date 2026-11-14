#!/usr/bin/env python3
"""Reconstruct walk-forward 2026 NFL prop forecasts and score them on completed games.

Forecasts use only player-game history before each target week and omit target-game
injury/availability status. Official finalized rosters are joined after forecasting
to validate the realized player population; their status is never an engine input.
The database is opened read-only and no model rows are written.
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import grade_nfl_prop_probabilities as grader
import nfl_player_projection_v2 as engine
import nfl_prop_calibration as calibration

SEASON = 2026
WEEKS = tuple(range(2, 10))
MIN_CALIBRATION_ITEMS = 200
MARKET_STAT = {
    **{market: ("rec", idx, attr) for market, (idx, attr) in grader.RECEIVING.items()},
    **{market: ("qb", idx, attr) for market, (idx, attr) in grader.PASSING.items()},
}
ROSTER_FIELDS = (
    "game_id", "week", "team", "gsis_id", "player_name", "jersey_number",
    "gamebook_position", "actual_gameday_status", "gamebook_roster_role",
    "weekly_source_status", "identity_match_method", "gamebook_url", "gamebook_sha256",
)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path, rows):
    if not rows:
        raise ValueError("refusing to write an empty result: " + str(path))
    with Path(path).open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def mean_or_none(values):
    values = list(values)
    return statistics.mean(values) if values else None


def read_rosters(path):
    out = {}
    with Path(path).open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            key = (row["game_id"], row["team"], row["gsis_id"])
            if key in out:
                raise ValueError("duplicate finalized roster key: " + repr(key))
            row["week"] = int(row["week"])
            row["jersey_number"] = int(row["jersey_number"])
            out[key] = row
    return out


def forward_maps(graded):
    maps = {}
    for week in WEEKS:
        training = [row for row in graded if int(row["game_id"].split("_")[1]) < week]
        if len(training) < MIN_CALIBRATION_ITEMS:
            continue
        a, b = calibration.fit_platt([(row["p_ours"], row["over"]) for row in training])
        maps[week] = {
            "a": a, "b": b, "n_items": len(training),
            "n_player_games": len({(r["game_id"], r["player_id"]) for r in training}),
            "trained_weeks": sorted({int(r["game_id"].split("_")[1]) for r in training}),
        }
    return maps


def target_settlement_disagreements(con, hist):
    """Count target-week disagreements with recorded book settlement without rerunning draws."""
    items, _skipped = grader.collect(con, SEASON)
    final_weeks = {week for (week,) in con.execute(
        "SELECT DISTINCT week FROM nfl_schedule WHERE season=? AND game_type='REG' "
        "AND home_score IS NOT NULL", (SEASON,))}
    counts = Counter()
    eligible = 0
    for gid, pid, market, _book, line, _market_p, book_hit in items:
        week = int(gid.split("_")[1])
        if week not in WEEKS or week not in final_weeks:
            continue
        row = next((r for r in hist.by_player.get((SEASON, pid), ()) if r.game_id == gid), None)
        if row is None:
            continue
        if market in grader.RECEIVING:
            if row.pos not in ("RB", "WR", "TE"):
                continue
            attr = grader.RECEIVING[market][1]
            projected = engine.project(hist, SEASON, week, pid, row.pos, row.team, row.opp, gid)
            if projected is None or projected.get("tgt", 0) <= 0:
                continue
        else:
            if row.pos != "QB" or grader.pregame_leader(hist, SEASON, row.team, week) != pid:
                continue
            attr = grader.PASSING[market][1]
            projected = engine.project_qb(hist, SEASON, week, pid, row.team, row.opp, gid)
            if projected is None or projected.get("att", 0) <= 0:
                continue
        eligible += 1
        if book_hit is not None and int(book_hit) != int(getattr(row, attr) > line):
            counts[week] += 1
    return eligible, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=Path("/root/legendarypicks/backend/data/picks.dev.db"))
    parser.add_argument("--rosters", type=Path, default=HERE / "finalized-game-day-rosters.csv")
    parser.add_argument("--out-dir", type=Path, default=HERE)
    args = parser.parse_args()
    db_path = args.db.resolve()
    before = db_path.stat()
    uri = "file:{}?mode=ro".format(db_path)
    con = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        con.execute("BEGIN")
        raw_history = engine.History.load(con, [SEASON - 1, SEASON])
        # Do not let postgame report or availability fields alter any target forecast.
        hist = engine.History(raw_history.rows, {})
        graded_all, skipped, _all_weeks_settlement_disagreements = grader.grade(
            con, SEASON, hist=hist, population="pregame", marcel=True
        )
        graded = [row for row in graded_all
                  if int(row["game_id"].split("_")[1]) in WEEKS]
        if not graded:
            raise ValueError("no eligible completed prop rows in Weeks 2-9")
        settlement_eligible, settlement_by_week = target_settlement_disagreements(con, hist)
        if settlement_eligible != len(graded):
            raise ValueError("independent target settlement audit does not match grader population: "
                             + str(settlement_eligible) + " != " + str(len(graded)))

        roster_by_key = read_rosters(args.rosters)
        players = {int(pid): (gsis, name, team) for pid, gsis, name, team in con.execute(
            "SELECT id,nfl_gsis_id,name,team FROM players WHERE league='nfl' AND nfl_gsis_id IS NOT NULL"
        )}
        if len({v[0] for v in players.values()}) != len(players):
            raise ValueError("duplicate NFL GSIS IDs in the player identity table")

        # Only use gamebook status after projection, to audit realized roster membership.
        for row in graded:
            info = players.get(int(row["player_id"]))
            if info is None:
                raise ValueError("graded player missing GSIS identity: " + repr(row))
            gsis, _name, _team = info
            hist_row = next((r for r in hist.by_player[(SEASON, int(row["player_id"]))]
                             if r.game_id == row["game_id"]), None)
            if hist_row is None:
                raise ValueError("graded player has no target game log: " + repr(row))
            roster = roster_by_key.get((row["game_id"], hist_row.team, str(gsis)))
            if roster is None:
                raise ValueError("graded player absent from finalized gamebook roster: "
                                 + repr((row["game_id"], hist_row.team, gsis)))
            if roster["actual_gameday_status"] != "ACTIVE" or roster["gamebook_roster_role"] == "did_not_play":
                raise ValueError("graded player conflicts with official gamebook status: "
                                 + repr((row["game_id"], hist_row.team, gsis, roster)))
            row["stable_player_id"] = str(gsis)
            row["team"] = hist_row.team
            row["player_name"] = roster["player_name"]
            row["gamebook_roster_role"] = roster["gamebook_roster_role"]
            row["gamebook_url"] = roster["gamebook_url"]

        maps = forward_maps(graded)
        projector = grader.Projector(hist)
        prop_rows = []
        player_market_rows = {}
        for row in graded:
            week = int(row["game_id"].split("_")[1])
            kind, index, _attr = MARKET_STAT[row["market"]]
            draws = projector.draws(SEASON, next(
                r for r in hist.by_player[(SEASON, int(row["player_id"]))]
                if r.game_id == row["game_id"]), kind)
            if not draws:
                raise ValueError("projection draws missing after grader accepted the row: " + repr(row))
            values = sorted(draw[index] for draw in draws)
            mapping = maps.get(week)
            p_platt = calibration.apply_map(mapping["a"], mapping["b"], row["p_ours"]) if mapping else None
            prop_rows.append({
                "week": week, "game_id": row["game_id"], "team": row["team"],
                "stable_player_id": row["stable_player_id"], "player_name": row["player_name"],
                "gamebook_roster_role": row["gamebook_roster_role"],
                "market": row["market"], "book": row["book"], "line": row["line"],
                "captured_two_sided_market_p_over": row["p_market"],
                "spec_b_v2_p_over": row["p_ours"], "forward_platt_p_over": p_platt,
                "forward_platt_status": "mapped" if mapping else "raw_no_map",
                "platt_a": mapping["a"] if mapping else None,
                "platt_b": mapping["b"] if mapping else None,
                "platt_training_items": mapping["n_items"] if mapping else 0,
                "projection_mean": row["proj"], "marcel_lite_mean": row["proj_marcel"],
                "projection_median": grader.quantile(values, 0.5),
                "projection_p10": grader.quantile(values, 0.1),
                "projection_p90": grader.quantile(values, 0.9),
                "actual": row["actual"], "over_hit": row["over"],
                "spec_b_v2_brier": (row["p_ours"] - row["over"]) ** 2,
                "forward_platt_brier": ((p_platt - row["over"]) ** 2) if p_platt is not None else None,
                "market_brier": ((row["p_market"] - row["over"]) ** 2)
                                if row["p_market"] is not None else None,
                "gamebook_url": row["gamebook_url"],
                "forecast_condition": "conditional on player having a target game stat-log row",
            })
            key = (week, row["game_id"], row["player_id"], row["market"])
            player_market_rows.setdefault(key, prop_rows[-1])

        # Aggregate at the player-game-market level so multiple books/alternate lines
        # do not multiply point-estimate MAE observations.
        point_rows = []
        for key, row in sorted(player_market_rows.items()):
            point_rows.append({
                "week": row["week"], "game_id": row["game_id"], "team": row["team"],
                "stable_player_id": row["stable_player_id"], "player_name": row["player_name"],
                "gamebook_roster_role": row["gamebook_roster_role"], "market": row["market"],
                "projection_mean": row["projection_mean"], "marcel_lite_mean": row["marcel_lite_mean"],
                "projection_median": row["projection_median"], "projection_p10": row["projection_p10"],
                "projection_p90": row["projection_p90"], "actual": row["actual"],
                "absolute_error_spec_b_v2": abs(row["projection_mean"] - row["actual"])
                    if row["projection_mean"] is not None else None,
                "absolute_error_marcel_lite": abs(row["marcel_lite_mean"] - row["actual"])
                    if row["marcel_lite_mean"] is not None else None,
                "gamebook_url": row["gamebook_url"],
            })

        metrics = []
        by_week = defaultdict(list)
        for row in prop_rows:
            by_week[row["week"]].append(row)
        for week in WEEKS:
            rows = by_week[week]
            if not rows:
                metrics.append({"week": week, "prop_line_rows": 0, "status": "no_eligible_props"})
                continue
            market_rows = [r for r in rows if r["market_brier"] is not None]
            platt_rows = [r for r in rows if r["forward_platt_brier"] is not None]
            point = [r for r in point_rows if r["week"] == week]
            metrics.append({
                "week": week, "status": "ok", "prop_line_rows": len(rows),
                "player_game_market_count": len({(r["game_id"], r["stable_player_id"], r["market"]) for r in rows}),
                "game_count": len({r["game_id"] for r in rows}),
                "spec_b_v2_brier": statistics.mean(r["spec_b_v2_brier"] for r in rows),
                "forward_platt_brier": statistics.mean(r["forward_platt_brier"] for r in platt_rows)
                    if platt_rows else None,
                "forward_platt_scored_rows": len(platt_rows),
                "market_brier": statistics.mean(r["market_brier"] for r in market_rows)
                    if market_rows else None,
                "market_scored_rows": len(market_rows),
                "constant_50pct_brier": statistics.mean((0.5 - r["over_hit"]) ** 2 for r in rows),
                "spec_b_v2_point_mae": mean_or_none(r["absolute_error_spec_b_v2"] for r in point
                    if r["absolute_error_spec_b_v2"] is not None),
                "marcel_lite_point_mae": mean_or_none(r["absolute_error_marcel_lite"] for r in point
                    if r["absolute_error_marcel_lite"] is not None),
                "point_player_game_market_count": len(point),
                "calibration_training_items": maps.get(week, {}).get("n_items", 0),
                "calibration_training_player_games": maps.get(week, {}).get("n_player_games", 0),
                "recorded_book_settlement_disagreements": settlement_by_week.get(week, 0),
            })

        roster_scope = [r for r in roster_by_key.values() if r["week"] in WEEKS]
        active_skill_roster_rows = sum(
            r["actual_gameday_status"] == "ACTIVE" and r["gamebook_position"] in
            {"QB", "RB", "FB", "WR", "TE"} for r in roster_scope)
        db_stat = db_path.stat()
        if db_stat.st_size != before.st_size or db_stat.st_mtime_ns != before.st_mtime_ns:
            raise RuntimeError("development database changed during the read-only backtest")
        summary = {
            "season": SEASON, "weeks": list(WEEKS),
            "model": "Spec B v2 with Marcel-lite point-estimate benchmark",
            "forecast_design": "walk-forward; each target week uses only earlier player-game rows; target-game availability status is omitted",
            "realized_roster_source": "official NFL GSIS gamebooks, joined after forecasts by game/team/GSIS ID",
            "realized_roster_rows": len(roster_scope),
            "realized_active_skill_roster_rows": active_skill_roster_rows,
            "graded_prop_line_rows": len(prop_rows),
            "player_game_market_projection_rows": len(point_rows),
            "unique_games_with_graded_props": len({r["game_id"] for r in prop_rows}),
            "unique_player_ids_with_graded_props": len({r["stable_player_id"] for r in prop_rows}),
            "settlement_disagreements_with_recorded_book_result": sum(settlement_by_week.values()),
            "settlement_disagreements_scope": "eligible graded prop rows in Weeks 2-9 only",
            "grade_exclusions_all_final_2026_weeks": skipped,
            "weekly_metrics": metrics,
            "forward_platt_maps": maps,
            "market_definition": "latest two-sided captured sportsbook over/under per game/player/market/book/line, before scheduled kickoff; whole-number lines excluded by the existing grader",
            "outcome_population": "players with a target-week player_game_logs row, verified ACTIVE in the official gamebook; projections are conditional on recorded player-game participation",
            "limitations": [
                "The official finalized roster is postgame ground truth and is used only to validate the scored roster population, never as a predictor input.",
                "Historic pregame injury/availability snapshots are not established for these weeks; projection availability redistribution is disabled by giving the model an empty target-status map.",
                "A finalized active roster is not the same as actual snap participation. This score is conditional on a player-game stat-log row; no-row/DNP props are not treated as zero or as settled.",
                "The model's frozen Spec B v2 probability distributions cover receiving props and quarterback passing props only; other market families are not filled with fabricated probabilities.",
                "Alternate lines and multiple books on one player-game are correlated. These per-line scores are descriptive, not independent-sample confidence intervals or evidence of profitability.",
                "Weeks 2-9 are 2026 retrospective evaluation weeks; these reconstructed projections were not captured before kickoff."
            ],
            "inputs": {
                "database_path": str(db_path), "database_size_bytes": db_stat.st_size,
                "database_mtime_ns": db_stat.st_mtime_ns,
                "database_read_mode": "SQLite mode=ro, one consistent read transaction; no model-table writes",
                "finalized_rosters_csv": str(args.rosters.resolve()),
                "finalized_rosters_sha256": sha256(args.rosters),
                "runner_sha256": sha256(Path(__file__)),
                "spec_b_engine_sha256": sha256(BACKEND / "nfl_player_projection_v2.py"),
                "prop_grader_sha256": sha256(BACKEND / "grade_nfl_prop_probabilities.py"),
                "calibration_source_sha256": sha256(BACKEND / "nfl_prop_calibration.py"),
                "projection_code_parameters": engine.DEFAULTS,
                "projection_distribution_parameters": engine.DIST,
                "quarterback_distribution_parameters": engine.QB_DEFAULTS,
                "draws_per_player_game": grader.N_SIMS,
                "minimum_forward_calibration_items": MIN_CALIBRATION_ITEMS,
            },
            "outputs": ["walk-forward-prop-projections.csv", "player-game-market-projections.csv",
                        "weekly-prop-projection-metrics.csv", "prop-projection-backtest-summary.json"],
        }
        args.out_dir.mkdir(parents=True, exist_ok=True)
        write_csv(args.out_dir / "walk-forward-prop-projections.csv", prop_rows)
        write_csv(args.out_dir / "player-game-market-projections.csv", point_rows)
        write_csv(args.out_dir / "weekly-prop-projection-metrics.csv", metrics)
        (args.out_dir / "prop-projection-backtest-summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"prop_line_rows": len(prop_rows), "player_game_market_rows": len(point_rows),
                          "weekly_metrics": metrics,
                          "settlement_disagreements": sum(settlement_by_week.values())},
                         indent=2, sort_keys=True))
    finally:
        try:
            con.rollback()
        finally:
            con.close()


if __name__ == "__main__":
    main()
