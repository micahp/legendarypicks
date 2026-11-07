"""Cross-season scoring-distribution analysis for SLC v2.

Tests the owner's claim: the engine cannot produce team scores below 17 or above 27
in realistic proportion. Uses the 2025 realism backtest (272 games, 30 seeds per game
per arm) against the observed 2025 NFL team-game results.

Outputs a machine-readable JSON summary plus CSV tables.
"""
import json
import os
import gzip
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

REPO = r"C:\Users\micah\OneDrive\Documents\deepseek-harness\default-workspace\slc"
B2025 = os.path.join(REPO, "docs", "research", "SLC-2025-REALISM-RESULTS-2026-11-05")
SCRATCH = r"C:\Users\micah\OneDrive\Documents\deepseek-harness\default-workspace\scratch"
OUT = os.path.join(SCRATCH, "out")
os.makedirs(OUT, exist_ok=True)

RESULT = {}

# ---------------------------------------------------------------- load
seeds = pd.read_csv(os.path.join(B2025, "seed_status.csv.gz"))
seeds["game_id"] = seeds["game_id"].astype(str)
# game id 2025_WW_AWAY_HOME
parts = seeds["game_id"].str.split("_", expand=True)
seeds["season"] = parts[0]
seeds["week"] = parts[1].astype(int)
seeds["away"] = parts[2]
seeds["home"] = parts[3]

obs = pd.read_csv(os.path.join(B2025, "observed", "observed_team_game.csv"))
obs["game_id"] = obs["game_id"].astype(str)

COMPLETE = ("complete_regulation", "complete_overtime")
seeds["completed"] = seeds["outcome_status"].isin(COMPLETE) & seeds["home_points"].notna()

RESULT["seeds_total"] = len(seeds)
RESULT["observed_team_games"] = len(obs)
RESULT["observed_games"] = obs["game_id"].nunique()

arms = ["v1", "v15", "v2"]
# observed team-game points (542 team-games across 271 games)
obs_pts = obs["points"].dropna().astype(int).to_numpy()
obs_games = (
    obs.groupby("game_id")
    .agg(home_points=("points", lambda s: s.iloc[0]))
    .reset_index()
)
# rebuild per-game observed from the two rows
og = obs[["game_id", "team", "is_home", "points", "week"]].copy()
obs_home = og[og.is_home == 1].set_index("game_id")["points"]
obs_away = og[og.is_home == 0].set_index("game_id")["points"]
obs_game = pd.DataFrame({"home_points": obs_home, "away_points": obs_away}).dropna()
RESULT["observed_games_scored"] = int(len(obs_game))


def bins(points):
    points = np.asarray(points, dtype=float)
    n = len(points)
    return {
        "n": int(n),
        "mean": round(float(points.mean()), 3),
        "sd": round(float(points.std(ddof=1)), 3),
        "p10": float(np.percentile(points, 10)),
        "p25": float(np.percentile(points, 25)),
        "p50": float(np.percentile(points, 50)),
        "p75": float(np.percentile(points, 75)),
        "p90": float(np.percentile(points, 90)),
        "lt17": round(float((points < 17).mean()), 4),
        "b17_27": round(float(((points >= 17) & (points <= 27)).mean()), 4),
        "gt27": round(float((points > 27).mean()), 4),
        "shutout": round(float((points == 0).mean()), 4),
        "le6": round(float((points <= 6).mean()), 4),
        "ge35": round(float((points >= 35).mean()), 4),
        "ge40": round(float((points >= 40).mean()), 4),
        "min": int(points.min()),
        "max": int(points.max()),
    }


def ks(a, b):
    a = np.sort(np.asarray(a, dtype=float))
    b = np.sort(np.asarray(b, dtype=float))
    grid = np.unique(np.concatenate([a, b]))
    ca = np.searchsorted(a, grid, side="right") / len(a)
    cb = np.searchsorted(b, grid, side="right") / len(b)
    return float(np.max(np.abs(ca - cb)))


# ---------------------------------------------------------------- 1. pooled team scoring
RESULT["observed_points"] = bins(obs_pts)
RESULT["arms_points"] = {}
for arm in arms:
    d = seeds[(seeds.arm == arm) & seeds.completed]
    team_pts = np.concatenate([d["home_points"].to_numpy(), d["away_points"].to_numpy()])
    b = bins(team_pts)
    b["ks_vs_observed"] = round(ks(team_pts, obs_pts), 4)
    b["completed_seeds"] = int(len(d))
    b["blocked_seeds"] = int(((seeds.arm == arm) & (~seeds.completed) & (seeds.outcome_status == "blocked")).sum())
    b["incomplete_seeds"] = int(((seeds.arm == arm) & (~seeds.completed) & (seeds.outcome_status != "blocked")).sum())
    RESULT["arms_points"][arm] = b

# ---------------------------------------------------------------- 2. game totals and margins
def game_table(arm):
    d = seeds[(seeds.arm == arm) & seeds.completed].copy()
    d["total"] = d.home_points + d.away_points
    d["margin"] = d.home_points - d.away_points
    return d


obs_game = obs_game.copy()
obs_game["total"] = obs_game.home_points + obs_game.away_points
obs_game["margin"] = obs_game.home_points - obs_game.away_points

RESULT["observed_game"] = {
    "total_mean": round(float(obs_game.total.mean()), 3),
    "total_sd": round(float(obs_game.total.std(ddof=1)), 3),
    "margin_mean_abs": round(float(obs_game.margin.abs().mean()), 3),
    "margin_sd": round(float(obs_game.margin.std(ddof=1)), 3),
    "abs_margin_sd": round(float(obs_game.margin.abs().std(ddof=1)), 3),
}
RESULT["arms_game"] = {}
for arm in arms:
    d = game_table(arm)
    RESULT["arms_game"][arm] = {
        "total_mean": round(float(d.total.mean()), 3),
        "total_sd": round(float(d.total.std(ddof=1)), 3),
        "margin_sd": round(float(d.margin.std(ddof=1)), 3),
        "abs_margin_sd": round(float(d.margin.abs().std(ddof=1)), 3),
        "tie_share": round(float((d.margin == 0).mean()), 4),
    }

# ---------------------------------------------------------------- 3. team-strength discrimination
# per (game, team) mean simulated points across seeds
disc = {}
for arm in arms:
    d = seeds[(seeds.arm == arm) & seeds.completed]
    rows = []
    for gid, g in d.groupby("game_id"):
        rows.append((gid, g.home.iloc[0], "home", g.home_points.mean()))
        rows.append((gid, g.away.iloc[0], "away", g.away_points.mean()))
    sm = pd.DataFrame(rows, columns=["game_id", "team", "side", "sim_mean"])
    obs_tg = obs[["game_id", "team", "points"]].rename(columns={"points": "obs_points"})
    m = sm.merge(obs_tg, on=["game_id", "team"], how="inner")
    # team-season means
    team_sim = m.groupby("team").sim_mean.mean()
    team_obs = m.groupby("team").obs_points.mean()
    # game totals
    gt_sim = d.groupby("game_id").apply(
        lambda x: pd.Series({"sim_total": (x.home_points + x.away_points).mean()}), include_groups=False
    )
    gt = gt_sim.join(obs_game[["total"]], how="inner")
    disc[arm] = {
        "team_games": int(len(m)),
        "corr_sim_mean_vs_observed_team_game": round(float(m.sim_mean.corr(m.obs_points)), 4),
        "sd_sim_team_game_mean": round(float(m.sim_mean.std(ddof=1)), 3),
        "sd_observed_team_game": round(float(m.obs_points.std(ddof=1)), 3),
        "team_season_corr": round(float(team_sim.corr(team_obs)), 4),
        "sd_team_season_sim": round(float(team_sim.std(ddof=1)), 3),
        "sd_team_season_observed": round(float(team_obs.std(ddof=1)), 3),
        "game_total_corr": round(float(gt.sim_total.corr(gt.total)), 4),
        "sd_game_total_sim_mean": round(float(gt.sim_total.std(ddof=1)), 3),
        "sd_game_total_observed": round(float(gt.total.std(ddof=1)), 3),
    }
    m.to_csv(os.path.join(OUT, f"disc_{arm}.csv"), index=False)
RESULT["discrimination"] = disc

# ---------------------------------------------------------------- 4. blocked-seed bias
blk = seeds[seeds.arm == "v2"].groupby("game_id").agg(
    seeds=("seed", "count"),
    completed=("completed", "sum"),
).reset_index()
blk["blocked"] = blk.seeds - blk.completed
blk["blocked_share"] = blk.blocked / blk.seeds
blk = blk.merge(obs_game.reset_index(), on="game_id", how="left")
blk = blk.dropna(subset=["total"])
blk["absdev_total"] = (blk.total - blk.total.mean()).abs()
blk["absdev_margin"] = (blk.margin - blk.margin.mean()).abs()
blk.to_csv(os.path.join(OUT, "blocked_bias_v2.csv"), index=False)
hi = blk[blk.absdev_total >= blk.absdev_total.quantile(0.8)]
lo = blk[blk.absdev_total <= blk.absdev_total.quantile(0.2)]
RESULT["blocked_bias_v2"] = {
    "total_blocked": int(blk.blocked.sum()),
    "total_seeds": int(blk.seeds.sum()),
    "blocked_share": round(float(blk.blocked.sum() / blk.seeds.sum()), 4),
    "corr_blocked_share_vs_absdev_observed_total": round(float(blk.blocked_share.corr(blk.absdev_total)), 4),
    "corr_blocked_share_vs_absdev_observed_margin": round(float(blk.blocked_share.corr(blk.absdev_margin)), 4),
    "blocked_share_most_extreme_quintile": round(float(hi.blocked.sum() / hi.seeds.sum()), 4),
    "blocked_share_least_extreme_quintile": round(float(lo.blocked.sum() / lo.seeds.sum()), 4),
    "blocker_reasons": Counter(
        seeds[(seeds.arm == "v2") & (seeds.outcome_status == "blocked")]["blocker"].fillna("none").tolist()
    ).most_common(12),
}

# ---------------------------------------------------------------- 5. mechanism tables
def readmech(name):
    p = os.path.join(B2025, name)
    return pd.read_csv(p)


RESULT["drive_half_totals"] = readmech("table_drive_half_totals.csv")[
    ["group", "metric", "observed_mean", "observed_sd", "v2_mean", "v2_bias", "v2_std_bias", "v2_mae"]
].round(4).to_dict("records")
RESULT["extremes"] = readmech("table_extremes.csv").round(4).to_dict("records")
RESULT["variability"] = readmech("table_variability.csv").round(4).to_dict("records")
RESULT["yardage"] = readmech("table_yardage.csv").round(4).to_dict("records")
RESULT["players"] = readmech("table_players.csv").round(4).to_dict("records")

# ---------------------------------------------------------------- 6. Sunday smoke slate
SUN = os.path.join(REPO, "docs", "research", "slc-sunday-smoke-2026-11-08", "smoke-table.csv")
sun = pd.read_csv(SUN)
RESULT["sunday_smoke"] = {
    "games": int(len(sun)),
    "team_scores": sorted(
        [int(v) for v in list(sun.away_points) + list(sun.home_points)]
    ),
    "all_valid_full_game": bool(sun.valid_full_game.all()),
    "team_score_bins": bins(list(sun.away_points) + list(sun.home_points)),
}

# ---------------------------------------------------------------- 7. Thursday JAX-BAL
SCORE = os.path.join(REPO, "docs", "research", "slc-scoring-review-2026-11-07")
thu = {}
for arm in arms:
    d = pd.read_csv(os.path.join(SCORE, "seed-outcomes", f"JAX-BAL-corrected-{arm}.csv"))
    comp = d[d.status.isin(["complete_regulation", "complete_overtime"])]
    thu[arm] = {
        "seeds": int(len(d)),
        "completed": int(len(comp)),
        "blocked": int((d.status == "blocked").sum()),
        "valid_full_game": int(d.valid_full_game.sum()),
        "home_points_vs_10": round(float((comp.home_points < 10).mean()), 4),
        "away_points_vs_33": round(float((comp.away_points < 33).mean()), 4),
    }
    for label, series, actual in [
        ("jax_33", comp.away_points, 33),
        ("bal_10", comp.home_points, 10),
        ("total_43", comp.away_points + comp.home_points, 43),
        ("margin_23", comp.away_points - comp.home_points, 23),
    ]:
        thu[arm][f"pct_actual_below__{label}"] = round(float((series < actual).mean()), 4)
    thu[arm]["median"] = [float(comp.away_points.median()), float(comp.home_points.median())]
    thu[arm]["mean"] = [round(float(comp.away_points.mean()), 2), round(float(comp.home_points.mean()), 2)]
RESULT["thursday_jax_bal"] = thu

with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as h:
    json.dump(RESULT, h, indent=1, default=str)

# console digest
print(json.dumps({k: RESULT[k] for k in [
    "seeds_total", "observed_team_games", "observed_games", "observed_games_scored",
    "observed_points", "arms_points", "observed_game", "arms_game",
    "discrimination", "blocked_bias_v2", "sunday_smoke", "thursday_jax_bal"]}, indent=1, default=str))
