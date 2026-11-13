#!/usr/bin/env python3
"""Read-only, as-of WAS-NYG 2026 Week 10 player-model reconstruction.

Uses the SAVED 323-item SLC grading cohort, never target-game box scores as
features. Separates retrospectively reconstructed predictions from locked ones.
No injury status of the target game is imported from the current database.
Outputs are generated only on an explicit --run, and no SQLite writes occur.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import sqlite3
import statistics
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import nfl_player_projection_v2 as eng
import grade_nfl_prop_probabilities as historical_grader
import nfl_prop_calibration as calibration
from analytics.projections import project_stat, prob_over

GAME = "2026_10_WAS_NYG"
SEASON, WEEK = 2026, 10
KICKOFF = dt.datetime(2026, 11, 13, 1, 15, tzinfo=dt.timezone.utc)
ET = ZoneInfo("America/New_York")
DIRECT = {
    "passing_yards": "pass_yds", "pass_attempts": "att",
    "pass_completions": "cmp", "passing_touchdowns": "pass_td",
    "rushing_yards": "rush_yds", "rush_attempts": "car",
    "receiving_yards": "rec_yds", "receptions": "rec", "targets": "tgt",
}
# The frozen Spec B engine provides distributions for these markets only.
REC_INDICES = {"receiving_yards": 1, "receptions": 0, "targets": 3}
PASS_INDICES = {"passing_yards": 1, "pass_attempts": 3,
                "pass_completions": 0, "passing_touchdowns": 2}
MODELS = ("marcel-lite", "spec-b-v2", "forward-platt-v1")


def utc_stamp(value):
    if not isinstance(value, str):
        return None
    try:
        got = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if got.tzinfo is None:
        return None
    return got.astimezone(dt.timezone.utc)


def kickoff(gameday, gametime):
    if not gameday or not gametime:
        return None
    try:
        return dt.datetime.strptime(f"{gameday} {gametime}", "%Y-%m-%d %H:%M").replace(
            tzinfo=ET).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def prior_history(history):
    """Detach target/future game stats AND target/future availability entirely."""
    rows = [r for r in history.rows if r.season < SEASON
            or (r.season == SEASON and r.week < WEEK)]
    statuses = {k: v for k, v in history.status.items()
                if int(k[0]) < SEASON or
                (int(k[0]) == SEASON and int(str(k[1]).split("_")[1]) < WEEK)}
    result = eng.History(rows, statuses)
    assert not any(r.season == SEASON and r.week >= WEEK for r in result.rows)
    assert not any(k[0] == SEASON and int(str(k[1]).split("_")[1]) >= WEEK
                   for k in result.status)
    return result


def load_as_of_history(con):
    """Load only earlier regular-season boxscores and report rows at SQL level.

    The standard History.load reads all current-season outcomes before its
    internal method-level week filters. Never even read Week 10+ results or
    availability as potential features for this historical replay.
    """
    positions = {pid: pos for pid, pos in con.execute(
        "SELECT id,position FROM players WHERE league='nfl'")}
    rows = []
    sql = """SELECT l.player_id,l.team,l.game_id,l.stats,
                    s.season,s.week,s.away_team,s.home_team
             FROM player_game_logs l JOIN nfl_schedule s ON s.game_id=l.game_id
             WHERE l.league='nfl' AND l.source='nflverse_weekly'
               AND (l.game_type='REG' OR l.game_type IS NULL)
               AND l.team IS NOT NULL AND l.game_id IS NOT NULL
               AND s.season IN (?,?) AND (s.season<? OR s.week<?)
               AND s.game_type='REG'"""
    for pid, team, gid, stats, season, week, away, home in con.execute(
            sql, (SEASON-1, SEASON, SEASON, WEEK)):
        pos = positions.get(pid)
        if pos not in eng.SKILL:
            continue
        if team not in (away, home):
            raise RuntimeError(f"unplaced earlier player row {gid} {team} {pid}")
        rows.append(eng.Row(pid, season, week, team,
                            home if team == away else away,
                            gid, "RB" if pos == "FB" else pos,
                            json.loads(stats)))
    statuses = defaultdict(dict)
    sql = """SELECT a.season,a.game_id,a.team,a.player_id,a.report_status,a.played
             FROM player_game_availability a
             JOIN nfl_schedule s ON s.game_id=a.game_id
             WHERE a.league='nfl' AND s.season IN (?,?)
               AND (s.season<? OR s.week<?) AND s.game_type='REG'"""
    for season, gid, team, pid, report, played in con.execute(
            sql, (SEASON-1, SEASON, SEASON, WEEK)):
        statuses[(season, gid, team)][pid] = (report, played)
    return prior_history(eng.History(rows, statuses))


def read_cohort(report):
    with (report / "graded-player-props.csv").open(newline="") as fp:
        rows = list(csv.DictReader(fp))
    if len(rows) != 323:
        raise ValueError(f"expected pinned 323-line cohort, got {len(rows)}")
    keys = [(r["stable_player_id"], r["market"], float(r["line"])) for r in rows]
    if len(set(keys)) != len(rows):
        raise ValueError("duplicate canonical player/market/line in pinned cohort")
    return rows


def model_roster(report):
    # SLC player output was derived from the pregame roster snapshot.
    teams = defaultdict(set)
    with (report / "player-projections.csv").open(newline="") as fp:
        for r in csv.DictReader(fp):
            if r["model"] == "v1.6":
                team = {"WAS": "WSH", "WSH": "WSH"}.get(r["team"], r["team"])
                teams[r["stable_player_id"]].add(team)
    return {gid: next(iter(cs)) for gid, cs in teams.items() if len(cs) == 1}


def choose_team(hist, gid, roster, schedule_teams, pid):
    if gid in roster:
        team = roster[gid]
        if team in schedule_teams:
            return team, "saved_pregame_slc_roster"
    candidates = {r.team for r in hist.by_player.get((SEASON, pid), [])
                  if r.team in schedule_teams}
    if len(candidates) == 1:
        return next(iter(candidates)), "pre_week10_player_logs"
    return None, "unresolved_pregame_team"


def raw_player_projections(hist, pid, team, opponent, position, market, sims=4000):
    """Return model-specific (mean, quantiles, empirical p-over supplier).

    Projection construction does not receive the observed target-game result.
    """
    metric = DIRECT.get(market)
    values = [getattr(r, metric) for r in reversed(hist.by_player.get((SEASON, pid), []))
              if r.week < WEEK] if metric else []
    marcel = project_stat(values) if metric else None
    out = {"marcel-lite": None, "spec-b-v2": None}
    if marcel:
        out["marcel-lite"] = {"mean": marcel["projection"],
                              "median": marcel["median"],
                              "p10": marcel["floor"], "p90": marcel["ceiling"],
                              "values": values,
                              "distribution_kind": "prior_games_empirical_hit_rate",
                              "n": len(values)}
    if market in PASS_INDICES and position == "QB":
        # Expected starter chosen from earlier games, never from target-game attempts.
        leader = historical_grader.pregame_leader(hist, SEASON, team, WEEK)
        if leader != pid:
            return out
        point = eng.project_qb(hist, SEASON, WEEK, pid, team, opponent, GAME)
        if point and point["att"] > 0:
            seed = zlib.crc32((f"{GAME}|{pid}|qb").encode()) & 0xffff
            draws = eng.simulate_qb(point["att"], point["cmp"]/point["att"],
                                    point["pass_yds"]/point["cmp"] if point["cmp"] else 0.0,
                                    point["pass_td"]/point["att"], n=sims, seed=seed)
            out["spec-b-v2"] = _dist(point[metric], draws, PASS_INDICES[market])
    elif market in REC_INDICES and position in ("RB", "WR", "TE"):
        point = eng.project(hist, SEASON, WEEK, pid, position, team, opponent, GAME)
        if point and point.get("tgt", 0) > 0:
            seed = zlib.crc32((f"{GAME}|{pid}|rec").encode()) & 0xffff
            draws = eng.simulate(point["tgt"], point["rec"]/point["tgt"],
                                 point["rec_yds"]/point["rec"] if point["rec"] else 0.0,
                                 point["rec_td"]/point["tgt"], n=sims, seed=seed)
            out["spec-b-v2"] = _dist(point[metric], draws, REC_INDICES[market])
    # Rushing and combined-market point models have no frozen Spec B draw engine.
    elif metric in ("rush_yds", "car"):
        point = eng.project(hist, SEASON, WEEK, pid, position, team, opponent, GAME)
        if point and metric in point:
            out["spec-b-v2"] = {"mean": point[metric], "median": None,
                                 "p10": None, "p90": None, "values": None,
                                 "distribution_kind": "point_only_no_probabilities", "n": 0}
    return out


def _dist(mean, draws, index):
    vals = sorted(d[index] for d in draws)
    return {"mean": mean, "median": eng.quantile(vals, .5),
            "p10": eng.quantile(vals, .1), "p90": eng.quantile(vals, .9),
            "values": vals, "distribution_kind": "frozen_spec_b_draws", "n": len(vals)}


def p_over(model, prediction, line):
    if prediction is None or prediction["values"] is None:
        return None
    if model == "marcel-lite":
        return prob_over(prediction["values"], line)["p_over"]
    return sum(value > line for value in prediction["values"]) / len(prediction["values"])


def historic_training(con, hist, *, cutoff=KICKOFF, min_items=500):
    """Reconstruct strict earlier-week Platt cohort, excluding later/late quotes.

    Preserves the earlier-week observed-played selection limitation; target
    WAS-NYG results, current injury status and Week 10 never enter this fit.
    """
    allowed = set(historical_grader.BOOKS)
    markets = set(historical_grader.RECEIVING) | set(historical_grader.PASSING)
    latest = {}
    excluded = Counter()
    sql = """SELECT s.game_id,s.week,s.gameday,s.gametime,
                    p.player_id,p.market,p.source,p.line,p.side,p.odds,p.captured_at
             FROM props p JOIN prop_games g ON g.id=p.game_id
             JOIN nfl_schedule s ON s.gameday=g.date
               AND s.home_team=g.home AND s.away_team=g.away
             WHERE g.league='nfl' AND s.season=? AND s.week<?
               AND s.game_type='REG' AND p.odds IS NOT NULL"""
    for gid, week, day, time, pid, market, book, line, side, odds, seen in con.execute(sql, (SEASON, WEEK)):
        if market not in markets or book not in allowed:
            continue
        limit, stamp = kickoff(day, time), utc_stamp(seen)
        if limit is None or stamp is None or stamp >= limit or limit >= cutoff:
            excluded["unknown_or_late_capture"] += 1
            continue
        key = (gid, int(week), int(pid), market, book, float(line), str(side).lower())
        if key not in latest or stamp > latest[key][0]:
            latest[key] = (stamp, odds)
    projector = historical_grader.Projector(hist)
    training = []
    for (gid, week, pid, market, book, line, side), (stamp, odds) in latest.items():
        if side != "over":
            continue
        other = latest.get((gid, week, pid, market, book, line, "under"))
        if other is None or abs((stamp - other[0]).total_seconds()) > 1800:
            excluded["unpaired_or_stale"] += 1
            continue
        if line == int(line):
            excluded["whole_line"] += 1
            continue
        played = next((r for r in hist.by_player.get((SEASON, pid), [])
                       if r.game_id == gid), None)
        if played is None:
            excluded["no_player_result"] += 1
            continue
        if market in historical_grader.RECEIVING:
            if played.pos not in ("RB", "WR", "TE"):
                continue
            index, attr = historical_grader.RECEIVING[market]
            kind = "rec"
        else:
            if played.pos != "QB" or historical_grader.pregame_leader(
                    hist, SEASON, played.team, week) != pid:
                continue
            index, attr = historical_grader.PASSING[market]
            kind = "qb"
        draws = projector.draws(SEASON, played, kind)
        if not draws:
            excluded["no_projection"] += 1
            continue
        p = sum(d[index] > line for d in draws) / len(draws)
        training.append({"game_id": gid, "week": week, "player_id": pid,
                         "p_raw": p, "over": int(getattr(played, attr) > line)})
    if any(r["week"] >= WEEK for r in training):
        raise AssertionError("calibration contains target or future game outcomes")
    fit = None
    if len(training) >= min_items:
        a, b = calibration.fit_platt([(r["p_raw"], r["over"]) for r in training])
        if math.isfinite(a) and math.isfinite(b) and a > 0:
            fit = {"slope": a, "intercept": b, "trained_items": len(training),
                   "trained_player_games": len({(r["game_id"], r["player_id"])
                                               for r in training}),
                   "train_latest_week": max(r["week"] for r in training)}
        else:
            excluded["invalid_nonmonotone_fit"] += 1
    return fit, dict(excluded), len(training)


def _write_csv(path, rows, columns):
    with path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _sha(path):
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for block in iter(lambda: fp.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def run(dbpath, report, sims=4000):
    rows = read_cohort(report)
    roster = model_roster(report)
    with sqlite3.connect(f"file:{dbpath}?mode=ro", uri=True) as con:
        # One consistent SQLite read snapshot, even if the ingest host is
        # concurrently updating another connection in WAL mode.
        con.execute("BEGIN")
        game = con.execute("SELECT away_team,home_team FROM nfl_schedule WHERE game_id=?", (GAME,)).fetchone()
        if not game:
            raise RuntimeError(f"schedule missing {GAME}")
        away, home = game
        both = {away, home}
        people = {str(gid): (int(pid), name, pos)
                  for pid, gid, name, pos in con.execute(
                      "SELECT id,nfl_gsis_id,name,position FROM players WHERE league='nfl'"
                  ) if gid}
        history = load_as_of_history(con)
        predictions = []
        probs = []
        uncovered = Counter()
        cache = {}
        for row in rows:
            gid, market, line = row["stable_player_id"], row["market"], float(row["line"])
            player = people.get(gid)
            if not player:
                uncovered["unknown_gsis_identity"] += 1
                continue
            pid, name, pos = player
            team, source = choose_team(history, gid, roster, both, pid)
            if team is None:
                uncovered["unresolved_pregame_team"] += 1
                continue
            opp = home if team == away else away
            key = (gid, market)
            if key not in cache:
                cache[key] = raw_player_projections(history, pid, team, opp, pos, market, sims)
                for model, pred in cache[key].items():
                    if pred is None:
                        continue
                    predictions.append({
                        "model": model, "game_id": GAME, "stable_player_id": gid,
                        "player_id": pid, "player_name": name, "position": pos,
                        "team": team, "team_source": source, "market": market,
                        "model_metric": DIRECT.get(market), "actual": float(row["actual"]),
                        "mean": pred["mean"], "absolute_error": abs(pred["mean"] - float(row["actual"])),
                        "median": pred["median"], "p10": pred["p10"], "p90": pred["p90"],
                        "draws_or_prior_games": pred["n"],
                        "distribution_kind": pred["distribution_kind"],
                        "input_status": "reconstructed_without_verified_week10_injury_report"})
            for model in ("marcel-lite", "spec-b-v2"):
                p = p_over(model, cache[key].get(model), line)
                probs.append({"model": model, "game_id": GAME,
                              "stable_player_id": gid, "market": market,
                              "line": line, "p_over": p,
                              "status": "scored" if p is not None else "unsupported_or_no_history"})
        # Earlier-week records alone may fit the map; no target-game result.
        platt, training_exclusions, training_n = historic_training(con, history)
        for row in rows:
            key = (row["stable_player_id"], row["market"], float(row["line"]))
            raw = next((p for p in probs if p["model"] == "spec-b-v2" and
                        (p["stable_player_id"], p["market"], p["line"]) == key), None)
            valid = raw is not None and raw["p_over"] is not None
            p_cal = (calibration.apply_map(platt["slope"], platt["intercept"], raw["p_over"])
                     if valid and platt else None)
            probs.append({"model": "forward-platt-v1", "game_id": GAME,
                          "stable_player_id": key[0], "market": key[1], "line": key[2],
                          "p_over": p_cal,
                          "status": ("scored" if p_cal is not None else
                                     "no_preweek10_fit" if platt is None else
                                     "unsupported_or_no_history")})

    if not any(p["p_over"] is not None for p in probs):
        raise RuntimeError("no reproducible player prop probabilities; inspect roster/history joins")
    out = report
    projection_cols = ("model", "game_id", "stable_player_id", "player_id", "player_name",
                       "position", "team", "team_source", "market", "model_metric",
                       "actual", "mean", "absolute_error", "median", "p10", "p90", "draws_or_prior_games",
                       "distribution_kind", "input_status")
    prob_cols = ("model", "game_id", "stable_player_id", "market", "line", "p_over", "status")
    _write_csv(out/"reconstructed-player-projections.csv", predictions, projection_cols)
    _write_csv(out/"reconstructed-player-prop-probabilities.csv", probs, prob_cols)
    cohort = {(r["stable_player_id"], r["market"], float(r["line"])): r for r in rows}
    by_model = defaultdict(dict)
    for p in probs:
        if p["p_over"] is not None:
            key = (p["stable_player_id"], p["market"], float(p["line"]))
            by_model[p["model"]][key] = float(p["p_over"])
    comparison = []
    # Every comparison uses the *same subset for the model, SLC and market*.
    # Also preserve the original all-323 scores without changing them.
    for model in MODELS:
        available = by_model[model]
        subset = [cohort[k] for k in sorted(available)]
        for segment in ("ALL", *sorted({r["market"] for r in subset})):
            items = [r for r in subset if segment == "ALL" or r["market"] == segment]
            if not items:
                continue
            norm = lambda values: statistics.mean(values)
            market = norm([(float(r["mean_devig_market_p_over"])-float(r["over_hit"]))**2
                           for r in items])
            for kind in (model, "v1", "v1.5", "v1.6", "v2", "market"):
                vals = []
                for r in items:
                    key = (r["stable_player_id"], r["market"], float(r["line"]))
                    p = (available[key] if kind == model else
                         float(r["mean_devig_market_p_over"]) if kind == "market" else
                         float(r[f"{kind}_p_over"]))
                    vals.append((p-float(r["over_hit"]))**2)
                comparison.append({"scope": f"{model}_matched", "market": segment,
                                   "model": kind, "items": len(items),
                                   "player_markets": len({(r["stable_player_id"], r["market"])
                                                         for r in items}),
                                   "brier": norm(vals), "matched_market_brier": market,
                                   "gap_to_market": norm(vals)-market})
    cmp_cols = ("scope", "market", "model", "items", "player_markets",
                "brier", "matched_market_brier", "gap_to_market")
    _write_csv(out/"player-model-comparison.csv", comparison, cmp_cols)
    manifest = {
        "game": GAME, "pregame_cutoff_utc": KICKOFF.isoformat(),
        "classification": "retrospective_as_of_reconstruction_not_pregame_lock",
        "source_database": str(dbpath.resolve()), "db_sha256": _sha(dbpath),
        "db_mode": "read_only", "target_game_result_used_as_feature": False,
        "target_week_or_later_game_logs_in_projection_history": 0,
        "target_week_or_later_availability_in_projection_history": 0,
        "target_game_injury_status": "not_used_missing_verified_pregame_evidence",
        "precutoff_injury_provenance": "not_verified",
        "spec_b_n_sims": sims,
        "spec_b_parameter_version": "repository_frozen_defaults",
        "platt": platt, "platt_training_items": training_n,
        "platt_training_exclusions": training_exclusions,
        "platt_cohort": "preweek10_strict_capture_both_sides_within_30_minutes",
        "platt_limitation": ("historical earlier-week participation and injury states "
                             "were retrospectively reconstructed, not pregame locked"),
        "input_sha256": {name: _sha(report/name) for name in
                         ("graded-player-props.csv", "player-projections.csv",
                          "pregame-prop-quotes.csv")},
        "output_rows": {"projections": len(predictions), "probabilities": len(probs),
                        "comparison": len(comparison)},
        "uncovered_identities": dict(uncovered),
    }
    (out/"player-model-replay-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True)+"\n")
    section = ["## Reconstructed player-model comparison (research only)", "",
               "These additional player-model outputs were **reconstructed after the game** using pre-Week-10",
               "historical player logs and the pinned 323-line pregame cohort. They are **not pregame locks**.",
               "Target-game and later injury/availability rows were excluded, rather than treating current",
               "database state as a timestamped pregame injury report. Earlier-week injury provenance is",
               "not independently verified; coverage is conditional on supported players/markets.", "",
               "| Comparison subset | Model | Items | Brier | Market on same items | Gap |",
               "|---|---|---:|---:|---:|---:|"]
    for model in MODELS:
        sub = [r for r in comparison if r["scope"] == f"{model}_matched" and
               r["market"] == "ALL" and r["model"] in (model, "v1.6", "market")]
        if not sub:
            section.append(f"| {model} | unavailable | 0 | — | — | — |")
        else:
            for r in sub:
                section.append(f"| {model} | {r['model']} | {r['items']} | "
                               f"{r['brier']:.4f} | {r['matched_market_brier']:.4f} | "
                               f"{r['gap_to_market']:+.4f} |")
    section.extend(["", "### Selected player mean projections versus final box score", "",
                    "| Player | Stat | Actual | Marcel-lite | Spec B |",
                    "|---|---|---:|---:|---:|"])
    grouped = defaultdict(dict)
    for p in predictions:
        grouped[(p["player_name"], p["market"], p["actual"])][p["model"]] = p["mean"]
    # One row per player/market, largest available Spec B absolute misses first.
    selected = sorted(grouped.items(), key=lambda kv:
                      abs(kv[1].get("spec-b-v2", kv[1].get("marcel-lite", kv[0][2]))
                          - kv[0][2]), reverse=True)[:15]
    for (name, market, actual), values in selected:
        marcel = f'{values["marcel-lite"]:.1f}' if "marcel-lite" in values else "—"
        specb = f'{values["spec-b-v2"]:.1f}' if "spec-b-v2" in values else "—"
        section.append(f"| {name} | {market} | {actual:g} | {marcel} | {specb} |")
    section.extend(["", "This table is selected after the game for diagnosis, not a prospective ranking.", "",
                    "No ranking across different model-coverage subsets is valid.",
                    "Raw frozen SLC grades remain unchanged. Platt is a line-probability",
                    "calibration on Spec B, **not** a separate player-stat distribution.",
                    "Historical Marcel-lite probabilities remain uncalibrated hit rates.",
                    "The full tables and source hashes are in the reconstructed CSVs and replay manifest.", ""])
    readme = out/"README.md"
    original = readme.read_text()
    marker = "## Reconstructed player-model comparison (research only)"
    if marker in original:
        original = original[:original.index(marker)].rstrip() + "\n"
    readme.write_text(original.rstrip()+"\n\n"+"\n".join(section))
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--report-dir", type=Path, required=True)
    ap.add_argument("--sims", type=int, default=4000)
    args = ap.parse_args(argv)
    if not args.db.is_file():
        ap.error("database file not found")
    if args.sims < 100:
        ap.error("--sims must be >=100")
    result = run(args.db, args.report_dir, args.sims)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
