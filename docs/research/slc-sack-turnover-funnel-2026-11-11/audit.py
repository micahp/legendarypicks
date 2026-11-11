#!/usr/bin/env python3
"""Score SLC's event-weighting funnel on clean, observed 2025 dropbacks.

No simulation is performed. The test compares the exact-cell league event mix with
the existing offense, defense and combined team-outcome reweights. Training and
test penalty eligibility comes from the frozen nflverse parquet, not nullable DB
flags. Later SLC modifiers are deliberately reported as outside this funnel.
"""
from __future__ import annotations

import collections
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts/nfl_sequence"))
sys.path.insert(0, str(REPO / "docs/research/slc-v2-conditional-outcome-audit-2026-11-10"))
import e0_single_play as e0
import e1_drive as e1
import team_season_adapt as tsa
import team_tendency as tt
import audit as prior_audit

PBP_DIR = Path("/root/lp-snapshots/nfl-backfill-2026-10-27/raw/pbp")
SCHEDULES = Path("/root/lp-snapshots/nfl-backfill-2026-10-27/raw/schedules/games.parquet")
OUT = Path(__file__).with_name("funnel-results.json")
TRAIN_SEASONS = (2022, 2023, 2024)
TEST_SEASON = 2025
EVENTS = ("sack", "interception", "fumble_lost", "pass_incomplete", "pass_complete")
METHODS = ("league", "offense_only", "defense_only", "matchup")
BOOTSTRAPS = 2000


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def penalty_overlay(season: int):
    path = PBP_DIR / f"play_by_play_{season}.parquet"
    table = pq.read_table(path, columns=["game_id", "play_id", "penalty"])
    columns = table.to_pydict()
    games, plays, flags = columns["game_id"], columns["play_id"], columns["penalty"]
    status = {}
    for game, play, flag in zip(games, plays, flags):
        if game is None or play is None:
            continue
        key = (game, int(play))
        if key in status:
            raise ValueError(f"duplicate source PBP identity: {key}")
        status[key] = None if flag is None else bool(flag)
    coverage = collections.Counter("unknown" if value is None else "penalty" if value else "clean"
                                   for value in status.values())
    return status, {"path": str(path), "sha256": sha256(path), "rows": len(status),
                    "penalty_status": dict(coverage)}


def apply_overlay(rows, overlay):
    """Mark flagged and unknown rows excluded while retaining sequence for next-snap logic."""
    missing = 0
    out = []
    for row in rows:
        row = dict(row)
        status = overlay.get((row["game_id"], int(row["play_id"])))
        if status is not False:
            row["penalty"] = 1
            missing += int((row["game_id"], int(row["play_id"])) not in overlay)
        else:
            row["penalty"] = 0
        out.append(row)
    return out, missing


def read_rows(season: int):
    path = PBP_DIR / f"play_by_play_{season}.parquet"
    table = pq.read_table(path, columns=[*e1.COLUMNS, "season_type"])
    rows = []
    for values in table.to_pylist():
        if values.get("season_type") != "REG" or values.get("week") is None or int(values["week"]) > 18:
            continue
        rows.append({key: values[key] for key in e1.COLUMNS})
    rows.sort(key=lambda row: (row["game_id"], int(row["play_id"])))
    return rows


def classify(rows):
    by_game = collections.defaultdict(list)
    for row in rows:
        by_game[row["game_id"]].append(row)
    out = collections.defaultdict(list)
    excluded = collections.Counter()
    for game, plays in by_game.items():
        for i, row in enumerate(plays):
            if row.get("qtr") is None or int(row["qtr"]) > 4:
                excluded["overtime"] += 1
                continue
            nxt = plays[i + 1] if i + 1 < len(plays) else None
            why = collections.Counter()
            result = e1.classify(row, nxt, why, include_qb_scrambles=False)
            excluded.update(why)
            if result is not None:
                event, _, _ = result
                if event not in e1.KICK_EVENTS:
                    out[game].append((row, event))
    return out, excluded


def metric(records):
    n = len(records)
    if not n:
        return {"n": 0, "observed_rate": None, "predicted_rate": None,
                "brier": None, "log_loss": None}
    actual = np.fromiter((x[0] for x in records), dtype=np.float64, count=n)
    p = np.clip(np.fromiter((x[1] for x in records), dtype=np.float64, count=n), 1e-12, 1-1e-12)
    return {"n": n, "observed_rate": float(actual.mean()), "predicted_rate": float(p.mean()),
            "brier": float(np.mean((p-actual)**2)),
            "log_loss": float(-np.mean(actual*np.log(p)+(1-actual)*np.log1p(-p)))}


def multiclass_metric(records):
    n = len(records)
    if not n:
        return {"n": 0, "log_loss": None, "brier": None}
    losses, briers = [], []
    for actual, probs in records:
        p = max(1e-12, probs.get(actual, 0.0))
        losses.append(-math.log(p))
        briers.append(sum((value-(1.0 if event == actual else 0.0))**2
                          for event, value in probs.items()))
    return {"n": n, "log_loss": float(np.mean(losses)), "brier": float(np.mean(briers))}


def main():
    overlays, source_info = {}, {}
    for season in (*TRAIN_SEASONS, TEST_SEASON):
        overlays[season], source_info[season] = penalty_overlay(season)

    train_rows = [row for year in TRAIN_SEASONS for row in read_rows(year)]
    train_rows, missing_train = apply_overlay(train_rows, {k:v for y in TRAIN_SEASONS for k,v in overlays[y].items()})
    pool, pool_excluded, team_pool = e1.build_pools(train_rows, regulation_only=True,
                                                    team_before_season=TEST_SEASON)
    hist = tt.build_from_team_pool(team_pool, TEST_SEASON, cutoff=(TEST_SEASON, 1))

    # Pregame team bins use only clean training evidence and EPA from the same seasons.
    raw_epa = []
    for year in TRAIN_SEASONS:
        p = PBP_DIR / f"play_by_play_{year}.parquet"
        cols = ["game_id", "play_id", "season_type", "week", "qtr", "posteam", "defteam", "epa", "penalty"]
        for row in pq.read_table(p, columns=cols).to_pylist():
            if (row["season_type"] == "REG" and row["week"] is not None and int(row["week"]) <= 18
                    and row["qtr"] is not None and 1 <= int(row["qtr"]) <= 4
                    and row["epa"] is not None and row["play_id"] is not None
                    and row["penalty"] is not None and not bool(row["penalty"])
                    and row["posteam"] and row["defteam"]):
                raw_epa.append((row["game_id"], int(row["play_id"]), row["posteam"], row["defteam"], row["epa"]))
    off_sum, off_n, def_sum, def_n = (collections.Counter() for _ in range(4))
    for game, play, offense, defense, epa in raw_epa:
        off_sum[offense] += float(epa); off_n[offense] += 1
        def_sum[defense] += float(epa); def_n[defense] += 1
    off_rate = {team: off_sum[team]/n for team,n in off_n.items() if n}
    def_rate = {team: def_sum[team]/n for team,n in def_n.items() if n}
    def tertiles(values, high_is_strong):
        ordered = sorted(values, key=values.get)
        q = max(1, len(ordered)//4)
        if high_is_strong:
            return {t: "weak" if i < q else "strong" if i >= len(ordered)-q else "middle"
                    for i,t in enumerate(ordered)}
        return {t: "strong" if i < q else "weak" if i >= len(ordered)-q else "middle"
                for i,t in enumerate(ordered)}
    off_bin, def_bin = tertiles(off_rate, True), tertiles(def_rate, False)

    test_rows = read_rows(TEST_SEASON)
    test_rows, missing_test = apply_overlay(test_rows, overlays[TEST_SEASON])
    by_game, excluded = classify(test_rows)
    schedule_table = pq.read_table(SCHEDULES, columns=["game_id","season","week","gameday","gametime",
                                                       "home_team","away_team","game_type"])
    schedule = [row for row in schedule_table.to_pylist()
                if int(row["season"]) == TEST_SEASON and row["game_type"] == "REG"]
    schedule_by_id = {r["game_id"]:r for r in schedule}
    plays_by_game = collections.defaultdict(list)
    for row in test_rows:
        plays_by_game[row["game_id"]].append(row)

    groups = collections.defaultdict(list)
    cutoffs = {}
    for gid in by_game:
        sr = schedule_by_id.get(gid)
        if not sr or not sr.get("gameday") or not sr.get("gametime"):
            continue
        cutoff = tsa.cutoff_utc(tsa.kickoff_utc(sr["gameday"], sr["gametime"]))
        available, _ = tsa.available_games(schedule, TEST_SEASON, cutoff, gid)
        key = tuple(available)
        groups[key].append(gid)
        cutoffs[key] = cutoff.isoformat()

    multi_rows = {m: collections.defaultdict(list) for m in METHODS}
    predicted_mix = {m: collections.Counter() for m in METHODS}
    prediction_counts = collections.Counter()
    score_rows = {target: {m: collections.defaultdict(list) for m in METHODS}
                  for target in ("sack", "interception", "fumble_lost", "turnover")}
    score_game = {target: {m: collections.defaultdict(list) for m in METHODS}
                  for target in ("sack", "interception", "fumble_lost", "turnover")}
    support = collections.Counter()
    stage_support = collections.Counter()
    teams = collections.Counter()
    cache_by_adaptation = {}

    for available_ids, games in groups.items():
        if available_ids not in cache_by_adaptation:
            current = [r for gid in available_ids for r in plays_by_game.get(gid, ())]
            tg = collections.Counter()
            for gid in available_ids:
                sr = schedule_by_id[gid]
                tg[sr.get("home_team")] += 1
                tg[sr.get("away_team")] += 1
            adapted, _ = tsa.adapt(hist, current, n0=4.0, team_games=dict(tg)) if current else (hist, {})
            cache_by_adaptation[available_ids] = adapted
        adapted = cache_by_adaptation[available_ids]
        probability_cache = {}
        for gid in games:
            for row, actual in by_game[gid]:
                if actual not in EVENTS or row.get("play_type") != "pass":
                    continue
                cell = e0.pool_key(int(row["down"]), row["ydstogo"], row["yardline_100"])
                key = (cell, row["posteam"], row["defteam"])
                if key not in probability_cache:
                    samples = [sample for sample in pool.get(cell, ()) if sample[0] in EVENTS and sample[0] != "punt"]
                    by_intent = collections.Counter()
                    for event, source_row, _runoff, _spot in samples:
                        intent = "run" if source_row.get("play_type") == "run" else "dropback"
                        if intent == "dropback":
                            by_intent[event] += 1
                    if sum(by_intent.values()) < 10:
                        probability_cache[key] = None
                    else:
                        base = {event: float(by_intent[event]) for event in by_intent}
                        distributions = {}
                        for method in METHODS:
                            weights = dict(base)
                            if method in ("offense_only", "matchup"):
                                for event in weights:
                                    before = adapted.fallback_count
                                    weights[event] *= adapted.ratio("offense", row["posteam"], cell, event)
                                    stage_support["offense_ratio_applications"] += 1
                                    if adapted.fallback_count > before:
                                        stage_support["offense_ratio_fallbacks"] += 1
                            if method in ("defense_only", "matchup"):
                                for event in weights:
                                    before = adapted.fallback_count
                                    weights[event] *= adapted.ratio("defense", row["defteam"], cell, event)
                                    stage_support["defense_ratio_applications"] += 1
                                    if adapted.fallback_count > before:
                                        stage_support["defense_ratio_fallbacks"] += 1
                            z = sum(weights.values())
                            if not z or not math.isfinite(z):
                                raise ValueError(f"invalid normalized outcome weights at {gid}:{row['play_id']}")
                            distributions[method] = {event: value/z for event,value in weights.items()}
                        probability_cache[key] = distributions
                distributions = probability_cache[key]
                if distributions is None:
                    support["unsupported_exact_cells"] += 1
                    continue
                support["scored_dropbacks"] += 1
                support["event_space_rows"] += 1
                teams[row["posteam"]] += 1
                off_group = off_bin.get(row["posteam"], "unknown")
                def_group = def_bin.get(row["defteam"], "unknown")
                strata = ("all", f"offense:{row['posteam']}", f"defense:{row['defteam']}",
                          f"strength:{off_group}x{def_group}", f"matchup:{row['posteam']}-{row['defteam']}")
                for method, probs in distributions.items():
                    predicted_mix[method].update(probs)
                    prediction_counts[method] += 1
                    for stratum in strata:
                        multi_rows[method][stratum].append((actual, probs))
                    for target in ("sack", "interception", "fumble_lost", "turnover"):
                        probability = (probs.get("interception",0.0)+probs.get("fumble_lost",0.0)
                                       if target == "turnover" else probs.get(target,0.0))
                        observed = int(actual in (("interception","fumble_lost") if target == "turnover" else (target,)))
                        for stratum in strata:
                            score_rows[target][method][stratum].append((observed, probability))
                        score_game[target][method][gid].append(-math.log(max(1e-12, probability if observed else 1-probability)))

    overall = {method: multiclass_metric(multi_rows[method]["all"]) for method in METHODS}
    event_scores = {target: {method: metric(score_rows[target][method]["all"]) for method in METHODS}
                    for target in score_rows}
    team_event_scores = {}
    for team in sorted(teams):
        team_event_scores[team] = {
            "offense": {target: {method:metric(score_rows[target][method][f"offense:{team}"]) for method in METHODS}
                        for target in score_rows},
            "defense": {target: {method:metric(score_rows[target][method][f"defense:{team}"]) for method in METHODS}
                        for target in score_rows},
        }
    by_group = {}
    binary_3x3 = {}
    for group in ("weakxstrong","weakxmiddle","weakxweak","middlexstrong","middlexmiddle",
                  "middlexweak","strongxstrong","strongxmiddle","strongxweak"):
        by_group[group] = {method:multiclass_metric(multi_rows[method].get(f"strength:{group}",[])) for method in METHODS}
        binary_3x3[group] = {
            target: {method:metric(score_rows[target][method].get(f"strength:{group}",[])) for method in METHODS}
            for target in score_rows
        }

    # Bootstrap paired multinomial log-loss deltas using game-level totals.
    # Per-target bootstrap input is produced from the observed-score arrays grouped by game above.
    deltas = {}
    for target in score_game:
        deltas[target] = {}
        for candidate in ("offense_only","defense_only","matchup"):
            # Aggregate per-game binary cross entropy from scored play outcomes.
            per_game = {m: {g:(sum(vals),len(vals)) for g,vals in score_game[target][m].items()} for m in ("league",candidate)}
            shared = sorted(set(per_game["league"]) & set(per_game[candidate]))
            rng = np.random.default_rng(20261111 + len(target) + len(candidate))
            draws = []
            if len(shared) >= 2:
                for _ in range(BOOTSTRAPS):
                    selected = rng.integers(0,len(shared),size=len(shared))
                    sums = {m:0.0 for m in ("league",candidate)}
                    counts = {m:0 for m in ("league",candidate)}
                    for idx in selected:
                        g=shared[idx]
                        for m in sums:
                            s,n=per_game[m][g];sums[m]+=s;counts[m]+=n
                    draws.append(sums[candidate]/counts[candidate]-sums["league"]/counts["league"])
            deltas[target][candidate] = {"league_game_count":len(shared),
                "log_loss_delta_ci95": [float(x) for x in np.quantile(draws,[.025,.975])] if draws else None,
                "candidate_minus_league": event_scores[target][candidate]["log_loss"]-event_scores[target]["league"]["log_loss"]}

    result = {
        "schema":"slc-sack-turnover-funnel-v1", "test_season":TEST_SEASON,
        "training_seasons":list(TRAIN_SEASONS), "database_used":False,
        "code":{"git_head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=REPO,text=True).strip(),
                "audit_sha256":sha256(Path(__file__).resolve())},
        "schedule_source":{"path":str(SCHEDULES),"sha256":sha256(SCHEDULES),
                            "regular_season_games_2025":len(schedule)},
        "source_penalty_overlay":source_info,
        "source_eligibility":{"training_rows_missing_overlay_key":missing_train,
                               "test_rows_missing_overlay_key":missing_test,
                               "policy":"source penalty=false only; confirmed penalty and unknown status excluded"},
        "cutoff":{"season_adaptation":"n0=4; only games available 10+ hours after kickoff and before target kickoff-90m",
                  "cutoff_groups":len(groups),"target_games":sum(map(len,groups.values()))},
        "pool":{"supporting_exact_cells":len(pool),"pool_excluded":dict(pool_excluded),
                 "event_rows":sum(map(len,pool.values())),"team_tendency_sha256":hist.manifest["sha256"]},
        "coverage":dict(support),"stage_support":dict(stage_support),
        "models":{"league":"exact-cell dropback event share",
                  "offense_only":"league counts x cutoff-safe offense ratio; normalized per cell",
                  "defense_only":"league counts x cutoff-safe defense ratio; normalized per cell",
                  "matchup":"league counts x offense ratio x defense ratio; normalized per cell"},
        "overall_multiclass":overall,"binary_event_scores":event_scores,
        "mean_predicted_event_probabilities":{
            method:{event:predicted_mix[method][event]/prediction_counts[method]
                    for event in sorted(predicted_mix[method])}
            for method in METHODS
        },
        "team_binary_event_scores":team_event_scores,
        "strength_3x3_multiclass":by_group,"strength_3x3_binary_events":binary_3x3,
        "paired_game_bootstrap":deltas,
        "limitations":[
            "This measures only the historical cell and team-outcome multiplier stage. Formation, coverage, streak, decision-label, player-outcome and QB/scramble effects are not applied in this audit.",
            "It is not the complete sampler funnel and cannot attribute the 2026 full-game sack deficit to later layers or generated state mix.",
            "Fumble target is fumble_lost per dropback. It does not measure all fumbles or fumbles lost on run plays.",
            "The local database digest differs from the database pinned by the Nov 10 audit; these results are a separately identified rebuild, not an exact reproduction.",
            "Strength groups use clean 2022-2024 EPA ranks and are descriptive. Sparse team and 3x3 cells require uncertainty-aware interpretation.",
        ],
    }
    OUT.write_text(json.dumps(result, sort_keys=True, indent=2)+"\n")
    print(json.dumps({"out":str(OUT),"coverage":result["coverage"],"overall":overall,
                      "binary":event_scores,"cutoff_groups":len(groups)},sort_keys=True))


if __name__ == "__main__":
    main()
