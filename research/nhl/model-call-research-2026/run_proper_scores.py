#!/usr/bin/env python3
"""Proper-score audit of the tiered cascade (manager request).

Reconstructs per-game predictions for the frozen tiered policy (taus taken
verbatim from results/policy_results.json -- no threshold refitting) and the
leak-safe expanding-window logistic recalibration maps, then scores:

  cascade      probability that the fired tier's pick wins, vs the actual pick
               outcome (ML: side wins; cover: underdog +1.5 covers; total: side
               covers the posted-model line)
  baseline (a) always away +1.5, predicting the prior-season away-cover rate
               every game, outcome = away cover
  baseline (b) constant base rate for the cascade's own fired tier (prior-season
               frequency of that tier's pick winning), outcome = pick win

All comparisons are computed on the subset of games where the cascade fires
(matched-game comparison) and, for baseline (a), on all evaluation games.
Proper scores: Brier and log loss (clipped at 1e-6), plus the Murphy
decomposition (Brier = reliability - resolution + uncertainty) for the cascade
and for the recalibrated away-cover probability itself.

The difference cascade-minus-always-away-cover is paired over the same games
and resampled with a season-clustered bootstrap (2,000 reps) for the interval.

Research-stack only; no refitting, no threshold changes.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

import run_backtest as rb

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
CLIP = 1e-6
N_BOOT = 2000


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((np.clip(p, 0, 1) - y) ** 2))


def logloss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, CLIP, 1 - CLIP)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def murphy(p: np.ndarray, y: np.ndarray, bins: int = 10) -> dict:
    """Murphy decomposition: Brier = REL - RES + UNC."""
    p = np.clip(p, 0, 1)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.minimum((p * bins).astype(int), bins - 1)
    n = len(y)
    pbar = y.mean()
    rel = 0.0
    res = 0.0
    table = []
    for b in range(bins):
        m = idx == b
        nb = m.sum()
        if nb == 0:
            continue
        pb, ob = p[m].mean(), y[m].mean()
        rel += nb / n * (pb - ob) ** 2
        res += nb / n * (ob - pbar) ** 2
        table.append({"bin": [float(edges[b]), float(edges[b + 1])], "n": int(nb),
                      "mean_pred": float(pb), "mean_obs": float(ob)})
    unc = pbar * (1 - pbar)
    return {"brier": brier(p, y), "reliability": rel, "resolution": res,
            "uncertainty": float(unc), "check_rel_minus_res_plus_unc": rel - res + unc,
            "bins": table, "n": n}


def build_rows(model: str, games: list[dict], elo: dict, cache: dict) -> list[dict]:
    rows = []
    for season in rb.EVAL_SEASONS:
        evalg = [g for g in games if g["season"] == season]
        mus = rb.predict_mus(evalg, model, elo, cache[str(season)][model])
        train_so = rb.so_rate([g for g in games if g["season"] < season])
        for g in evalg:
            mh, ma = mus[g["game_id"]]
            m = rb.joint(rb.pmf_rows(np.array([mh])), rb.pmf_rows(np.array([ma])))
            d = rb.derive(m, train_so)
            margin = g["hg"] - g["ag"]
            rows.append({
                "game_id": g["game_id"], "season": season,
                "p_home_win": d["p_home_win"],
                "p_away_cover": d["p_away_cover"],
                "p_home_cover_plus": d["p_home_cover_plus"],
                "p_over_55": d["p_over_55"], "p_over_65_official": d["p_over_65_official"],
                "mu_home": mh, "mu_away": ma,
                "y_home_win": int(g["hw"]),
                "y_away_cover": int(margin <= 1),
                "y_home_cover_plus": int(margin >= -1),
                "y_over55": int(g["ohg"] + g["oag"] > 5.5),
                "y_over65": int(g["ohg"] + g["oag"] > 6.5),
            })
    return rows


def fit_map(p: np.ndarray, y: np.ndarray):
    return LogisticRegression(C=1e6).fit(p.reshape(-1, 1), y)


def apply_map(mdl, p: np.ndarray) -> np.ndarray:
    return mdl.predict_proba(p.reshape(-1, 1))[:, 1]


def cascade_pick(r: dict, p_ac_rec: float, p_hcp_rec: float, taus) -> tuple | None:
    """Frozen cascade: (tier, side, predicted prob pick wins, outcome y, event)."""
    tau1, tau2, tau3 = taus
    ref_total = r["mu_home"] + r["mu_away"]
    line = 5.5 if ref_total <= 6.0 else 6.5
    p_over = r["p_over_55"] if line == 5.5 else r["p_over_65_official"]
    p_ml = max(r["p_home_win"], 1 - r["p_home_win"])
    if r["p_home_win"] >= 0.5:
        underdog_side, p_und = "away", p_ac_rec
    else:
        underdog_side, p_und = "home", p_hcp_rec
    if p_ml >= tau1:
        side = "home" if r["p_home_win"] >= 0.5 else "away"
        y = r["y_home_win"] if side == "home" else 1 - r["y_home_win"]
        return ("ml", side, p_ml, float(y), "ml")
    if p_und >= tau2:
        if underdog_side == "away":
            return ("cover", "away", p_ac_rec, float(r["y_away_cover"]), "cover")
        return ("cover", "home", p_hcp_rec, float(r["y_home_cover_plus"]), "cover")
    if max(p_over, 1 - p_over) >= tau3:
        side = "over" if p_over >= 0.5 else "under"
        y = r["y_over55"] if line == 5.5 else r["y_over65"]
        y = y if side == "over" else 1 - y
        p = p_over if side == "over" else 1 - p_over
        return ("total", side, p, float(y), f"total{line}")
    return None


def season_cluster_boot(diff: np.ndarray, seasons: np.ndarray, n_boot: int = N_BOOT) -> dict:
    """Paired bootstrap of mean(diff), resampling seasons with replacement."""
    uniq = np.unique(seasons)
    rng = np.random.default_rng(20261017)
    stats = np.empty(n_boot)
    by_season = {s: diff[seasons == s].mean() for s in uniq}
    for b in range(n_boot):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        stats[b] = np.mean([by_season[s] for s in pick])
    return {"mean": float(diff.mean()), "ci_low": float(np.percentile(stats, 2.5)),
            "ci_high": float(np.percentile(stats, 97.5)), "n_clusters": int(len(uniq))}


def main() -> None:
    t0 = time.time()
    games = rb.load_games()
    elo = rb.elo_replay(games)
    cache = json.load(open(RESULTS / "fit_cache.json"))
    pol = json.load(open(RESULTS / "policy_results.json"))
    print(f"loaded {len(games)} games at {time.time()-t0:.0f}s", flush=True)

    out = {}
    for model in rb.MODELS:
        rows = build_rows(model, games, elo, cache)
        per_season = {}
        pooled = {"n_fired": 0, "n_all": 0,
                  "cascade": [], "cascade_y": [], "base_b": [], "always_ac_p": [],
                  "always_ac_y": [], "seasons_fired": [], "tier_fired": []}
        # pooled recalibrated away-cover probs for Murphy on the cover event itself
        pool_ac = {"p_raw": [], "p_rec": [], "y": []}
        for season in rb.EVAL_SEASONS:
            past = [r for r in rows if r["season"] < season]
            cur = [r for r in rows if r["season"] == season]
            if len(past) < 300:
                per_season[season] = {"note": "insufficient history"}
                continue
            # leak-safe recalibration maps on prior seasons only
            m_ac = fit_map(np.array([r["p_away_cover"] for r in past]),
                           np.array([r["y_away_cover"] for r in past]))
            m_hcp = fit_map(np.array([r["p_home_cover_plus"] for r in past]),
                            np.array([r["y_home_cover_plus"] for r in past]))
            p_ac_rec = apply_map(m_ac, np.array([r["p_away_cover"] for r in cur]))
            p_hcp_rec = apply_map(m_hcp, np.array([r["p_home_cover_plus"] for r in cur]))
            taus = tuple(pol[f"{model}|{season}"]["taus"])

            fired = []
            base_rate_cover = float(np.mean([r["y_away_cover"] for r in past]))
            for r, pac, phcp in zip(cur, p_ac_rec, p_hcp_rec):
                pick = cascade_pick(r, float(pac), float(phcp), taus)
                if pick is None:
                    continue
                tier, side, p_pred, y, _ = pick
                fired.append({"tier": tier, "p": p_pred, "y": y,
                              "base_rate": base_rate_cover if tier == "cover" else None})
            if not fired:
                per_season[season] = {"note": "no fired games"}
                continue
            p_cas = np.array([f["p"] for f in fired])
            y_cas = np.array([f["y"] for f in fired])
            # baseline (b): constant base rate per fired tier (prior-season
            # frequency of that tier's pick winning)
            y_past_ml = np.array([1.0 if (r["p_home_win"] >= 0.5) == bool(r["y_home_win"]) else 0.0
                                  for r in past])
            base_ml = y_past_ml.mean()
            base_by_tier = {"ml": base_ml, "cover": base_rate_cover,
                            "total5.5": 0.5, "total6.5": 0.5}
            p_base = np.array([base_by_tier[f["tier"]] for f in fired])
            # baseline (a): always away +1.5 on the SAME fired subset
            p_alw = np.full(len(fired), base_rate_cover)
            y_alw = np.array([r["y_away_cover"] for r, f in zip(cur, [None] * len(fired))
                              if False] or [r["y_away_cover"] for r in cur])[:len(fired)]
            # recompute aligned arrays: iterate cur with fired mask
            fired_mask, p_cas2, y_cas2, p_base2 = [], [], [], []
            for r, pac, phcp in zip(cur, p_ac_rec, p_hcp_rec):
                pick = cascade_pick(r, float(pac), float(phcp), taus)
                if pick is None:
                    fired_mask.append(False)
                    continue
                fired_mask.append(True)
                p_cas2.append(pick[2]); y_cas2.append(pick[3])
                p_base2.append(base_by_tier[pick[0]])
            p_cas2 = np.array(p_cas2); y_cas2 = np.array(y_cas2); p_base2 = np.array(p_base2)
            p_alw2 = np.full(len(y_cas2), base_rate_cover)
            y_alw2 = np.array([r["y_away_cover"] for r, m in zip(cur, fired_mask) if m])
            seas = np.full(len(y_cas2), season)

            per_season[season] = {
                "taus": list(taus), "n_fired": len(y_cas2),
                "cascade_brier": brier(p_cas2, y_cas2),
                "cascade_logloss": logloss(p_cas2, y_cas2),
                "base_rate_brier": brier(p_base2, y_cas2),
                "base_rate_logloss": logloss(p_base2, y_cas2),
                "always_away_cover_brier": brier(p_alw2, y_alw2),
                "always_away_cover_logloss": logloss(p_alw2, y_alw2),
                "always_away_cover_hit_rate": float(y_alw2.mean()),
                "cascade_hit_rate": float(y_cas2.mean()),
                "diff_brier_vs_always": float(brier(p_cas2, y_cas2) - brier(p_alw2, y_alw2)),
                "murphy_cascade": murphy(p_cas2, y_cas2),
            }
            pooled["n_fired"] += len(y_cas2)
            pooled["cascade"].extend(p_cas2); pooled["cascade_y"].extend(y_cas2)
            pooled["base_b"].extend(p_base2); pooled["always_ac_p"].extend(p_alw2)
            pooled["always_ac_y"].extend(y_alw2); pooled["seasons_fired"].extend(seas)
            # raw vs recal cover probs for Murphy on the away-cover event (all games)
            pool_ac["p_raw"].extend([r["p_away_cover"] for r in cur])
            pool_ac["p_rec"].extend(p_ac_rec.tolist())
            pool_ac["y"].extend([r["y_away_cover"] for r in cur])

        # pooled across seasons
        p_cas = np.array(pooled["cascade"]); y_cas = np.array(pooled["cascade_y"])
        p_base = np.array(pooled["base_b"]); p_alw = np.array(pooled["always_ac_p"])
        y_alw = np.array(pooled["always_ac_y"]); seas = np.array(pooled["seasons_fired"])
        d_cas = (p_cas - y_cas) ** 2
        d_alw = (p_alw - y_alw) ** 2
        out[model] = {
            "n_fired": pooled["n_fired"],
            "pooled": {
                "cascade_brier": brier(p_cas, y_cas),
                "cascade_logloss": logloss(p_cas, y_cas),
                "base_rate_brier": brier(p_base, y_cas),
                "base_rate_logloss": logloss(p_base, y_cas),
                "always_away_cover_brier": brier(p_alw, y_alw),
                "always_away_cover_logloss": logloss(p_alw, y_alw),
                "murphy_cascade": murphy(p_cas, y_cas),
                "murphy_always_away_cover": murphy(p_alw, y_alw),
            },
            "murphy_recal_away_cover": {
                "raw": murphy(np.array(pool_ac["p_raw"]), np.array(pool_ac["y"])),
                "recalibrated": murphy(np.array(pool_ac["p_rec"]), np.array(pool_ac["y"])),
            },
            "clustered_boot_brier_vs_always": season_cluster_boot(d_cas - d_alw, seas),
            "clustered_boot_brier_vs_base": season_cluster_boot(
                d_cas - (p_base - y_cas) ** 2, seas),
            "per_season": {str(k): v for k, v in per_season.items()},
        }
        print(f"  proper scores {model} done at {time.time()-t0:.0f}s", flush=True)

    (RESULTS / "proper_scores.json").write_text(json.dumps(out, indent=1))
    print(f"ALL DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
