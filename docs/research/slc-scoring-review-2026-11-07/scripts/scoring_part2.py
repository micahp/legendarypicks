"""Part 2: tail/joint distributions, noise-corrected discrimination, and chart data."""
import json
import os

import numpy as np
import pandas as pd

REPO = r"C:\Users\micah\OneDrive\Documents\deepseek-harness\default-workspace\slc"
B2025 = os.path.join(REPO, "docs", "research", "SLC-2025-REALISM-RESULTS-2026-11-05")
OUT = r"C:\Users\micah\OneDrive\Documents\deepseek-harness\default-workspace\scratch\out"
os.makedirs(OUT, exist_ok=True)

seeds = pd.read_csv(os.path.join(B2025, "seed_status.csv.gz"))
seeds["game_id"] = seeds["game_id"].astype(str)
p = seeds["game_id"].str.split("_", expand=True)
seeds["away"], seeds["home"] = p[2], p[3]
seeds["completed"] = seeds["outcome_status"].isin(("complete_regulation", "complete_overtime")) & seeds[
    "home_points"
].notna()

obs = pd.read_csv(os.path.join(B2025, "observed", "observed_team_game.csv"))
obs["game_id"] = obs["game_id"].astype(str)
oh = obs[obs.is_home == 1].set_index("game_id")[["team", "points"]].rename(
    columns={"team": "home", "points": "home_points"}
)
oa = obs[obs.is_home == 0].set_index("game_id")[["team", "points"]].rename(
    columns={"team": "away", "points": "away_points"}
)
og = oh.join(oa, how="inner").reset_index()
og["total"] = og.home_points + og.away_points
og["margin"] = og.home_points - og.away_points
og.to_csv(os.path.join(OUT, "observed_games.csv"), index=False)

R = {}
R["observed_games"] = int(len(og))
R["observed_team_games"] = int(len(obs))


def game_bins(df):
    t = df.total.to_numpy(float)
    m = df.margin.to_numpy(float)
    hp = df.home_points.to_numpy(float)
    ap = df.away_points.to_numpy(float)
    return {
        "n": int(len(df)),
        "total_mean": round(float(t.mean()), 2),
        "total_sd": round(float(t.std(ddof=1)), 2),
        "total_lt30": round(float((t < 30).mean()), 4),
        "total_30_39": round(float(((t >= 30) & (t < 40)).mean()), 4),
        "total_40_49": round(float(((t >= 40) & (t < 50)).mean()), 4),
        "total_50_59": round(float(((t >= 50) & (t < 60)).mean()), 4),
        "total_ge60": round(float((t >= 60).mean()), 4),
        "both_lt17": round(float(((hp < 17) & (ap < 17)).mean()), 4),
        "both_gt27": round(float(((hp > 27) & (ap > 27)).mean()), 4),
        "one_lt10": round(float(((hp < 10) | (ap < 10)).mean()), 4),
        "blowout_ge21": round(float((np.abs(m) >= 21).mean()), 4),
        "abs_margin_mean": round(float(np.abs(m).mean()), 2),
        "tie": round(float((m == 0).mean()), 4),
    }


R["observed_game_bins"] = game_bins(og)
for arm in ["v1", "v15", "v2"]:
    # predictive distribution: every completed seed is one simulated game
    d = seeds[(seeds.arm == arm) & seeds.completed][["game_id", "home_points", "away_points"]].copy()
    d["total"] = d.home_points + d.away_points
    d["margin"] = d.home_points - d.away_points
    R[f"{arm}_game_bins"] = game_bins(d)
    # expectations: per-game mean across seeds (used only for discrimination, not predictive spread)
    gt = d.groupby("game_id").agg(home_points=("home_points", "mean"), away_points=("away_points", "mean"))
    gt["total"] = gt.home_points + gt.away_points
    gt["margin"] = gt.home_points - gt.away_points
    gt.to_csv(os.path.join(OUT, f"games_{arm}.csv"))

# ---- noise-corrected discrimination
# observed team-season means contain sampling noise; subtract it to estimate true team strength spread
obs_sd_game = float(obs.points.std(ddof=1))
games_per_team = obs.groupby("team").game_id.nunique().mean()
obs_team_mean = obs.groupby("team").points.mean()
obs_team_sd = float(obs_team_mean.std(ddof=1))
noise_var = obs_sd_game**2 / games_per_team
true_var = obs_team_sd**2 - noise_var
R["team_strength"] = {
    "obs_team_game_sd": round(obs_sd_game, 3),
    "games_per_team": round(float(games_per_team), 2),
    "obs_team_season_mean_sd": round(obs_team_sd, 3),
    "sampling_noise_sd_of_team_mean": round(float(np.sqrt(noise_var)), 3),
    "estimated_true_team_strength_sd": round(float(np.sqrt(max(true_var, 0))), 3),
    "observed_team_means": {k: round(float(v), 2) for k, v in obs_team_mean.sort_values().items()},
}
for arm in ["v1", "v15", "v2"]:
    d = seeds[(seeds.arm == arm) & seeds.completed]
    rows = []
    for gid, g in d.groupby("game_id"):
        rows.append((gid, g.home.iloc[0], g.home_points.mean()))
        rows.append((gid, g.away.iloc[0], g.away_points.mean()))
    sm = pd.DataFrame(rows, columns=["game_id", "team", "sim_mean"])
    tm = sm.groupby("team").sim_mean.mean()
    gt = d.assign(total=d.home_points + d.away_points).groupby("game_id").total.mean()
    tot = gt.to_frame("sim_total").join(og.set_index("game_id")[["total"]], how="inner")
    m = sm.merge(
        obs[["game_id", "team", "points"]].rename(columns={"points": "obs"}), on=["game_id", "team"]
    )
    R[f"{arm}_discrimination"] = {
        "team_season_mean_sd_sim": round(float(tm.std(ddof=1)), 3),
        "team_season_mean_sd_observed_raw": round(obs_team_sd, 3),
        "sim_over_true_ratio": round(float(tm.std(ddof=1) / np.sqrt(max(true_var, 0))), 3),
        "team_season_corr": round(float(tm.corr(obs_team_mean)), 4),
        "team_game_corr": round(float(m.sim_mean.corr(m.obs)), 4),
        "team_game_r2": round(float(m.sim_mean.corr(m.obs) ** 2), 4),
        "sd_sim_team_game_expectation": round(float(m.sim_mean.std(ddof=1)), 3),
        "sd_observed_team_game": round(float(m.obs.std(ddof=1)), 3),
        "game_total_corr": round(float(tot.sim_total.corr(tot.total)), 4),
        "sd_sim_game_total_expectation": round(float(tot.sim_total.std(ddof=1)), 3),
        "sd_observed_game_total": round(float(tot.total.std(ddof=1)), 3),
        "sim_team_means": {k: round(float(v), 2) for k, v in tm.sort_values().items()},
    }
    tm.to_csv(os.path.join(OUT, f"team_strength_{arm}.csv"))

# ---- compensating-error ratios
dth = pd.read_csv(os.path.join(B2025, "table_drive_half_totals.csv")).set_index("metric")
obs_ppd = float(dth.loc["points_per_drive", "observed_mean"])
sim_ppd = float(dth.loc["points_per_drive", "v2_mean"])
obs_ypd = float(dth.loc["yards_per_drive", "observed_mean"])
sim_ypd = float(dth.loc["yards_per_drive", "v2_mean"])
R["compensating_errors"] = {
    "yards_per_point_observed": round(obs_ypd / obs_ppd, 2),
    "yards_per_point_sim": round(sim_ypd / sim_ppd, 2),
    "yards_per_point_inflation": round((sim_ypd / sim_ppd) / (obs_ypd / obs_ppd) - 1, 4),
    "plays_per_drive_observed": round(float(dth.loc["plays_per_drive", "observed_mean"]), 3),
    "plays_per_drive_sim": round(float(dth.loc["plays_per_drive", "v2_mean"]), 3),
    "yards_per_play_observed": round(obs_ypd / float(dth.loc["plays_per_drive", "observed_mean"]), 3),
    "yards_per_play_sim": round(sim_ypd / float(dth.loc["plays_per_drive", "v2_mean"]), 3),
    "points_per_play_observed": round(obs_ppd / float(dth.loc["plays_per_drive", "observed_mean"]), 4),
    "points_per_play_sim": round(sim_ppd / float(dth.loc["plays_per_drive", "v2_mean"]), 4),
}

# ---- chart data: team score frequency 0..55
def freq(points, hi=56):
    c = np.bincount(np.clip(np.asarray(points, int), 0, hi - 1), minlength=hi)
    return c / c.sum()


charts = {"observed": freq(obs.points)}
for arm in ["v1", "v15", "v2"]:
    d = seeds[(seeds.arm == arm) & seeds.completed]
    charts[arm] = freq(np.concatenate([d.home_points, d.away_points]))
charts = pd.DataFrame(charts)
charts.index.name = "points"
charts.to_csv(os.path.join(OUT, "team_score_freq.csv"))

with open(os.path.join(OUT, "summary2.json"), "w", encoding="utf-8") as h:
    json.dump(R, h, indent=1, default=str)

print(json.dumps(R, indent=1, default=str)[:6000])
