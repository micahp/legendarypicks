#!/usr/bin/env python3
"""Emit the consolidated per-game forecasts CSV — NO model fit.

Reads the stored artifacts only:
  - forecasts_st.csv       (arms b5, st)
  - forecasts_penalty.csv  (arms st, v1, v2)
  - special_teams_merged_features.csv  (home_team / away_team, and the feature values)
and writes one long-format row per (game, arm):

  game_id, season, game_date, home_team, away_team, model_variant,
  p_home, mu_h, mu_a, home_goals, away_goals

Also writes features_all_arms.csv (game_id, season, home_team, away_team,
hpp, hpk, app, apk, hdrawn, htaken, adrawn, ataken) for the leakage audit.
Penalty features are computed with the same builder the model used; the audit
recomputes them independently.
"""
from __future__ import annotations

import csv
from pathlib import Path

import run_penalty_volume as P

HERE = Path(__file__).resolve().parent
ARMS = ("b5", "st", "v1", "v2")


def load_csv(path):
    return {int(r["game_id"]): r for r in csv.DictReader(open(path))}


def main() -> None:
    st_csv = load_csv(HERE / "forecasts_st.csv")
    pen_csv = load_csv(HERE / "forecasts_penalty.csv")
    merged = {int(r["game_id"]): r for r in csv.DictReader(open(HERE / "special_teams_merged_features.csv"))}

    # ST must be identical across the two stored files
    common = sorted(set(st_csv) & set(pen_csv))
    assert common == sorted(st_csv) and common == sorted(pen_csv), "game sets differ"
    for gid in common:
        assert abs(float(st_csv[gid]["p_st"]) - float(pen_csv[gid]["p_st"])) < 1e-12
        assert abs(float(st_csv[gid]["mu_h_st"]) - float(pen_csv[gid]["mu_h_st"])) < 1e-12
        assert abs(float(st_csv[gid]["mu_a_st"]) - float(pen_csv[gid]["mu_a_st"])) < 1e-12

    # long-format forecasts
    rows = []
    for gid in common:
        s, p = st_csv[gid], pen_csv[gid]
        m = merged[gid]
        for arm in ARMS:
            if arm == "b5":
                p_home, mu_h, mu_a = s["p_b5"], s["mu_h_b5"], s["mu_a_b5"]
            elif arm == "st":
                p_home, mu_h, mu_a = s["p_st"], s["mu_h_st"], s["mu_a_st"]
            elif arm == "v1":
                p_home, mu_h, mu_a = p["p_v1"], p["mu_h_v1"], p["mu_a_v1"]
            elif arm == "v2":
                p_home, mu_h, mu_a = p["p_v2"], p["mu_h_v2"], p["mu_a_v2"]
            rows.append({"game_id": gid, "season": s["season"], "game_date": s["game_date"],
                         "home_team": m["home_team"], "away_team": m["away_team"],
                         "model_variant": arm, "p_home": p_home, "mu_h": mu_h, "mu_a": mu_a,
                         "home_win": s["home_win"],
                         "home_goals": s["home_goals"], "away_goals": s["away_goals"]})
    rows.sort(key=lambda r: (r["game_date"], r["game_id"], r["model_variant"]))
    out = HERE / "forecasts_all_arms.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["game_id", "season", "game_date", "home_team", "away_team",
                                          "model_variant", "p_home", "mu_h", "mu_a", "home_win",
                                          "home_goals", "away_goals"])
        w.writeheader(); w.writerows(rows)
    print(f"wrote {out} ({len(rows)} rows, {len(common)} games x {len(ARMS)} arms)")

    # feature file for the leakage audit
    pen = P.build_penalty_features()
    frows = []
    for gid in common:
        m = merged[gid]
        hp = pen.get((gid, "HOME")); ap = pen.get((gid, "AWAY"))
        frows.append({"game_id": gid, "season": m["season"], "home_team": m["home_team"],
                      "away_team": m["away_team"], "hpp": m["hpp"], "hpk": m["hpk"],
                      "app": m["app"], "apk": m["apk"],
                      "hdrawn": hp[0], "htaken": hp[1], "adrawn": ap[0], "ataken": ap[1]})
    frows.sort(key=lambda r: (r["season"], r["game_id"]))
    fout = HERE / "features_all_arms.csv"
    with fout.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["game_id", "season", "home_team", "away_team",
                                          "hpp", "hpk", "app", "apk",
                                          "hdrawn", "htaken", "adrawn", "ataken"])
        w.writeheader(); w.writerows(frows)
    print(f"wrote {fout} ({len(frows)} rows)")


if __name__ == "__main__":
    main()
