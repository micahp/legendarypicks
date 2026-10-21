#!/usr/bin/env python3
"""Runner for the preregistered FBS passing hurdle (prereg rev4).

Modes
-----
--check-only (default)   Load the read-only cache, build the strictly
                         chronological membership, verify provenance, run every
                         leakage assertion, and report readiness. **Estimates no
                         model parameter** — no prior, no dispersion, no grid.

--fit                    The registered experiment. Refuses to start unless §10 of
                         the preregistration carries an owner signature (blank
                         today), and then requires the dispersion grids and
                         decision rule to be the committed ones.

Nothing here writes predictions, results, baselines or verdicts: the original
research files are read-only inputs at every step.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(HERE)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

import run_direct_props as rdp            # noqa: E402
from hurdle import cohort, leakage, model, prereg_gate, priors   # noqa: E402

MARKET = "pass_attempts"
POSITIONS = ("QB",)
SELECT_SEASON = rdp.VALID_SEASON          # 2024 grid selection
SCORE_SEASON = rdp.SCORE_SEASON           # 2025 evaluation (exploratory)


def _eval_keys(predictions_csv):
    d = pd.read_csv(predictions_csv, usecols=["athlete_id", "season", "week", "game_id"])
    return d.drop_duplicates()


def _scored_frame(pg, keys, season):
    """The rows actually scored for `season`, in the prereg's population.

    Membership is derived **within the frame being classified**, because the
    strictly-trailing fallback is a property of the athlete's appearances in that
    population. Classifying the whole cache and merging afterwards inflates the
    trailing volumes with rows outside the scored frame and does not reproduce
    the preregistered population.
    """
    k = keys[keys["season"] == season]
    d = pg.merge(k, on=["athlete_id", "season", "week", "game_id"], how="inner")
    if d.duplicated(["athlete_id", "season", "week", "game_id"]).any():
        raise ValueError("scored frame has duplicate player-game keys")
    return d.reset_index(drop=True)


def build(cache, predictions_csv):
    pg, _tg, _pr = rdp.build_frames(cache)
    pg = pg.reset_index(drop=True)
    vol = cohort.season_volume(pg, MARKET, POSITIONS)
    thresholds = cohort.season_thresholds(vol)

    keys = _eval_keys(predictions_csv)
    m_all = cohort.classify(pg, MARKET, POSITIONS)                  # training + provenance
    scored = _scored_frame(pg, keys, SCORE_SEASON)
    m_scored = cohort.classify(scored, MARKET, POSITIONS, volume_frame=pg)
    m_scored_alt = cohort.classify(scored, MARKET, POSITIONS, volume_frame=pg,
                                   prior_basis=cohort.PRIOR_BASIS_POSITIVE)
    return pg, m_all, m_scored, m_scored_alt, thresholds


def readiness(cache, prereg_path, predictions_csv):
    gate = prereg_gate.gate_status(prereg_path)
    pg, m, m_scored, m_scored_alt, thresholds = build(cache, predictions_csv)

    part = priors.participation_rows(m, SCORE_SEASON)
    volr = priors.conditional_volume_rows(m, SCORE_SEASON)
    leakage.run_all(m, thresholds, part, volr)
    leakage.assert_cut_precedes_target(m_scored)
    leakage.assert_unclassifiable_2018(m_scored)

    ev24 = m[m["season"] == SELECT_SEASON]

    by_year = {}
    for season, g in m.groupby("season"):
        by_year[int(season)] = {
            "rows": int(len(g)),
            "members": int(g["cohort_member"].sum()),
            "prior_volume": int((g["membership_source"] == cohort.SOURCE_PRIOR).sum()),
            "strictly_trailing": int((g["membership_source"] == cohort.SOURCE_TRAILING).sum()),
            "unclassifiable": int((g["membership_source"] == cohort.SOURCE_UNCLASSIFIABLE).sum()),
            "cut_season": (None if g["cut_season"].isna().all()
                           else int(g["cut_season"].dropna().iloc[0])),
            "cut_threshold": (None if g["cut_threshold"].isna().all()
                              else round(float(g["cut_threshold"].dropna().iloc[0]), 2)),
        }

    baselines = model.load_committed_baselines(predictions_csv)

    return {
        "prereg": gate,
        "market": MARKET,
        "rows_loaded": int(len(m)),
        "by_season": by_year,
        "scored_2025_rows": int(len(m_scored)),
        "scored_2025_members": int(m_scored["cohort_member"].sum()),
        "scored_2025_athletes": int(m_scored.loc[m_scored["cohort_member"], "athlete_id"].nunique()),
        "prereg_population_match": {
            "prereg_rows": 1175, "prereg_athletes": 106,
            "matches": bool(int(m_scored["cohort_member"].sum()) == 1175
                            and m_scored.loc[m_scored["cohort_member"], "athlete_id"].nunique() == 106),
        },
        "alternate_prior_basis": {
            "basis": cohort.PRIOR_BASIS_POSITIVE,
            "rows": int(m_scored_alt["cohort_member"].sum()),
            "athletes": int(m_scored_alt.loc[m_scored_alt["cohort_member"], "athlete_id"].nunique()),
            "used": False,
        },
        "selection_2024_rows": int(len(ev24)),
        "selection_2024_members": int(ev24["cohort_member"].sum()),
        "participation_prior_rowset": {
            "n": int(len(part)), "s": int((part["attempts"] > 0).sum()),
            "value_reported": False,
        },
        "conditional_volume_prior_rowset": {
            "n": int(len(volr)), "value_reported": False,
        },
        "leakage_assertions": "all passed",
        "committed_baselines": {
            "file": os.path.basename(predictions_csv),
            "rows": int(len(baselines)),
            "columns_ok": True,
        },
        "thresholds": {int(k): (None if not np.isfinite(v) else round(float(v), 2))
                       for k, v in thresholds.items()},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=rdp.DEFAULT_CACHE)
    ap.add_argument("--prereg", default=prereg_gate.DEFAULT_PREREG)
    ap.add_argument("--predictions",
                    default=os.path.join(_PARENT, "predictions_pass_attempts.csv"))
    ap.add_argument("--fit", action="store_true",
                    help="run the registered experiment (requires a signed prereg)")
    ap.add_argument("--check-only", action="store_true",
                    help="readiness report only (the default; accepted explicitly)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.fit:
        # The gate is the first statement of the fitting path, not a comment.
        prereg_gate.assert_prereg_signed(args.prereg)
        raise SystemExit(
            "signature present, but the registered experiment is not implemented "
            "in this commit: fitting is deliberately out of scope until signoff "
            "is confirmed by Micah")

    rep = readiness(args.cache, args.prereg, args.predictions)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
        return
    print("prereg       :", rep["prereg"]["state"])
    print("market       :", rep["market"])
    print("rows loaded  :", rep["rows_loaded"])
    print("\nseason  rows  members  prior_vol  trailing  unclassifiab  cut  threshold")
    for s, v in rep["by_season"].items():
        print("%6d %5d %8d %10d %9d %12d %4s %10s"
              % (s, v["rows"], v["members"], v["prior_volume"], v["strictly_trailing"],
                 v["unclassifiable"], v["cut_season"], v["cut_threshold"]))
    print("\n2025 scored rows %d / members %d / athletes %d  [prereg 1175 / 106 -> %s]"
          % (rep["scored_2025_rows"], rep["scored_2025_members"], rep["scored_2025_athletes"],
             "MATCH" if rep["prereg_population_match"]["matches"] else "MISMATCH"))
    print("alternate basis (%s, NOT used): %d rows / %d athletes"
          % (rep["alternate_prior_basis"]["basis"], rep["alternate_prior_basis"]["rows"],
             rep["alternate_prior_basis"]["athletes"]))
    print("2024 selection rows %d / members %d"
          % (rep["selection_2024_rows"], rep["selection_2024_members"]))
    print("prior rowsets: participation n=%d s=%d | volume n=%d (values NOT estimated pre-signature)"
          % (rep["participation_prior_rowset"]["n"],
             rep["participation_prior_rowset"]["s"],
             rep["conditional_volume_prior_rowset"]["n"]))
    print("leakage      :", rep["leakage_assertions"])
    print("baselines    :", rep["committed_baselines"])


if __name__ == "__main__":
    main()
