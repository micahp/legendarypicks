#!/usr/bin/env python3
"""score_realism.py -- realism of V1, V1.5 and V2 against observed 2025, on the same scored games.

Development-exposed: 2025 informed play-call development, so every conclusion here is a 2025 retrospective result.
This is not a winner-prediction scorer: no game's winner or margin is scored. The unit is the team-game. A simulated
team-game is the mean over that arm's completed seeds (complete_game true, including overtime ties); blocked and
simulation_error seeds are excluded and counted in summary.json. The observed value is the 2025 team-game.

Evaluations:
  drive, half and season totals   game-level absolute error and season bias of each simulated team-game mean
  players                         team opportunities, named-player allocation (top carrier, top target, top passer)
                                  and offensive snaps. Snap metrics exist for V2 only: V1 and V1.5 exports carry
                                  lineup = null, so their snap counts are reported as not exported, not as zero.
  yardage                         pooled outcome shares of run and pass plays, by yardage bucket
  variability and calibration     pooled season distributions, leave-one-game-out observed baselines, and PIT
                                  calibration of each simulated seed set
  family summary                  per-arm aggregates, with paired game-clustered differences between arms
Uncertainty: the games are the resampling unit (2,000 draws). Arm comparisons are paired by game.

Usage: python3 score_realism.py --metrics DIR --observed DIR --verify DIR --out DIR
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

ARMS = ["v1", "v15", "v2"]
DRIVE = ["drives", "plays_per_drive", "yards_per_drive", "points_per_drive", "scoring_drive_rate",
         "three_and_outs", "punts", "turnovers", "turnovers_on_downs", "touchdowns", "fg_attempts", "fg_made"]
TOTAL = ["scrimmage_plays", "scrimmage_yards", "points", "run_plays", "pass_plays", "run_share_total"]
HALF = ["plays_h1", "plays_h2", "drives_h1", "drives_h2", "points_h1", "points_h2", "touchdowns_h1",
        "touchdowns_h2", "run_share_h1", "run_share_h2"]
VARIABILITY = ["points", "scrimmage_yards", "scrimmage_plays", "turnovers", "touchdowns", "drives",
               "three_and_outs", "run_share_total"]
PLAYER_LABELS = {"carries": "team_carries", "targets": "team_targets", "receptions": "team_receptions",
                 "pass_att": "team_pass_att", "team_offense_snaps": "team_offense_snaps",
                 "rb1_share": "rb1_share_of_carries", "rb2_share": "rb2_share_of_carries",
                 "wr1_share": "wr1_share_of_targets", "wr2_share": "wr2_share_of_targets",
                 "rb1_snap_share": "rb1_snap_share"}
SNAP_METRICS = ("team_offense_snaps", "rb1_snap_share")
PLAYER_CORE = ["team_carries", "team_targets", "team_receptions", "team_pass_att", "rb1_share_of_carries",
               "rb2_share_of_carries", "wr1_share_of_targets", "wr2_share_of_targets"]
BUCKETS = ["neg", "zero", "b1_3", "b4_9", "b10_19", "b20_39", "b40p"]
EXTREMES = {"points_ge_35": ("points", 35, "ge"), "points_le_6": ("points", 6, "le"),
            "scrimmage_yards_ge_500": ("scrimmage_yards", 500, "ge"),
            "scrimmage_yards_le_200": ("scrimmage_yards", 200, "le")}
DRAWS = 2000
RNG_SEED = 2026
REQUESTED_GAMES = 272


def derive(t):
    """Metrics per row. The same definitions apply to simulated seeds and to observed team-games."""
    d = t["drives"].where(t["drives"] > 0)
    o = pd.DataFrame(index=t.index)
    for col in ["drives", "scrimmage_plays", "scrimmage_yards", "points", "points_h1", "touchdowns", "touchdowns_h1",
                "touchdowns_h2", "fg_attempts", "fg_made", "punts", "three_and_outs", "turnovers",
                "turnovers_on_downs", "scoring_drives", "plays_h1", "plays_h2", "drives_h1", "drives_h2",
                "run_plays", "pass_plays"]:
        o[col] = t[col]
    o["points_h2"] = t["points"] - t["points_h1"]
    o["plays_per_drive"] = t["scrimmage_plays"] / d
    o["yards_per_drive"] = t["scrimmage_yards"] / d
    o["points_per_drive"] = t["points"] / d
    o["scoring_drive_rate"] = t["scoring_drives"] / d
    o["run_share_total"] = t["run_plays"] / (t["run_plays"] + t["pass_plays"])
    o["run_share_h1"] = t["run_h1"] / (t["run_h1"] + t["pass_h1"])
    o["run_share_h2"] = t["run_h2"] / (t["run_h2"] + t["pass_h2"])
    return o


def load(metrics_dir, observed_dir, verify_dir):
    sim = pd.read_csv(os.path.join(metrics_dir, "team_seed.csv.gz"))
    sim["points"] = sim.points_h1 + sim.points_h2 + sim.points_ot
    sim = sim[sim.complete_game == 1].reset_index(drop=True)
    sim_player = pd.read_csv(os.path.join(metrics_dir, "player_seed.csv.gz"))
    sim_player = sim_player[sim_player.complete_game == 1].reset_index(drop=True)
    obs = pd.read_csv(os.path.join(observed_dir, "observed_team_game.csv"))
    obs_player = pd.read_csv(os.path.join(observed_dir, "observed_player_game.csv"))
    status = pd.read_csv(os.path.join(verify_dir, "seed_status.csv"))
    return sim, obs, sim_player, obs_player, status


def restrict_to_common(sim, sim_player, obs, obs_player):
    """Keep the team-games that every arm completed at least one seed for; return what was dropped.

    A team-game with no completed seed in some arm has no simulated mean in that arm, so it cannot be compared
    across arms. Dropping it from all arms keeps the arms paired. Each dropped team-game is listed in the summary.
    """
    obs_keys = set(zip(obs.game_id, obs.team))
    common = set(obs_keys)
    for arm in ARMS:
        common &= set(zip(sim[sim.arm == arm].game_id, sim[sim.arm == arm].team))
    dropped = sorted(obs_keys - common)

    def keep(df):
        return df[[k in common for k in zip(df.game_id, df.team)]].reset_index(drop=True)

    return keep(sim), keep(sim_player), keep(obs), keep(obs_player), dropped


def per_game_mean(values, gi, n_games):
    sums = np.bincount(gi, weights=values, minlength=n_games)
    counts = np.bincount(gi, minlength=n_games)
    return sums / np.maximum(counts, 1)


def bootstrap_mean(values, rng):
    """Mean across games and a 95% interval from resampling games with replacement."""
    values = np.asarray(values, dtype=float)
    n = len(values)
    draws = np.array([values[rng.integers(0, n, n)].mean() for _ in range(DRAWS)])
    return values.mean(), np.percentile(draws, 2.5), np.percentile(draws, 97.5)


def sim_team_games(sim):
    """Mean over completed seeds for each arm and team-game, derived with the same definitions as the observed side."""
    d = derive(sim)
    d[["arm", "game_id", "team"]] = sim[["arm", "game_id", "team"]].values
    seeds = sim.groupby(["arm", "game_id", "team"]).size().rename("seeds").reset_index()
    means = d.groupby(["arm", "game_id", "team"]).mean().reset_index()
    return means.merge(seeds, on=["arm", "game_id", "team"])


def observed_team_games(obs):
    d = derive(obs)
    d[["game_id", "team", "week"]] = obs[["game_id", "team", "week"]].values
    return d


def metric_table(metrics, sim_tg, obs_tg, games, rng, group, norm_store):
    """Season bias, game-level MAE and paired game-clustered differences in MAE, one row per metric.

    norm_store[metric][arm] receives each game's MAE divided by the observed SD of that metric, for family summaries.
    """
    gidx = {g: i for i, g in enumerate(games)}
    n = len(games)
    obs_tg = obs_tg.assign(gi=obs_tg.game_id.map(gidx))
    rows = []
    for m in metrics:
        obs_sd = float(obs_tg[m].std(ddof=1))
        row = {"group": group, "metric": m, "observed_mean": float(obs_tg[m].mean()), "observed_sd": obs_sd}
        err_by_arm = {}
        for arm in ARMS:
            s = sim_tg[sim_tg.arm == arm].merge(obs_tg[["game_id", "team", "gi", m]].rename(columns={m: "obs"}),
                                                 on=["game_id", "team"])
            if len(s) != len(obs_tg):
                raise SystemExit("%s %s: %d matched team-games" % (arm, m, len(s)))
            bias = s[m].values - s["obs"].values
            err = np.abs(bias)
            gi = s.gi.values.astype(int)
            err_by_arm[arm] = per_game_mean(err, gi, n)
            norm_store.setdefault(m, {})[arm] = err_by_arm[arm] / obs_sd
            row[arm + "_mean"] = float(s[m].mean())
            row[arm + "_bias"] = float(bias.mean())
            row[arm + "_std_bias"] = float(bias.mean() / obs_sd) if obs_sd else np.nan
            row[arm + "_mae"] = float(err.mean())
            _, lo, hi = bootstrap_mean(per_game_mean(bias, gi, n), rng)
            row[arm + "_bias_ci_low"], row[arm + "_bias_ci_high"] = lo, hi
        for a, b in (("v15", "v1"), ("v2", "v15"), ("v2", "v1")):
            # mean over games of (error of a - error of b): negative means a is closer to the observed value
            point, lo, hi = bootstrap_mean(err_by_arm[a] - err_by_arm[b], rng)
            row["mae_%s_minus_%s" % (a, b)] = point
            row["mae_%s_minus_%s_ci_low" % (a, b)] = lo
            row["mae_%s_minus_%s_ci_high" % (a, b)] = hi
        rows.append(row)
    return pd.DataFrame(rows)


def player_block(sim_player, obs_player, sim_team, obs_team, games, rng):
    """Team opportunities, named-player allocation and offensive snaps, per arm and observed.

    Team offensive snaps come from the team tables: the simulator's lineup team_snaps for the seed, and the largest
    offensive snap count in the team-game for the observed side (all offensive players, linemen included).
    """
    gidx = {g: i for i, g in enumerate(games)}
    n = len(games)
    sim_snaps = sim_team.set_index(["arm", "game_id", "seed", "team"]).team_snaps.to_dict()
    obs_snaps = obs_team.set_index(["game_id", "team"]).team_snaps.to_dict()

    def team_summary(df, keys, snaps_map):
        out = []
        for key, grp in df.groupby(keys):
            key = key if isinstance(key, tuple) else (key,)
            rec = dict(zip(keys, key))
            for col in ("carries", "targets", "receptions", "pass_att"):
                rec[col] = float(grp[col].sum())
            snaps = snaps_map.get(tuple(rec[k] for k in keys), np.nan)
            rec["team_offense_snaps"] = float(snaps) if pd.notna(snaps) else np.nan

            def ranked(col, rank):
                if grp[col].sum() <= 0:
                    return None
                ordered = grp.sort_values([col, "gsis_id"], ascending=[False, True])
                return ordered.iloc[rank] if len(ordered) > rank else None

            c, t, p = ranked("carries", 0), ranked("targets", 0), ranked("pass_att", 0)
            c2, t2 = ranked("carries", 1), ranked("targets", 1)
            rec["rb1_share"] = c.carries / rec["carries"] if c is not None else np.nan
            rec["rb2_share"] = c2.carries / rec["carries"] if c2 is not None else np.nan
            rec["wr1_share"] = t.targets / rec["targets"] if t is not None else np.nan
            rec["wr2_share"] = t2.targets / rec["targets"] if t2 is not None else np.nan
            rec["rb1_snap_share"] = (c.snaps / rec["team_offense_snaps"]
                                     if c is not None and pd.notna(rec["team_offense_snaps"])
                                     and rec["team_offense_snaps"] > 0 else np.nan)
            rec["rb1_gsis"] = c.gsis_id if c is not None else None
            rec["wr1_gsis"] = t.gsis_id if t is not None else None
            rec["qb_gsis"] = p.gsis_id if p is not None else None
            out.append(rec)
        return pd.DataFrame(out)

    obs_sum = team_summary(obs_player, ["game_id", "team"], obs_snaps)
    sim_seed = team_summary(sim_player, ["arm", "game_id", "seed", "team"], sim_snaps)
    obs_idx = obs_sum.set_index(["game_id", "team"])
    sim_means = sim_seed.groupby(["arm", "game_id", "team"])[list(PLAYER_LABELS)].mean()

    rows, identity = [], []
    for arm in ARMS:
        sm = sim_means.loc[arm]
        exported = bool(sim_seed[sim_seed.arm == arm].team_offense_snaps.notna().any())
        for col, label in PLAYER_LABELS.items():
            if col in SNAP_METRICS and not exported:
                # V1 and V1.5 exports carry lineup = null: their snap counts are absent, not zero
                rows.append({"arm": arm, "metric": label, "observed_mean": float(obs_idx[col].mean()),
                             "sim_mean": np.nan, "bias": np.nan, "std_bias": np.nan, "bias_ci_low": np.nan,
                             "bias_ci_high": np.nan, "mae": np.nan, "note": "not exported by this arm"})
                continue
            joined = pd.concat([sm[col].rename("sim"), obs_idx[col].rename("obs")], axis=1).dropna()
            if len(joined) != len(obs_idx):
                raise SystemExit("players %s %s: %d of %d team-games matched" % (arm, col, len(joined), len(obs_idx)))
            gi = np.array([gidx[g] for g, _ in joined.index])
            bias = (joined.sim - joined.obs).values
            obs_sd = float(joined.obs.std(ddof=1))
            _, lo, hi = bootstrap_mean(per_game_mean(bias, gi, n), rng)
            rows.append({"arm": arm, "metric": label, "observed_mean": float(joined.obs.mean()),
                         "sim_mean": float(joined.sim.mean()), "bias": float(bias.mean()),
                         "std_bias": float(bias.mean() / obs_sd) if obs_sd else np.nan,
                         "bias_ci_low": lo, "bias_ci_high": hi, "mae": float(np.abs(bias).mean()), "note": ""})
        for (game, team), grp in sim_seed[sim_seed.arm == arm].groupby(["game_id", "team"]):
            o = obs_idx.loc[(game, team)]
            identity.append({"arm": arm, "game_id": game, "team": team,
                             "rb1": float((grp.rb1_gsis == o.rb1_gsis).mean()),
                             "wr1": float((grp.wr1_gsis == o.wr1_gsis).mean()),
                             "qb": float((grp.qb_gsis == o.qb_gsis).mean())})
    identity = pd.DataFrame(identity)
    for key, label in (("rb1", "rb1_top_carrier_identity_match"), ("wr1", "wr1_top_target_identity_match"),
                       ("qb", "qb_top_passer_identity_match")):
        for arm in ARMS:
            vals = identity[identity.arm == arm][key].values
            rows.append({"arm": arm, "metric": label, "observed_mean": np.nan, "sim_mean": float(vals.mean()),
                         "bias": np.nan, "std_bias": np.nan, "bias_ci_low": np.nan, "bias_ci_high": np.nan,
                         "mae": np.nan, "note": "share of seeds whose top player is the observed top player"})
    return pd.DataFrame(rows)


def yardage_block(sim, obs, games, rng):
    gidx = {g: i for i, g in enumerate(games)}
    rows = []
    for kind in ("run", "pass"):
        cols = [kind + "_" + b for b in BUCKETS]
        obs_counts = np.zeros((len(games), len(BUCKETS)))
        for game, grp in obs.groupby("game_id"):
            obs_counts[gidx[game]] = grp[cols].values.sum(axis=0)
        arm_counts = {}
        for arm in ARMS:
            counts = np.zeros((len(games), len(BUCKETS)))
            for game, grp in sim[sim.arm == arm].groupby("game_id"):
                counts[gidx[game]] = grp[cols].values.sum(axis=0)
            arm_counts[arm] = counts
        draws = {}
        for name, counts in [("obs", obs_counts)] + [(arm, arm_counts[arm]) for arm in ARMS]:
            d = np.empty((DRAWS, len(BUCKETS)))
            for k in range(DRAWS):
                c = counts[rng.integers(0, len(games), len(games))].sum(axis=0)
                d[k] = c / c.sum()
            draws[name] = d
        obs_share = obs_counts.sum(axis=0) / obs_counts.sum()
        for j, b in enumerate(BUCKETS):
            row = {"play_type": kind, "bucket": b, "observed_share": float(obs_share[j]),
                   "observed_ci_low": float(np.percentile(draws["obs"][:, j], 2.5)),
                   "observed_ci_high": float(np.percentile(draws["obs"][:, j], 97.5))}
            for arm in ARMS:
                share = arm_counts[arm].sum(axis=0) / arm_counts[arm].sum()
                row[arm + "_share"] = float(share[j])
                row[arm + "_ci_low"] = float(np.percentile(draws[arm][:, j], 2.5))
                row[arm + "_ci_high"] = float(np.percentile(draws[arm][:, j], 97.5))
            rows.append(row)
    return pd.DataFrame(rows)


def ks_distance(a, b):
    a, b = np.sort(a), np.sort(b)
    grid = np.concatenate([a, b])
    fa = np.searchsorted(a, grid, side="right") / len(a)
    fb = np.searchsorted(b, grid, side="right") / len(b)
    return float(np.max(np.abs(fa - fb)))


def variability_block(sim, obs, games):
    """Pooled season distributions, leave-one-game-out observed baselines, and calibration of each seed set."""
    obs_d = observed_team_games(obs)
    sim_d = derive(sim)
    sim_d[["arm", "game_id", "team"]] = sim[["arm", "game_id", "team"]].values
    games_of_obs = obs.game_id.values
    teams_of_obs = obs.team.values
    dist_rows, cal_rows = [], []
    for m in VARIABILITY:
        ov = obs_d[m].values
        total, total_sq = ov.sum(), (ov ** 2).sum()
        game_sum = obs_d.groupby(games_of_obs)[m].transform("sum").values
        game_sq = (obs_d[m] ** 2).groupby(games_of_obs).transform("sum").values
        game_n = obs_d.groupby(games_of_obs)[m].transform("size").values
        n_other = len(ov) - game_n
        league_mean = (total - game_sum) / n_other
        league_var = ((total_sq - game_sq) - n_other * league_mean ** 2) / (n_other - 1)
        league_sd = np.sqrt(league_var)
        team_mean = np.empty(len(ov))
        team_sd = np.empty(len(ov))
        for i in range(len(ov)):
            same_team = (teams_of_obs == teams_of_obs[i]) & (games_of_obs != games_of_obs[i])
            others = ov[same_team]
            team_mean[i] = others.mean()
            team_sd[i] = others.std(ddof=1)
        naive_mae = float(np.mean(np.abs(ov - league_mean)))
        for arm in ARMS:
            arm_sim = sim_d[sim_d.arm == arm]
            sv = arm_sim[m].values
            dist_rows.append({"metric": m, "arm": arm, "observed_pooled_mean": float(ov.mean()),
                              "sim_pooled_mean": float(sv.mean()), "observed_sd": float(ov.std(ddof=1)),
                              "sim_pooled_sd": float(sv.std(ddof=1)), "ks_distance": ks_distance(sv, ov),
                              "naive_league_loo_mae": naive_mae,
                              **{"observed_p%d" % q: float(np.percentile(ov, q)) for q in (10, 25, 50, 75, 90)},
                              **{"sim_p%d" % q: float(np.percentile(sv, q)) for q in (10, 25, 50, 75, 90)}})
            grouped = arm_sim.groupby(["game_id", "team"])[m]
            pit = np.empty(len(ov))
            cover = np.empty(len(ov))
            sim_mean = np.empty(len(ov))
            sim_sd = np.empty(len(ov))
            for i, (g, t) in enumerate(zip(games_of_obs, teams_of_obs)):
                vals = grouped.get_group((g, t)).values
                pit[i] = (vals < ov[i]).mean() + 0.5 * (vals == ov[i]).mean()
                cover[i] = float(np.percentile(vals, 10) <= ov[i] <= np.percentile(vals, 90))
                sim_mean[i] = vals.mean()
                sim_sd[i] = vals.std(ddof=1)
            cal_rows.append({"metric": m, "arm": arm, "pit_mean": float(pit.mean()),
                             "pit_deciles": "|".join(str(int(c)) for c in np.histogram(pit, bins=10, range=(0, 1))[0]),
                             "p10_p90_coverage": float(cover.mean()),
                             "league_loo_bias_in_sd": float(np.mean((sim_mean - league_mean) / league_sd)),
                             "team_loo_bias_in_sd": float(np.mean((sim_mean - team_mean) / team_sd)),
                             "sim_sd_over_league_loo_sd": float(np.mean(sim_sd / league_sd)),
                             "sim_sd_over_team_loo_sd": float(np.mean(sim_sd / team_sd))})
    extremes = []
    for name, (m, thr, op) in EXTREMES.items():
        test = (lambda x: x >= thr) if op == "ge" else (lambda x: x <= thr)
        for arm in ARMS:
            sv = sim_d[sim_d.arm == arm][m].values
            extremes.append({"event": name, "arm": arm, "observed_share": float(test(obs_d[m].values).mean()),
                             "sim_share": float(test(sv).mean())})
    return pd.DataFrame(dist_rows), pd.DataFrame(cal_rows), pd.DataFrame(extremes)


def family_summary(table, dist, cal, yardage, extremes, players, norm_store, games, rng):
    """One row per arm and family, with paired game-clustered differences in normalized game-level error."""
    rows = []
    gi_n = len(games)
    fam = {"drive_half_totals": DRIVE + TOTAL + HALF}
    for arm in ARMS:
        vals = [table[(table.metric == m)][arm + "_std_bias"].abs().values[0] for m in fam["drive_half_totals"]]
        norm = [np.mean(norm_store[m][arm]) for m in fam["drive_half_totals"]]
        rows.append({"family": "drive_half_totals", "arm": arm, "n_metrics": len(vals),
                     "mean_abs_std_bias": float(np.mean(vals)), "mean_normalized_mae": float(np.mean(norm))})
    for arm in ARMS:
        d = dist[dist.arm == arm]
        c = cal[cal.arm == arm]
        rows.append({"family": "variability", "arm": arm, "n_metrics": len(d),
                     "mean_abs_std_bias": float(c.league_loo_bias_in_sd.abs().mean()),
                     "mean_normalized_mae": float(d.ks_distance.mean()),
                     "mean_pit_deviation": float((c.pit_mean - 0.5).abs().mean()),
                     "mean_coverage_deviation": float((c.p10_p90_coverage - 0.8).abs().mean())})
    for arm in ARMS:
        y = yardage[yardage.play_type.isin(["run", "pass"])]
        tvd = []
        for kind in ("run", "pass"):
            sub = y[y.play_type == kind]
            tvd.append(0.5 * (sub[arm + "_share"] - sub.observed_share).abs().sum())
        rows.append({"family": "yardage_buckets", "arm": arm, "n_metrics": 2,
                     "mean_normalized_mae": float(np.mean(tvd)),
                     "note": "total variation distance between simulated and observed bucket shares, run and pass"})
    for arm in ARMS:
        e = extremes[extremes.arm == arm]
        rows.append({"family": "extremes", "arm": arm, "n_metrics": len(e),
                     "mean_normalized_mae": float((e.sim_share - e.observed_share).abs().mean())})
    for arm in ARMS:
        p = players[(players.arm == arm) & players.std_bias.notna()]
        rows.append({"family": "player_allocation", "arm": arm, "n_metrics": len(p),
                     "mean_abs_std_bias": float(p.std_bias.abs().mean()) if len(p) else np.nan,
                     "note": "all metrics with a simulated value; V2 adds the snap metrics"})
    for arm in ARMS:
        p = players[(players.arm == arm) & players.metric.isin(PLAYER_CORE)]
        rows.append({"family": "player_allocation_core", "arm": arm, "n_metrics": len(p),
                     "mean_abs_std_bias": float(p.std_bias.abs().mean()),
                     "note": "the same eight metrics for every arm"})
    out = pd.DataFrame(rows)
    paired = []
    for a, b in (("v15", "v1"), ("v2", "v15"), ("v2", "v1")):
        per_game = [np.mean([norm_store[m][a][k] - norm_store[m][b][k] for m in DRIVE + TOTAL + HALF])
                    for k in range(gi_n)]
        point, lo, hi = bootstrap_mean(per_game, rng)
        paired.append({"family": "drive_half_totals", "comparison": "%s minus %s" % (a, b),
                       "mean_normalized_mae_difference": point, "ci_low": lo, "ci_high": hi})
    return out, pd.DataFrame(paired)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--metrics", required=True)
    ap.add_argument("--observed", required=True)
    ap.add_argument("--verify", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    rng = np.random.default_rng(RNG_SEED)

    sim, obs, sim_player, obs_player, status = load(a.metrics, a.observed, a.verify)
    sim, sim_player, obs, obs_player, dropped = restrict_to_common(sim, sim_player, obs, obs_player)
    for arm in ARMS:
        if set(zip(sim[sim.arm == arm].game_id, sim[sim.arm == arm].team)) != set(zip(obs.game_id, obs.team)):
            raise SystemExit("%s: simulated and observed team-games differ after restriction" % arm)
    games = sorted(obs.game_id.unique())
    sim_tg = sim_team_games(sim)
    obs_tg = observed_team_games(obs)

    norm_store = {}
    table = pd.concat([metric_table(DRIVE, sim_tg, obs_tg, games, rng, "drive", norm_store),
                       metric_table(TOTAL, sim_tg, obs_tg, games, rng, "season_totals", norm_store),
                       metric_table(HALF, sim_tg, obs_tg, games, rng, "half", norm_store)], ignore_index=True)
    table.to_csv(os.path.join(a.out, "table_drive_half_totals.csv"), index=False)

    players = player_block(sim_player, obs_player, sim, obs, games, rng)
    players.to_csv(os.path.join(a.out, "table_players.csv"), index=False)

    yardage = yardage_block(sim, obs, games, rng)
    yardage.to_csv(os.path.join(a.out, "table_yardage.csv"), index=False)

    dist, cal, extremes = variability_block(sim, obs, games)
    dist.to_csv(os.path.join(a.out, "table_variability.csv"), index=False)
    cal.to_csv(os.path.join(a.out, "table_calibration.csv"), index=False)
    extremes.to_csv(os.path.join(a.out, "table_extremes.csv"), index=False)

    family, paired = family_summary(table, dist, cal, yardage, extremes, players, norm_store, games, rng)
    family.to_csv(os.path.join(a.out, "table_family_summary.csv"), index=False)
    paired.to_csv(os.path.join(a.out, "table_paired_family_differences.csv"), index=False)

    per_arm = status.groupby(["arm", "category"]).size().unstack(fill_value=0)
    summary = {
        "games_requested": REQUESTED_GAMES,
        "games_scored": int(len(games)),
        "team_games_scored": int(len(obs)),
        "team_games_dropped_no_completed_seed_in_some_arm": ["%s %s" % k for k in dropped],
        "seeds_per_arm": int(status.groupby("arm").size().iloc[0]),
        "completed_seeds_per_arm": {arm: int(per_arm.loc[arm, ["complete", "tied"]].sum()) for arm in ARMS},
        "tied_seeds_per_arm": {arm: int(per_arm.loc[arm].get("tied", 0)) for arm in ARMS},
        "blocked_seeds_per_arm": {arm: int(per_arm.loc[arm].get("blocked", 0)) for arm in ARMS},
        "error_seeds_per_arm": {arm: int(per_arm.loc[arm].get("incomplete", 0)) for arm in ARMS},
        "valid_full_game_seeds_per_arm": {arm: int(per_arm.loc[arm].get("valid", 0)) for arm in ARMS},
        "snap_metrics_exported": {arm: bool(players[(players.arm == arm) & (players.metric == "team_offense_snaps")]
                                            .sim_mean.notna().any()) for arm in ARMS},
        "bootstrap_draws": DRAWS,
        "bootstrap_seed": RNG_SEED,
        "development_exposed": True,
    }
    with open(os.path.join(a.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
