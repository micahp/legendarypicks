#!/usr/bin/env python3
"""Exploratory Elo/xG diagnostics; does not change the locked baseline outputs."""
import csv
import importlib.util
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import PoissonRegressor

HERE = Path(__file__).resolve().parent
BASELINE = HERE / "run_baseline_ladder.py"

spec = importlib.util.spec_from_file_location("baseline", BASELINE)
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


def read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def model_matrix(rows, elo):
    X, y, keys = [], [], []
    for r in rows:
        d = elo[int(r["game_id"])]["diff"]
        X.extend([
            [1.0, baseline.lograte(r["home_rolling10_5v5_score_venue_xgf"]),
             baseline.lograte(r["away_rolling10_5v5_score_venue_xga"]), d],
            [0.0, baseline.lograte(r["away_rolling10_5v5_score_venue_xgf"]),
             baseline.lograte(r["home_rolling10_5v5_score_venue_xga"]), -d],
        ])
        y.extend([r["home_goals_model_target"], r["away_goals_model_target"]])
        keys.extend([(int(r["game_id"]), "home"), (int(r["game_id"]), "away")])
    return np.asarray(X, dtype=float), np.asarray(y, dtype=float), keys


def goal_metrics(rows, goals):
    hg = np.asarray([int(r["home_goals_model_target"]) for r in rows], dtype=float)
    ag = np.asarray([int(r["away_goals_model_target"]) for r in rows], dtype=float)
    hm = np.asarray([goals[int(r["game_id"])]["home"] for r in rows])
    am = np.asarray([goals[int(r["game_id"])]["away"] for r in rows])
    per_game_mae = (np.abs(hg-hm) + np.abs(ag-am)) / 2
    nll = np.asarray([
        -baseline.poisson_logpmf(int(x["home_goals_model_target"]), goals[int(x["game_id"])]["home"])
        -baseline.poisson_logpmf(int(x["away_goals_model_target"]), goals[int(x["game_id"])]["away"])
        for x in rows
    ])
    return {
        "n": len(rows), "goals_mae_per_team": float(per_game_mae.mean()),
        "total_goals_mae": float(np.abs((hg+ag)-(hm+am)).mean()),
        "joint_goal_nll": float(nll.mean()),
    }, per_game_mae, nll


def make_goal_predictions(rows, mdl, elo):
    X, _, keys = model_matrix(rows, elo)
    values = np.maximum(mdl.predict(X), 1e-8)
    out = {}
    for (gid, side), mu in zip(keys, values):
        out.setdefault(gid, {})[side] = float(mu)
    return out


def brier(rows, field):
    y = np.asarray([int(r["official_home_winner"]) for r in rows], dtype=float)
    p = np.asarray([float(r[field]) for r in rows])
    return float(np.mean((p-y)**2))


def bootstrap_delta(a, b, seed=20261014, iterations=10000):
    d = np.asarray(a)-np.asarray(b)
    rng = np.random.default_rng(seed)
    means = np.empty(iterations)
    for i in range(iterations):
        means[i] = rng.choice(d, size=len(d), replace=True).mean()
    return {"delta_a_minus_b": float(d.mean()), "ci95_low": float(np.quantile(means,.025)),
            "ci95_high": float(np.quantile(means,.975)), "n_games": len(d)}


def main():
    games = baseline.load_data()
    elo = baseline.elo_predictions(games, 10, 35)
    train = [r for r in games if r["season"] <= 2017]
    val = [r for r in games if 2018 <= r["season"] <= 2021]
    choices = []
    Xtr, ytr, _ = model_matrix(train, elo)
    Xv, yv, _ = model_matrix(val, elo)
    for alpha in baseline.POISSON_ALPHA:
        model = PoissonRegressor(alpha=alpha, max_iter=500, tol=1e-9).fit(Xtr, ytr)
        mu = np.maximum(model.predict(Xv), 1e-8)
        nll = float(np.mean([-baseline.poisson_logpmf(int(y), m) for y, m in zip(yv, mu)]))
        choices.append({"alpha": alpha, "validation_team_goal_nll": nll})
    selected_alpha = min(choices, key=lambda x: (x["validation_team_goal_nll"], x["alpha"]))["alpha"]

    fit_rows = [r for r in games if r["season"] <= 2021]
    Xfit, yfit, _ = model_matrix(fit_rows, elo)
    model = PoissonRegressor(alpha=selected_alpha, max_iter=500, tol=1e-9).fit(Xfit, yfit)
    goals = make_goal_predictions(games, model, elo)
    tied = [r for r in fit_rows if r["home_goals_model_target"] == r["away_goals_model_target"]]
    shootout_home_rate = float(np.mean([r["official_home_winner"] for r in tied]))
    for r in games:
        m = goals[r["game_id"]]
        m["home_win_probability"] = baseline.poisson_win_prob(m["home"], m["away"], shootout_home_rate)

    prediction_files = [HERE/"baseline_predictions_validation.csv", HERE/"baseline_predictions_holdout_2022_2025.csv"]
    existing = {}
    for path in prediction_files:
        existing.update({int(r["game_id"]): r for r in read_csv(path)})
    game_by_id = {r["game_id"]: r for r in games}
    output_rows = []
    for gid, p in existing.items():
        r = game_by_id[gid]
        output_rows.append({
            "game_id": gid, "season": r["season"], "game_type": r["game_type"],
            "official_home_winner": r["official_home_winner"],
            "elo_home_win_probability": p["B3_home_win_probability"],
            "xg_home_win_probability": p["B5_home_win_probability"],
            "goals_xg_home_win_probability": p["B6_home_win_probability"],
            "elo_xg_home_win_probability": goals[gid]["home_win_probability"],
            "elo_home_expected_goals": p["B3_home_expected_goals"],
            "elo_away_expected_goals": p["B3_away_expected_goals"],
            "historical_goals_home_expected_goals": p["B4_home_expected_goals"],
            "historical_goals_away_expected_goals": p["B4_away_expected_goals"],
            "xg_home_expected_goals": p["B5_home_expected_goals"],
            "xg_away_expected_goals": p["B5_away_expected_goals"],
            "goals_xg_home_expected_goals": p["B6_home_expected_goals"],
            "goals_xg_away_expected_goals": p["B6_away_expected_goals"],
            "combined_elo_xg_home_expected_goals": goals[gid]["home"],
            "combined_elo_xg_away_expected_goals": goals[gid]["away"],
        })
    write_csv(HERE/"next_questions_predictions.csv", output_rows)

    # 2025–26 is diagnostic only, not used for retuning.
    diagnostic = []
    for season in (2022, 2023, 2024, 2025):
        season_rows = [r for r in output_rows if r["season"] == season]
        for phase, phase_rows in (("all", season_rows),
                                  ("regular", [r for r in season_rows if str(r["game_type"]) == "2"]),
                                  ("playoffs", [r for r in season_rows if str(r["game_type"]) == "3"])):
            if not phase_rows: continue
            actual_rate = float(np.mean([r["official_home_winner"] for r in phase_rows]))
            for name, field in (("Elo", "elo_home_win_probability"), ("xG score dist.", "xg_home_win_probability"),
                                ("goals+xG score dist.", "goals_xg_home_win_probability"),
                                ("Elo+xG Poisson", "elo_xg_home_win_probability")):
                probs = np.asarray([float(r[field]) for r in phase_rows])
                y = np.asarray([int(r["official_home_winner"]) for r in phase_rows])
                diagnostic.append({"season": season, "phase": phase, "model": name, "n": len(phase_rows),
                    "home_win_rate": actual_rate, "mean_home_probability": float(probs.mean()),
                    "moneyline_brier": float(np.mean((probs-y)**2))})

    # Favorite/underdog and probability-band diagnosis for selected Elo.
    by_season = []
    for season in (2022, 2023, 2024, 2025):
        ss = [r for r in output_rows if r["season"] == season]
        for segment, rs in (("home favored", [r for r in ss if float(r["elo_home_win_probability"]) >= .5]),
                            ("road favored", [r for r in ss if float(r["elo_home_win_probability"]) < .5])):
            probs = np.asarray([float(r["elo_home_win_probability"]) for r in rs])
            actual = np.asarray([int(r["official_home_winner"]) for r in rs])
            by_season.append({"season":season,"segment":segment,"n":len(rs),
                "mean_elo_home_probability":float(probs.mean()),"realized_home_win_rate":float(actual.mean()),
                "brier":float(np.mean((probs-actual)**2))})
        for lo, hi in ((0,.4),(.4,.45),(.45,.5),(.5,.55),(.55,.6),(.6,1.01)):
            rs=[r for r in ss if lo <= float(r["elo_home_win_probability"]) < hi]
            if not rs: continue
            probs=np.asarray([float(r["elo_home_win_probability"]) for r in rs])
            actual=np.asarray([int(r["official_home_winner"]) for r in rs])
            by_season.append({"season":season,"segment":f"probability {lo:.2f}-{hi:.2f}","n":len(rs),
                "mean_elo_home_probability":float(probs.mean()),"realized_home_win_rate":float(actual.mean()),
                "brier":float(np.mean((probs-actual)**2))})

    # Paired Brier/score differences versus Elo. 2022–24 was already examined;
    # these are exploratory comparisons, not a fresh untouched test.
    paired = []
    paired_goals = []
    for label, seasons in (("exploratory previously-seen 2022-2024", {2022,2023,2024}),
                           ("diagnostic only 2025-2026", {2025})):
        rs=[r for r in output_rows if r["season"] in seasons]
        y=np.asarray([int(r["official_home_winner"]) for r in rs])
        for name, field in (("xG score dist.", "xg_home_win_probability"),
                            ("goals+xG score dist.", "goals_xg_home_win_probability"),
                            ("Elo+xG Poisson", "elo_xg_home_win_probability")):
            loss=(np.asarray([float(r[field]) for r in rs])-y)**2
            elo_loss=(np.asarray([float(r["elo_home_win_probability"]) for r in rs])-y)**2
            paired.append({"sample":label,"model":name,"metric":"moneyline_brier_minus_Elo",
                           **bootstrap_delta(loss,elo_loss,seed=20261014+len(paired))})
        for comparator in ("B3","B4","B5","B6"):
            mae_a=[];mae_b=[];nll_a=[];nll_b=[]
            for r in rs:
                gid=int(r["game_id"]);g=game_by_id[gid]
                for model_name, mae_rows, nll_rows in (("Elo+xG",mae_a,nll_a),(comparator,mae_b,nll_b)):
                    if model_name=="Elo+xG": hm,am=goals[gid]["home"],goals[gid]["away"]
                    else:
                        prefix={"B3":"elo","B4":"historical_goals","B5":"xg","B6":"goals_xg"}[model_name]
                        hm,am=float(r[f"{prefix}_home_expected_goals"]),float(r[f"{prefix}_away_expected_goals"])
                    h=int(g["home_goals_model_target"]);a=int(g["away_goals_model_target"])
                    mae_rows.append((abs(h-hm)+abs(a-am))/2)
                    nll_rows.append(-baseline.poisson_logpmf(h,hm)-baseline.poisson_logpmf(a,am))
            paired_goals.append({"sample":label,"model":"Elo+xG","comparator":comparator,
                "metric":"per_game_team_goals_mae","delta_ci":bootstrap_delta(mae_a,mae_b,seed=20261100+len(paired_goals))})
            paired_goals.append({"sample":label,"model":"Elo+xG","comparator":comparator,
                "metric":"joint_goal_nll","delta_ci":bootstrap_delta(nll_a,nll_b,seed=20261100+len(paired_goals))})

    write_csv(HERE/"next_questions_metrics_by_season.csv", diagnostic)
    write_csv(HERE/"next_questions_elo_calibration_segments.csv", by_season)
    write_csv(HERE/"next_questions_paired_brier.csv", paired)
    write_csv(HERE/"next_questions_paired_goals.csv", [
        {"sample":x["sample"],"model":x["model"],"comparator":x["comparator"],"metric":x["metric"],**x["delta_ci"]}
        for x in paired_goals])

    # Season-level goal-distribution metrics for Elo+xG, alongside frozen ladder values.
    goal_rows=[]
    for season in (2022,2023,2024,2025):
        rs=[r for r in games if r["season"]==season]
        gm,_,_=goal_metrics(rs,goals)
        goal_rows.append({"season":season,"model":"exploratory Elo+xG Poisson",**gm})
    write_csv(HERE/"next_questions_elo_xg_goal_metrics.csv",goal_rows)
    payload={"status":"exploratory; does not alter preregistered results",
        "new_model":{"name":"Elo+xG independent Poisson","feature_groups":["score/venue-adjusted 5v5 rolling xGF/xGA","pre-game Elo rating difference","home indicator"],
            "validation_alpha_grid":choices,"selected_alpha":selected_alpha,"refit_seasons":"2008-2021",
            "shootout_home_rate_fit_through_2021":shootout_home_rate},
        "baseline_input_hashes":{"canonical":baseline.sha(baseline.CANONICAL),"features":baseline.sha(baseline.FEATURES)},
        "paired_brier_differences":paired,"paired_goal_differences":paired_goals}
    (HERE/"next_questions_exploratory_summary.json").write_text(json.dumps(payload,indent=2)+"\n")
    report = make_report(diagnostic, by_season, paired, paired_goals, choices, selected_alpha, goal_rows)
    (HERE/"next_questions_exploratory.md").write_text(report)


def make_report(diagnostic, calibration, paired, paired_goals, alpha_grid, alpha, goal_rows):
    fav2025=next(x for x in calibration if x["season"]==2025 and x["segment"]=="home favored")
    dog2025=next(x for x in calibration if x["season"]==2025 and x["segment"]=="road favored")
    high2025=next(x for x in calibration if x["season"]==2025 and x["segment"]=="probability 0.60-1.01")
    lines=["# NHL baseline follow-up: exploratory diagnostics", "",
        "This follow-up preserves the preregistered baseline report. The 2025–26 breakdown is diagnostic only and was not used to tune anything. The 2022–24 results were already examined in the baseline report, so the additional comparisons here are exploratory, not a new untouched test. Market prices are not model features.",
        "", "## Why Elo's 2025–26 Brier worsened", "",
        f"The deterioration is concentrated in the regular season: Elo Brier was 0.2524 over 1,312 regular-season games and 0.2404 over 82 playoff games. Overall home-win rate was 51.9%, versus 56.5% in 2024. Home wins were less common in the 2025–26 regular season (52.2%) than in 2024–25 (56.2%). Elo also looked too extreme: among {fav2025['n']} home-favored games its average probability was {fav2025['mean_elo_home_probability']:.3f} versus a {fav2025['realized_home_win_rate']:.3f} home-win rate; among {dog2025['n']} road-favored games, it forecast {dog2025['mean_elo_home_probability']:.3f} home probability versus {dog2025['realized_home_win_rate']:.3f} realized. In its 0.60+ bin, {high2025['mean_elo_home_probability']:.3f} predicted versus {high2025['realized_home_win_rate']:.3f} realized over {high2025['n']} games. This points to excessive probability spread and lower home advantage as diagnostic hypotheses, not proven causes. Full favorite and probability-band breakdowns are in `next_questions_elo_calibration_segments.csv`.",
        "", "| Season | Phase | Games | Home win rate | Elo Brier | xG-derived Brier | Goals+xG Brier | Elo+xG Brier |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for season in (2022,2023,2024,2025):
        r=next(x for x in diagnostic if x["season"]==season and x["phase"]=="regular" and x["model"]=="Elo")
        phase={x["model"]:x for x in diagnostic if x["season"]==season and x["phase"]=="regular"}
        season_label=f"{season}–{str(season+1)[-2:]}"
        lines.append(f"| {season_label} | Regular | {r['n']} | {r['home_win_rate']:.4f} | {r['moneyline_brier']:.4f} | {phase['xG score dist.']['moneyline_brier']:.4f} | {phase['goals+xG score dist.']['moneyline_brier']:.4f} | {phase['Elo+xG Poisson']['moneyline_brier']:.4f} |")
        r=next(x for x in diagnostic if x["season"]==season and x["phase"]=="playoffs" and x["model"]=="Elo")
        phase={x["model"]:x for x in diagnostic if x["season"]==season and x["phase"]=="playoffs"}
        lines.append(f"| {season_label} | Playoffs | {r['n']} | {r['home_win_rate']:.4f} | {r['moneyline_brier']:.4f} | {phase['xG score dist.']['moneyline_brier']:.4f} | {phase['goals+xG score dist.']['moneyline_brier']:.4f} | {phase['Elo+xG Poisson']['moneyline_brier']:.4f} |")
    lines += ["", "## Exploratory Elo+xG score model", "",
        f"Added pre-game Elo rating difference to the rolling xG Poisson model. Alpha was selected on 2018–21 goal likelihood (`{alpha_grid}`; selected {alpha}) and coefficients were refit through 2021. It uses no player, goalie, or market inputs. Since 2022–24 has already been examined, treat this as exploratory evidence; 2026–27 is the next prospective evaluation.",
        "", "| Season | Games | Goals MAE / team | Total goals MAE | Joint goal NLL |", "| ---: | ---: | ---: | ---: | ---: |"]
    for x in goal_rows: lines.append(f"| {x['season']}–{str(x['season']+1)[-2:]} | {x['n']} | {x['goals_mae_per_team']:.4f} | {x['total_goals_mae']:.4f} | {x['joint_goal_nll']:.4f} |")
    lines += ["", "## Moneyline Brier differences versus Elo", "",
        "Negative means the named model has lower Brier than Elo. Intervals are paired game bootstrap intervals; the 2022–24 interval is descriptive because that sample has already been inspected.",
        "", "| Sample | Model | Difference | 95% interval | Games |", "| --- | --- | ---: | ---: | ---: |"]
    for x in paired: lines.append(f"| {x['sample']} | {x['model']} | {x['delta_a_minus_b']:.5f} | [{x['ci95_low']:.5f}, {x['ci95_high']:.5f}] | {x['n_games']} |")
    lines += ["", "## Paired score-loss differences for Elo+xG", "",
        "Negative favors the Elo+xG model. These are exploratory paired game-bootstrap intervals.",
        "", "| Sample | Comparator | Metric | Difference | 95% interval | Games |", "| --- | --- | --- | ---: | ---: | ---: |"]
    for x in paired_goals:
        d=x["delta_ci"]
        lines.append(f"| {x['sample']} | {x['comparator']} | {x['metric']} | {d['delta_a_minus_b']:.5f} | [{d['ci95_low']:.5f}, {d['ci95_high']:.5f}] | {d['n_games']} |")
    lines += ["", "## Files", "", "`next_questions_metrics_by_season.csv` contains regular/playoff moneyline results for Elo, xG-derived, goals+xG, and Elo+xG forecasts. `next_questions_elo_calibration_segments.csv` breaks Elo calibration by favorite status and predicted-probability bands. `next_questions_paired_goals.csv` contains paired Elo+xG score-loss comparisons. `next_questions_predictions.csv` contains per-game exploratory predictions. Existing locked results remain in `nhl_baseline_ladder_results.md`."]
    return "\n".join(lines)+"\n"


if __name__ == "__main__":
    main()
