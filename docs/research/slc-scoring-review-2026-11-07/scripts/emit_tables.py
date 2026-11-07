"""Emit the review tables as CSVs into the repo bundle, and copy the workbook and figure there."""
import json
import os
import shutil

import pandas as pd

SCRATCH = r"C:\Users\micah\OneDrive\Documents\deepseek-harness\default-workspace\scratch"
REPO = r"C:\Users\micah\OneDrive\Documents\deepseek-harness\default-workspace\slc"
DEST = os.path.join(REPO, "docs", "research", "slc-scoring-review-2026-11-07")
TAB = os.path.join(DEST, "scoring-tables")
os.makedirs(TAB, exist_ok=True)

r1 = json.load(open(os.path.join(SCRATCH, "out", "summary.json")))
r2 = json.load(open(os.path.join(SCRATCH, "out", "summary2.json")))

# 1. score bins, all arms vs observed
rows = []
for m in ["lt17", "b17_27", "gt27", "shutout", "le6", "ge35", "ge40", "min", "max", "p10", "p25", "p50", "p75", "p90", "mean", "sd"]:
    rows.append({"measure": m, "observed": r1["observed_points"][m], "v1": r1["arms_points"]["v1"][m],
                 "v15": r1["arms_points"]["v15"][m], "v2": r1["arms_points"]["v2"][m]})
pd.DataFrame(rows).to_csv(os.path.join(TAB, "team-score-bins.csv"), index=False)

# 2. team strength
ts = pd.DataFrame({
    "team": list(r2["team_strength"]["observed_team_means"].keys()),
}).set_index("team")
ts["observed_season_mean"] = pd.Series(r2["team_strength"]["observed_team_means"])
ts["v2_simulated_season_mean"] = pd.Series(r2["v2_discrimination"]["sim_team_means"])
ts["v1_simulated_season_mean"] = pd.Series(r2["v1_discrimination"]["sim_team_means"])
ts["v15_simulated_season_mean"] = pd.Series(r2["v15_discrimination"]["sim_team_means"])
ts = ts.sort_values("observed_season_mean")
ts.to_csv(os.path.join(TAB, "team-strength.csv"))
summary = {
    "observed_team_season_mean_sd_raw": r2["team_strength"]["obs_team_season_mean_sd"],
    "observed_sampling_noise_sd": r2["team_strength"]["sampling_noise_sd_of_team_mean"],
    "estimated_true_team_strength_sd": r2["team_strength"]["estimated_true_team_strength_sd"],
    "v1_sim_sd": r2["v1_discrimination"]["team_season_mean_sd_sim"],
    "v15_sim_sd": r2["v15_discrimination"]["team_season_mean_sd_sim"],
    "v2_sim_sd": r2["v2_discrimination"]["team_season_mean_sd_sim"],
    "v1_share_of_true": r2["v1_discrimination"]["sim_over_true_ratio"],
    "v15_share_of_true": r2["v15_discrimination"]["sim_over_true_ratio"],
    "v2_share_of_true": r2["v2_discrimination"]["sim_over_true_ratio"],
    "observed_range": round(ts.observed_season_mean.max() - ts.observed_season_mean.min(), 2),
    "v2_range": round(ts.v2_simulated_season_mean.max() - ts.v2_simulated_season_mean.min(), 2),
    "v2_team_season_corr": r2["v2_discrimination"]["team_season_corr"],
    "v2_team_game_corr": r2["v2_discrimination"]["team_game_corr"],
    "v2_team_game_r2": r2["v2_discrimination"]["team_game_r2"],
}
pd.Series(summary).to_csv(os.path.join(TAB, "team-strength-summary.csv"), header=["value"])

# 3. game-level tails
GB = {k.replace("_game_bins", ""): v for k, v in r2.items() if k.endswith("_game_bins")}
grows = []
for key in ["n", "total_mean", "total_sd", "total_lt30", "total_30_39", "total_40_49", "total_50_59", "total_ge60",
            "both_lt17", "both_gt27", "one_lt10", "blowout_ge21", "abs_margin_mean", "tie"]:
    grows.append({"measure": key, "observed": GB["observed"][key], "v1": GB["v1"][key],
                  "v15": GB["v15"][key], "v2": GB["v2"][key]})
pd.DataFrame(grows).to_csv(os.path.join(TAB, "game-tails.csv"), index=False)

# 4. mechanism
mech = pd.DataFrame(r1["drive_half_totals"])
mech.to_csv(os.path.join(TAB, "mechanism-observed-vs-arms.csv"), index=False)
pd.DataFrame(r1["extremes"]).to_csv(os.path.join(TAB, "extremes.csv"), index=False)
pd.DataFrame(r1["variability"]).to_csv(os.path.join(TAB, "variability.csv"), index=False)
pd.Series({**r2["compensating_errors"]}).to_csv(os.path.join(TAB, "efficiency-ratios.csv"), header=["value"])

# 5. blocked bias
blk = pd.read_csv(os.path.join(SCRATCH, "out", "blocked_bias_v2_fixed.csv"))
blk.to_csv(os.path.join(TAB, "blocked-bias-per-game-v2.csv"), index=False)

# copy the workbook and the figure into the bundle
shutil.copy(os.path.join(SCRATCH, "slc-scoring-distribution-analysis.xlsx"),
            os.path.join(DEST, "slc-scoring-distribution-analysis.xlsx"))
shutil.copy(os.path.join(SCRATCH, "scoring_compression.png"),
            os.path.join(DEST, "scoring_compression.png"))

print("tables written:")
for f in sorted(os.listdir(TAB)):
    print("  ", f, os.path.getsize(os.path.join(TAB, f)))
print("bundle:", DEST)
for f in sorted(os.listdir(DEST)):
    print("  ", f)
