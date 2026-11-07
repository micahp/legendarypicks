"""Low-end team scoring: share of team-games at <=3 and <=10 points, observed vs simulated.

Observed: 2025 NFL, 272 games / 544 team-games.
Simulated: 2025 realism backtest, per-seed team scores, completed seeds only.
CIs are game-clustered bootstrap, because seeds within a game and the two team-games
within a game are not independent.
"""
import json
import os

import numpy as np
import pandas as pd

REPO = r"C:\Users\micah\OneDrive\Documents\deepseek-harness\default-workspace\slc"
B = os.path.join(REPO, "docs", "research", "SLC-2025-REALISM-RESULTS-2026-11-05")
OUT = r"C:\Users\micah\OneDrive\Documents\deepseek-harness\default-workspace\scratch\out"

# ---------------- observed
obs = pd.read_csv(os.path.join(B, "observed", "observed_team_game.csv"))
obs["game_id"] = obs["game_id"].astype(str)
obs = obs[["game_id", "team", "points"]].dropna()
obs_pts = obs.points.to_numpy(int)

# ---------------- simulated
seeds = pd.read_csv(os.path.join(B, "seed_status.csv.gz"))
seeds["game_id"] = seeds["game_id"].astype(str)
seeds["completed"] = seeds["outcome_status"].isin(("complete_regulation", "complete_overtime")) & seeds[
    "home_points"
].notna()


def team_points(d):
    return np.concatenate([d.home_points.to_numpy(float), d.away_points.to_numpy(float)]).astype(int)


def boot_share(points_by_game, threshold, draws=4000, seed=20261107):
    """Game-clustered bootstrap of P(team-game points <= threshold)."""
    rng = np.random.default_rng(seed)
    # points_by_game: array (n_games, 2) of the two team scores
    rng.shuffle  # noqa
    n = len(points_by_game)
    hits = (points_by_game <= threshold).sum(axis=1).astype(float)
    share_game = hits / 2.0
    idx = rng.integers(0, n, size=(draws, n))
    samples = share_game[idx].mean(axis=1)
    return float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5))


def per_game_matrix(df, home_col, away_col):
    return df[[home_col, away_col]].to_numpy(float)


rows = []

# observed matrix
obs_m = per_game_matrix(obs[obs.team.isin([])] if False else pd.DataFrame(), "a", "b") if False else None
oh = obs[obs.team.isin(obs.groupby("game_id").apply(lambda g: g.sort_values("team").team.iloc[0]).tolist())] if False else None

# build observed 2-column matrix by game
g = obs.groupby("game_id")["points"].apply(list)
obs_games = np.array([v for v in g if len(v) == 2], dtype=float)
assert obs_games.shape[0] == 272, obs_games.shape

for label, matrix, flat in [("observed_2025", obs_games, obs_games.ravel())]:
    for thr in (3, 6, 10):
        lo, hi = boot_share(obs_games, thr)
        rows.append({
            "source": label, "threshold": f"<= {thr}",
            "n_team_games": len(flat),
            "count": int((flat <= thr).sum()),
            "share": round(float((flat <= thr).mean()), 5),
            "ci95_low": round(lo, 5), "ci95_high": round(hi, 5),
        })

for arm in ["v1", "v15", "v2"]:
    d = seeds[(seeds.arm == arm) & seeds.completed].copy()
    d["team_hit"] = ((d.home_points <= 3).astype(float) + (d.away_points <= 3).astype(float)) / 2.0
    tp_all = np.concatenate([d.home_points.to_numpy(float), d.away_points.to_numpy(float)]).astype(int)
    for thr in (3, 6, 10):
        d["hit"] = ((d.home_points <= thr).astype(float) + (d.away_points <= thr).astype(float)) / 2.0
        share_game = d.groupby("game_id")["hit"].mean().to_numpy()
        rng = np.random.default_rng(20261107)
        idx = rng.integers(0, len(share_game), size=(2000, len(share_game)))
        samples = share_game[idx].mean(axis=1)
        rows.append({
            "source": arm, "threshold": f"<= {thr}",
            "n_team_games": len(tp_all),
            "count": int((tp_all <= thr).sum()),
            "share": round(float((tp_all <= thr).mean()), 5),
            "ci95_low": round(float(np.percentile(samples, 2.5)), 5),
            "ci95_high": round(float(np.percentile(samples, 97.5)), 5),
        })

df = pd.DataFrame(rows)
df.to_csv(os.path.join(OUT, "low-end-scoring.csv"), index=False)
pd.set_option("display.width", 200)
print(df.to_string(index=False))

# exact score frequencies on the low end
print()
print("exact team score shares, 0..14")
print(f"{'pts':>3} {'observed':>10} {'v1':>9} {'v15':>9} {'v2':>9}")
for p in range(0, 15):
    o = (obs_pts == p).mean()
    cells = [f"{100*o:9.2f}"]
    for arm in ["v1", "v15", "v2"]:
        d = seeds[(seeds.arm == arm) & seeds.completed]
        tp = team_points(d)
        cells.append(f"{100*float((tp == p).mean()):9.2f}")
    print(f"{p:>3} " + " ".join(cells))

# ratio table
print()
print("simulated / observed ratio")
for thr in (3, 6, 10):
    o = df[(df.source == "observed_2025") & (df.threshold == f"<= {thr}")].share.iloc[0]
    line = f"<= {thr}: obs {100*o:.2f}%"
    for arm in ["v1", "v15", "v2"]:
        s = df[(df.source == arm) & (df.threshold == f"<= {thr}")].share.iloc[0]
        line += f" | {arm} {100*s:.2f}% ({s/o:.2f}x)"
    print(line)
