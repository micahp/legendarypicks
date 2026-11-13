#!/usr/bin/env python3
"""Reconstruct Marcel-lite, Spec B v2 and forward Platt for WAS–NYG Week 10.

The replay reads pre-kickoff quotes, the frozen roster/injury snapshot, and NFL player
logs through Week 9. It never uses Week 10 player outcomes to form a forecast.
"""
import argparse
import atexit
import csv
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import statistics
import sys
import tempfile
import zlib
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import grade_nfl_prop_probabilities as grade_engine
import nfl_player_projection_v2 as eng
import nfl_prop_calibration as calibration
import player_splits

GAME_ID = "2026_10_WAS_NYG"
SEASON, WEEK, CUTOFF = 2026, 10, "2026-11-13T01:15:00+00:00"
N_SIMS = grade_engine.N_SIMS
TEAM_MAP = {"WAS": "WSH", "WSH": "WSH", "NYG": "NYG"}
ATTR_TO_STAT = {
    "pass_yds": "pass_yards", "att": "pass_attempts", "cmp": "pass_completions",
    "pass_td": "pass_tds", "rec_yds": "receiving_yards", "rec": "receptions",
    "tgt": "targets", "rush_yds": "rush_yards", "car": "carries",
    "rush_td": "rushing_touchdowns", "rec_td": "receiving_touchdowns",
}
STAT_TO_ATTR = {value: key for key, value in ATTR_TO_STAT.items()}
MARKET_STATS = {
    "passing_yards": "pass_yards", "pass_attempts": "pass_attempts",
    "pass_completions": "pass_completions", "passing_touchdowns": "pass_tds",
    "receiving_yards": "receiving_yards", "receptions": "receptions", "targets": "targets",
    "rushing_yards": "rush_yards", "rush_attempts": "carries",
}
COMBINED = {
    "rushing_receiving_yards": ("rush_yards", "receiving_yards"),
    "passing_rushing_yards": ("pass_yards", "rush_yards"),
    "total_touchdowns": ("rushing_touchdowns", "receiving_touchdowns"),
}
DRAW_INDEX = {
    "passing_yards": ("qb", 1), "pass_attempts": ("qb", 3),
    "pass_completions": ("qb", 0), "passing_touchdowns": ("qb", 2),
    "receiving_yards": ("rec", 1), "receptions": ("rec", 0), "targets": ("rec", 3),
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def week_of(game_id):
    return int(str(game_id).split("_")[1])


def is_training_week(game_id, serve_week=WEEK):
    return 2 <= week_of(game_id) < serve_week


def model_seed(game_id, player_id, kind):
    return zlib.crc32(("%s|%d|%s" % (game_id, player_id, kind)).encode()) & 0xffff


def p_over(draws, index, line):
    return sum(1 for draw in draws if draw[index] > float(line)) / len(draws)


def fit_forward_platt(training, serve_week=WEEK):
    eligible = [r for r in training if is_training_week(r["game_id"], serve_week)]
    if len(eligible) < 200:
        raise RuntimeError("fewer than 200 pre-serve-week training items")
    a, b = calibration.fit_platt([(r["p_over"], r["over"]) for r in eligible])
    return a, b, len(eligible), len({(r["game_id"], r["player_id"]) for r in eligible})


def make_history(con, injury_path, roster, snapshot):
    # History.load only reads logs and statuses. Keep logs through Week 9 and replace
    # the mutable availability table with the preserved pregame injury artifact.
    loaded = eng.History.load(con, [SEASON - 1, SEASON])
    rows = [r for r in loaded.rows if r.season < SEASON or r.week < WEEK]
    hist = eng.History(rows, {})
    import duckdb
    injury_rows = duckdb.connect().execute(
        "SELECT team, gsis_id, report_status, practice_status FROM read_parquet(?) "
        "WHERE season=2026 AND week=10 AND team IN ('WAS','NYG')", [str(injury_path)]
    ).fetchall()
    by_gsis = {str(gsis): int(pid) for pid, gsis in con.execute(
        "SELECT id,nfl_gsis_id FROM players WHERE league='nfl' AND nfl_gsis_id IS NOT NULL")}
    frozen_status = defaultdict(dict)
    for team, gsis, report, practice in injury_rows:
        pid = by_gsis.get(str(gsis))
        if pid is not None and report:
            canonical_team = TEAM_MAP[team]
            frozen_status[(SEASON, GAME_ID, canonical_team)][pid] = (report, None)
    hist.status = dict(frozen_status)
    # Attach hashes as attributes for provenance and tests.
    hist.cutoff_week = WEEK
    hist.max_target_history_week = max((r.week for r in rows if r.season == SEASON), default=0)
    hist.snapshot = snapshot
    return hist


def roster_players(roster_path, con):
    data = json.loads(Path(roster_path).read_text())
    players = {}
    for side in ("away", "home"):
        for item in data["rosters"][side]["players"]:
            pos = item.get("pos_abb")
            if pos not in eng.SKILL:
                continue
            pid = item.get("player_id")
            gsis = item.get("gsis_id")
            row = con.execute(
                "SELECT id,nfl_gsis_id,name,position FROM players WHERE league='nfl' AND id=?", (pid,)
            ).fetchone()
            if not row or str(row[1]) != str(gsis):
                raise ValueError("frozen roster identity mismatch: %s / %s" % (pid, gsis))
            team = TEAM_MAP[item["team"]]
            players[pid] = {"pid": pid, "gsis": str(gsis), "name": row[2], "position": pos,
                            "team": team, "roster_team": item["team"], "starter": bool(item.get("starter"))}
    return players


def target_opponent(team):
    return "NYG" if team == "WSH" else "WSH"


def model_point_projection(hist, player):
    pid, pos, team = player["pid"], player["position"], player["team"]
    opp = target_opponent(team)
    out = {}
    if pos == "QB":
        spec = eng.project_qb(hist, SEASON, WEEK, pid, team, opp, GAME_ID)
        cols = ("att", "cmp", "pass_yds", "pass_td")
    else:
        spec = eng.project(hist, SEASON, WEEK, pid, pos, team, opp, GAME_ID)
        cols = ("tgt", "rec", "rec_yds", "rec_td", "car", "rush_yds", "rush_td")
    if spec:
        for col in cols:
            if col in spec:
                out[("spec_b_v2", ATTR_TO_STAT[col])] = float(spec[col])
    for col, stat in ATTR_TO_STAT.items():
        value = eng.marcel(hist, SEASON, WEEK, pid, col)
        if value is not None:
            out[("marcel_lite", stat)] = float(value)
    return spec, out


def distributions(spec, player):
    if not spec:
        return {}
    if player["position"] == "QB":
        if spec.get("att", 0) <= 0:
            return {}
        return {"passing": eng.simulate_qb(
            spec["att"], spec["cmp"] / spec["att"],
            spec["pass_yds"] / spec["cmp"] if spec["cmp"] > 0 else 0.0,
            spec["pass_td"] / spec["att"], n=N_SIMS,
            seed=model_seed(GAME_ID, player["pid"], "qb"))}
    if spec.get("tgt", 0) <= 0:
        return {}
    return {"receiving": eng.simulate(
        spec["tgt"], spec["rec"] / spec["tgt"],
        spec["rec_yds"] / spec["rec"] if spec["rec"] > 0 else 0.0,
        spec["rec_td"] / spec["tgt"], n=N_SIMS,
        seed=model_seed(GAME_ID, player["pid"], "rec"))}


def collect_training_items(con, hist):
    """Use only two-sided sportsbook quotes captured before each game's scheduled start."""
    all_pg = {r[0] for r in con.execute(
        "SELECT DISTINCT p.game_id FROM props p JOIN prop_games g ON g.id=p.game_id "
        "WHERE g.league='nfl' AND p.market IN (%s) AND p.source IN (%s)"
        % (",".join("?" * len(tuple(grade_engine.RECEIVING) + tuple(grade_engine.PASSING))),
           ",".join("?" * len(grade_engine.BOOKS))),
        tuple(grade_engine.RECEIVING) + tuple(grade_engine.PASSING) + grade_engine.BOOKS)}
    pg_to_nfl = player_splits.prop_game_nfl_ids(con, all_pg)
    query = """SELECT p.game_id,p.player_id,p.market,p.source,p.line,p.side,p.odds,p.captured_at,
                      g.start_time,pl.nfl_gsis_id
               FROM props p JOIN prop_games g ON g.id=p.game_id
               JOIN players pl ON pl.id=p.player_id
               WHERE g.league='nfl' AND p.market IN (%s) AND p.source IN (%s) AND p.odds IS NOT NULL""" % (
        ",".join("?" * (len(grade_engine.RECEIVING) + len(grade_engine.PASSING))),
        ",".join("?" * len(grade_engine.BOOKS)))
    params = tuple(grade_engine.RECEIVING) + tuple(grade_engine.PASSING) + grade_engine.BOOKS
    latest = {}
    missing_start = 0
    for pg, pid, market, book, line, side, odds, captured, start, gsis in con.execute(query, params):
        gid = pg_to_nfl.get(pg)
        if not gid or not gid.startswith("2026_") or not is_training_week(gid):
            continue
        if not start:
            missing_start += 1
            continue
        if str(captured) >= str(start):
            continue
        key = (gid, int(pid), market, book, float(line), side.lower())
        if key not in latest or str(captured) > latest[key][0]:
            latest[key] = (str(captured), odds, gsis, start)
    grouped = defaultdict(dict)
    for key, val in latest.items():
        gid, pid, market, book, line, side = key
        grouped[(gid, pid, market, book, line)][side] = val
    projector = grade_engine.Projector(hist)
    training = []
    excluded = defaultdict(int)
    for (gid, pid, market, book, line), sides in sorted(grouped.items()):
        if not {"over", "under"}.issubset(sides):
            excluded["one_sided"] += 1
            continue
        if line == int(line):
            excluded["push_possible_whole_line"] += 1
            continue
        week = week_of(gid)
        row = next((r for r in hist.by_player.get((SEASON, pid), []) if r.game_id == gid), None)
        if row is None:
            excluded["player_did_not_play"] += 1
            continue
        if market in grade_engine.RECEIVING:
            idx = grade_engine.RECEIVING[market][0]
            kind_name = "rec"
        elif market in grade_engine.PASSING:
            if row.pos != "QB" or grade_engine.pregame_leader(hist, SEASON, row.team, week) != pid:
                excluded["not_pregame_lead_passer"] += 1
                continue
            kind_name = "qb"
            idx = grade_engine.PASSING[market][0]
        else:
            continue
        draws = projector.draws(SEASON, row, kind_name)
        if not draws:
            excluded["no_projection"] += 1
            continue
        actual = getattr(row, grade_engine.RECEIVING[market][1] if market in grade_engine.RECEIVING
                         else grade_engine.PASSING[market][1])
        training.append({"game_id": gid, "week": week, "player_id": pid, "market": market,
                         "book": book, "line": line, "p_over": p_over(draws, idx, line),
                         "over": int(actual > line), "actual": actual})
    return training, {"missing_kickoff_time_rows": missing_start, **excluded}


def target_quote_probabilities(lines, players, distributions_by_pid, fit):
    a, b, n, n_pgs = fit
    out = []
    for row in lines:
        gsis, market = row["stable_player_id"], row["market"]
        player = next((p for p in players.values() if p["gsis"] == gsis), None)
        stat = MARKET_STATS.get(market)
        spec_p = platt_p = reason = None
        if player and market in DRAW_INDEX:
            kind, idx = DRAW_INDEX[market]
            draws = distributions_by_pid.get(player["pid"], {}).get("passing" if kind == "qb" else "receiving")
            if draws is not None:
                spec_p = p_over(draws, idx, float(row["line"]))
                platt_p = calibration.apply_map(a, b, spec_p)
            else:
                reason = "no Spec B simulation for this player/market"
        else:
            reason = ("Marcel-lite is point-only" if market in MARKET_STATS or market in COMBINED
                      else "market unsupported by Spec B distribution")
        if market in ("rushing_yards", "rush_attempts"):
            reason = "Spec B stores rushing point estimates but has no frozen rushing simulation distribution"
        if market in COMBINED:
            reason = "no joint distribution for combined stats"
        if market in ("interceptions_thrown",):
            reason = "unsupported by Marcel-lite and Spec B v2"
        out.append({"stable_player_id": gsis, "market": market, "model_metric": row["model_metric"],
                    "line": float(row["line"]), "actual": float(row["actual"]),
                    "over_hit": int(float(row["over_hit"])), "spec_b_v2_p_over": spec_p,
                    "forward_platt_p_over": platt_p, "marcel_lite_p_over": None,
                    "spec_b_status": "scored" if spec_p is not None else "unsupported",
                    "forward_platt_status": "scored" if platt_p is not None else "unsupported",
                    "marcel_status": "point_estimate_only", "exclusion_reason": reason,
                    "platt_a": a, "platt_b": b, "platt_training_items": n,
                    "platt_training_player_games": n_pgs})
    return out


def write_csv(path, rows):
    path = Path(path)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=Path("backend/data/picks.dev.db"))
    ap.add_argument("--snapshot", type=Path, default=HERE / "evidence/finalized-snapshot.json")
    ap.add_argument("--roster", type=Path, default=HERE / "evidence/full-depth-roster.json")
    ap.add_argument("--injuries", type=Path, default=HERE / "evidence/injuries_2026.parquet")
    ap.add_argument("--out-dir", type=Path, default=HERE)
    args = ap.parse_args()
    db_path = args.db.resolve()
    fd, temp_db_path = tempfile.mkstemp(prefix="was-nyg-player-replay-", suffix=".sqlite3")
    os.close(fd)
    db_snapshot_path = Path(temp_db_path)
    source = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    snapshot_db = sqlite3.connect(str(db_snapshot_path))
    source.backup(snapshot_db)
    snapshot_db.close()
    source.close()
    atexit.register(lambda: db_snapshot_path.unlink(missing_ok=True))
    con = sqlite3.connect("file:%s?mode=ro" % db_snapshot_path, uri=True)
    con.row_factory = None
    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get("as_of") != "2026-11-13T00:10:12Z":
        raise ValueError("unexpected finalized snapshot timestamp")
    if snapshot.get("roster_snapshot_source", {}).get("full_depth_roster_sha256") != sha256(args.roster):
        raise ValueError("roster file hash does not match finalized snapshot manifest")
    if snapshot.get("capture", {}).get("files") is None:
        raise ValueError("snapshot source capture manifest missing")
    frozen_injury = next(x for x in snapshot["capture"]["files"] if x["name"] == "injuries_2026.parquet")
    if sha256(args.injuries) != frozen_injury["sha256"]:
        raise ValueError("injury parquet hash does not match finalized snapshot manifest")
    players = roster_players(args.roster, con)
    full_roster = json.loads(args.roster.read_text())
    full_depth_gsis = {str(p["gsis_id"]) for side in ("away", "home")
                       for p in full_roster["rosters"][side]["players"] if p.get("gsis_id")}
    hist = make_history(con, args.injuries, players, snapshot)
    if hist.max_target_history_week > 9:
        raise AssertionError("post-Week-9 player logs entered model history")
    points, distributions_by_pid, projection_rows = {}, {}, []
    for player in players.values():
        spec, vals = model_point_projection(hist, player)
        points[player["pid"]] = vals
        dists = distributions(spec, player)
        distributions_by_pid[player["pid"]] = dists
        for (model, stat), value in sorted(vals.items()):
            if model == "spec_b_v2" and stat in {
                "pass_yards", "pass_attempts", "pass_completions", "pass_tds",
                "receiving_yards", "receptions", "targets", "receiving_touchdowns",
            }:
                continue  # distributions below are the single canonical record for these stats
            projection_rows.append({"model": model, "stable_player_id": player["gsis"],
                                    "player_id": player["pid"], "player": player["name"],
                                    "team": player["roster_team"], "position": player["position"],
                                    "starter": int(player["starter"]), "stat": stat,
                                    "mean": value, "median": None, "p10": None, "p90": None,
                                    "probability_gt_zero": None, "draws": None,
                                    "provenance": "retrospectively reconstructed"})
        for dist_name, draws in dists.items():
            spec_stats = ("rec", "rec_yds", "rec_td", "tgt") if dist_name == "receiving" else ("cmp", "pass_yds", "pass_td", "att")
            indexes = {"rec": 0, "rec_yds": 1, "rec_td": 2, "tgt": 3,
                       "cmp": 0, "pass_yds": 1, "pass_td": 2, "att": 3}
            mapping = {"rec": "receptions", "rec_yds": "receiving_yards", "rec_td": "receiving_touchdowns",
                       "tgt": "targets", "cmp": "pass_completions", "pass_yds": "pass_yards",
                       "pass_td": "pass_tds", "att": "pass_attempts"}
            for col in spec_stats:
                vals_sorted = sorted(draw[indexes[col]] for draw in draws)
                projection_rows.append({"model": "spec_b_v2", "stable_player_id": player["gsis"],
                                        "player_id": player["pid"], "player": player["name"],
                                        "team": player["roster_team"], "position": player["position"],
                                        "starter": int(player["starter"]), "stat": mapping[col],
                                        "mean": statistics.mean(vals_sorted), "median": eng.quantile(vals_sorted, .5),
                                        "p10": eng.quantile(vals_sorted, .1), "p90": eng.quantile(vals_sorted, .9),
                                        "probability_gt_zero": sum(v > 0 for v in vals_sorted) / len(vals_sorted),
                                        "draws": len(vals_sorted), "provenance": "retrospectively reconstructed"})
    training, training_exclusions = collect_training_items(con, hist)
    if not training:
        raise RuntimeError("no eligible pre-kickoff calibration observations in Weeks 2–9")
    fit = fit_forward_platt(training)
    a, b = fit[:2]
    lines = list(csv.DictReader((HERE / "graded-player-props.csv").open()))
    prop_rows = target_quote_probabilities(lines, players, distributions_by_pid, fit)
    for row in prop_rows:
        if row["spec_b_v2_p_over"] is not None:
            row["spec_b_v2_brier"] = (row["spec_b_v2_p_over"] - row["over_hit"]) ** 2
            row["forward_platt_brier"] = (row["forward_platt_p_over"] - row["over_hit"]) ** 2
        else:
            row["spec_b_v2_brier"] = row["forward_platt_brier"] = None
    comparison = build_comparison(lines, prop_rows, points, players, con)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    attach_actuals(projection_rows, con)
    write_csv(args.out_dir / "reconstructed-player-projections.csv", projection_rows)
    write_csv(args.out_dir / "reconstructed-player-prop-probabilities.csv", prop_rows)
    write_csv(args.out_dir / "player-model-comparison.csv", comparison)
    manifest = {
        "game_id": GAME_ID, "kickoff_cutoff_utc": CUTOFF, "forecast_provenance": "retrospectively reconstructed",
        "model_artifacts": {
            "marcel_lite": {"implementation": "backend/analytics/projections.py::project_stat; wrapper backend/nfl_player_projection_v2.py::marcel",
                             "source_sha256": sha256(BACKEND / "analytics/projections.py"), "probability_distribution": None},
            "spec_b_v2": {"implementation": "backend/nfl_player_projection_v2.py", "source_sha256": sha256(BACKEND / "nfl_player_projection_v2.py"),
                           "draws_per_player": N_SIMS, "distribution_constants": eng.DIST, "qb_distribution_constants": eng.QB_DEFAULTS,
                           "model_parameters": eng.DEFAULTS},
            "forward_platt": {"implementation": "backend/nfl_prop_calibration.py::fit_platt/apply_map",
                              "source_sha256": sha256(BACKEND / "nfl_prop_calibration.py"), "trained_weeks": list(range(2, WEEK)),
                              "training_items": fit[2], "training_player_games": fit[3], "a": a, "b": b,
                              "minimum_items": 200, "historical_quote_cutoff": "each quote captured before scheduled kickoff"}},
        "inputs": {"database_path": str(db_path), "database_snapshot_sha256": sha256(db_snapshot_path),
                   "database_snapshot_method": "SQLite online backup to a temporary read-only replay copy",
                   "database_observation_limit": "all target model history explicitly truncated to 2026 Week 9; Week 10 labels used only for grading",
                   "roster_snapshot_path": "evidence/finalized-snapshot.json", "roster_snapshot_sha256": sha256(args.snapshot),
                   "roster_path": "evidence/full-depth-roster.json", "roster_sha256": sha256(args.roster),
                   "injury_snapshot_path": "evidence/injuries_2026.parquet", "injury_snapshot_sha256": sha256(args.injuries),
                   "injury_snapshot_as_of_utc": snapshot["as_of"],
                   "injury_file_acquired_at_utc": frozen_injury["acquired_at_utc"],
                   "injury_file_source_last_modified_utc": frozen_injury["last_modified_utc"],
                   "pregame_prop_quotes": "saved graded-player-props.csv"},
        "frozen_roster_identity": snapshot["roster_snapshot_id"],
        "full_depth_roster_player_count": len(full_depth_gsis), "eligible_skill_player_count": len(players),
        "model_history": {"seasons": [2025, 2026], "latest_2026_week_in_model_history": hist.max_target_history_week,
                          "availability_source": "week 10 frozen injuries_2026.parquet; postgame-built player_game_availability excluded",
                          "unknown_status": "not treated as Out/Doubtful"},
        "training_exclusions": dict(training_exclusions),
        "coverage": {"saved_prop_items": len(lines),
                     "spec_b_v2": sum(x["spec_b_v2_p_over"] is not None for x in prop_rows),
                     "forward_platt": sum(x["forward_platt_p_over"] is not None for x in prop_rows),
                     "marcel_lite_probability": 0,
                     "unsupported_market_counts": dict(sorted((m, sum(r["market"] == m and r["spec_b_v2_p_over"] is None for r in prop_rows)) for m in {r["market"] for r in prop_rows}))},
        "outputs": ["reconstructed-player-projections.csv", "reconstructed-player-prop-probabilities.csv", "player-model-comparison.csv"],
        "limitations": ["Marcel-lite is point-estimate only; no empirical distribution or over probabilities are invented.",
                        "Spec B v2 has no frozen rushing or joint-stat simulation distribution; those prop lines are excluded from its Brier score.",
                        "Forward Platt uses Week 2–9 sportsbook observations reconstructed from pre-kickoff line captures; no Week 10 outcomes are in its fit.",
                        "Forecasts are reconstructed now from preserved pregame roster/injury files and cutoff-safe historical stats, not predictions frozen before kickoff."]}
    (args.out_dir / "player-model-replay-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    con.close()
    print(json.dumps({"training_items": fit[2], "training_player_games": fit[3], "platt_a": a, "platt_b": b,
                      "coverage": manifest["coverage"], "comparison": comparison}, indent=2))


def build_comparison(lines, prop_rows, point_map, players, con):
    prob_by_key = {(x["stable_player_id"], x["market"], float(x["line"])): x for x in prop_rows}
    line_by_key = {(x["stable_player_id"], x["market"], float(x["line"])): x for x in lines}
    slc_fields = {"v1": "v1_p_over", "v1.5": "v1.5_p_over", "v1.6": "v1.6_p_over", "v2": "v2_p_over"}
    common_keys = [key for key, p in prob_by_key.items() if p["spec_b_v2_p_over"] is not None and
                   all(line_by_key[key].get(field) not in (None, "") for field in slc_fields.values())]
    rows = []
    models = list(slc_fields) + ["spec_b_v2", "forward_platt", "marcel_lite", "devigged_market"]
    for model in models:
        ps, outcomes = [], []
        for key, line in line_by_key.items():
            item = prob_by_key[key]
            if model in slc_fields:
                p = float(line[slc_fields[model]])
            elif model == "spec_b_v2":
                p = item["spec_b_v2_p_over"]
            elif model == "forward_platt":
                p = item["forward_platt_p_over"]
            elif model == "devigged_market":
                p = line.get("mean_devig_market_p_over")
            else:
                p = None
            if p not in (None, ""):
                ps.append((key, float(p)))
                outcomes.append(int(line["over_hit"]))
        score = statistics.mean((p - y) ** 2 for (_, p), y in zip(ps, outcomes)) if ps else None
        cps, cys = [], []
        for key in common_keys:
            line, item = line_by_key[key], prob_by_key[key]
            p = (float(line[slc_fields[model]]) if model in slc_fields else
                 item["spec_b_v2_p_over"] if model == "spec_b_v2" else
                 item["forward_platt_p_over"] if model == "forward_platt" else
                 line.get("mean_devig_market_p_over") if model == "devigged_market" else None)
            if p not in (None, ""):
                cps.append(float(p)); cys.append(int(line["over_hit"]))
        common_score = statistics.mean((p - y) ** 2 for p, y in zip(cps, cys)) if cps else None
        rows.append({"comparison_type": "prop_probability_brier", "model": model, "stat": "",
                     "probability_items": len(ps), "probability_coverage_pct": round(100 * len(ps) / len(lines), 2),
                     "brier_on_covered_items": score, "common_spec_b_coverage_items": len(cps),
                     "brier_on_common_coverage": common_score, "point_forecast_count": 0, "point_mae": None,
                     "provenance": "frozen pregame batch" if model in slc_fields else
                                  "retrospectively reconstructed" if model != "devigged_market" else "frozen pregame market lines"})
    # Point forecast MAE is evaluated once per player/stat, never once per alternate line.
    actual_rows = con.execute(
        "SELECT player_id,stats FROM player_game_logs WHERE league='nfl' AND game_id=? AND game_type='REG'",
        (GAME_ID,)).fetchall()
    actuals = {}
    actual_keys = {"pass_yds": "pass_yds", "att": "att", "cmp": "cmp", "pass_td": "pass_td",
                   "rec_yds": "rec_yds", "rec": "rec", "tgt": "targets", "rush_yds": "rush_yds",
                   "car": "carries", "rush_td": "rush_td", "rec_td": "rec_td"}
    for pid, js in actual_rows:
        data = json.loads(js)
        for col, stat in ATTR_TO_STAT.items():
            actuals[(int(pid), stat)] = float(data.get(actual_keys[col], 0) or 0)
    for model in ("marcel_lite", "spec_b_v2"):
        for stat in ATTR_TO_STAT.values():
            errs = []
            for player in players.values():
                pred = point_map[player["pid"]].get((model, stat))
                actual = actuals.get((player["pid"], stat))
                if pred is not None and actual is not None:
                    errs.append(abs(pred - actual))
            if errs:
                rows.append({"comparison_type": "point_stat_mae", "model": model, "stat": stat,
                             "probability_items": 0, "probability_coverage_pct": None,
                             "brier_on_covered_items": None, "common_spec_b_coverage_items": 0,
                             "brier_on_common_coverage": None, "point_forecast_count": len(errs),
                             "point_mae": statistics.mean(errs),
                             "provenance": "retrospectively reconstructed; conditional point projections"})
    return rows


def attach_actuals(projection_rows, con):
    actual_names = {"pass_yards": "pass_yds", "pass_attempts": "att",
                    "pass_completions": "cmp", "pass_tds": "pass_td",
                    "receiving_yards": "rec_yds", "receptions": "rec", "targets": "targets",
                    "rush_yards": "rush_yds", "carries": "carries",
                    "rushing_touchdowns": "rush_td", "receiving_touchdowns": "rec_td"}
    pid_by_gsis = {str(gsis): int(pid) for pid, gsis in con.execute(
        "SELECT id,nfl_gsis_id FROM players WHERE league='nfl' AND nfl_gsis_id IS NOT NULL")}
    actual_by_pid = {}
    for pid, stats_json in con.execute(
            "SELECT player_id,stats FROM player_game_logs WHERE league='nfl' AND game_id=? AND game_type='REG'",
            (GAME_ID,)):
        actual_by_pid[int(pid)] = json.loads(stats_json)
    for row in projection_rows:
        pid = pid_by_gsis.get(row["stable_player_id"])
        payload = actual_by_pid.get(pid, {})
        key = actual_names.get(row["stat"])
        value = payload.get(key) if key else None
        row["actual"] = float(value) if value not in (None, "") else None
        row["absolute_error"] = abs(row["mean"] - row["actual"]) if row["actual"] is not None else None


if __name__ == "__main__":
    main()
