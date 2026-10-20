"""FBS model runner: parity gate, pregame locks, grading.

Usage
  python fbs_model_runner.py --parity          # reproduce the research walk-forward numbers
  python fbs_model_runner.py --run --days 10   # forecast the upcoming slate, lock, grade
  python fbs_model_runner.py --grade-only

Parity is the gate. If the copied research modules no longer reproduce
research/fbs/phase3-g/metrics.csv on the same 2,397 games, the production forecast is not the
adopted model and the runner must not write locks.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fbs_game_winner_baseline as base  # noqa: E402
import fbs_model_service as service  # noqa: E402
import fbs_model_store as store  # noqa: E402
import fbs_phase3_features_c as feat_c  # noqa: E402
from fbs_phase3_features_c import FEATURE_NAMES_C as FEATURES_C  # noqa: E402
from fbs_phase3_increment import walk_forward  # noqa: E402
from fbs_phase3_increment_g import hierarchical_walk_forward  # noqa: E402

RESEARCH = {
    ("walk-forward 2023-2025", "g2"): 0.21326326867759376,
    ("walk-forward 2023-2025", "c2"): 0.19649426790375815,
    ("walk-forward 2023-2025", "g2h"): 0.19459583502356598,
}
PARITY_TOLERANCE = 5e-4
PARITY_LEDGER = os.environ.get("FBS_PARITY_LEDGER", "/root/fbs-data/parity/wf_research.csv")
ESPN_SCOREBOARD = ("https://site.api.espn.com/apis/site/v2/sports/football/"
                   "college-football/scoreboard?groups=80&limit=400&dates=%s")
MODEL_ORDER = ("g2", "c2", "g2h")


def brier(rows: pd.DataFrame, column: str) -> float:
    y = rows["y"].to_numpy(dtype=float)
    p = rows[column].to_numpy(dtype=float)
    return float(np.mean((p - y) ** 2))


def check_parity(frame: pd.DataFrame, ledger_path: str = PARITY_LEDGER) -> dict:
    """Re-derive the research walk-forward, then compare per game against the frozen ledger.

    The aggregate Brier alone cannot tell an implementation drift from a population drift: the
    research population additionally required a non-null EPA feature that neither C2 nor G2h
    uses. So the gate is per-game agreement on the ledger's own games, which is strict, plus the
    aggregate Brier on the identical population.
    """
    work = frame[frame["season"].between(2022, 2026)].copy()
    wf = walk_forward(work.copy(), FEATURES_C)
    wf = wf.rename(columns={"p_b2": "p_c2", "p_b1": "p_c2_ctl"})
    hwf, diags = hierarchical_walk_forward(work.copy(), FEATURES_C, service.LAM_TEAM, service.LAM_CONF)
    merged = (frame[["game_id", "season", "y", "p_g2"]]
              .merge(wf[["game_id", "p_c2"]], on="game_id", how="inner")
              .merge(hwf[["game_id", "p_h"]], on="game_id", how="inner"))
    merged = merged.rename(columns={"p_h": "p_g2h"})
    merged["game_id"] = merged["game_id"].astype(str)

    result = {"models": {}, "max_grad": max(d["grad_norm"] for d in diags)}
    if not os.path.exists(ledger_path):
        result.update({"ok": False, "reason": "missing parity ledger %s" % ledger_path})
        return result

    ledger = pd.read_csv(ledger_path, dtype={"game_id": str})
    ledger["game_id"] = ledger["game_id"].astype(str)
    population = (ledger[ledger["season"].between(2023, 2025)]
                  .merge(merged, on="game_id", how="inner", suffixes=("_ref", "")))
    result["games"] = int(len(population))
    result["ledger_games"] = int(len(ledger[ledger["season"].between(2023, 2025)]))

    for model in MODEL_ORDER:
        column = "p_" + model
        ref = population["%s_ref" % column]
        mine = population[column]
        difference = (mine - ref).abs()
        y = population["y_ref"].to_numpy(dtype=float)
        observed = float(np.mean((mine.to_numpy(dtype=float) - y) ** 2))
        expected = RESEARCH[("walk-forward 2023-2025", model)]
        result["models"][model] = {
            "brier": round(observed, 6),
            "expected": round(expected, 6),
            "delta": round(observed - expected, 6),
            "max_abs_row_diff": float(round(difference.max(), 9)),
            "rows_over_1e-6": int((difference > 1e-6).sum()),
            "ok": bool(difference.max() <= 1e-6),
        }
    result["ok"] = (result["games"] == result["ledger_games"]
                    and all(m["ok"] for m in result["models"].values()))
    return result


# --------------------------------------------------------------------------------------- slate

def fetch_slate(days: int = 10, now: dt.datetime | None = None) -> pd.DataFrame:
    """Upcoming FBS games from ESPN's public scoreboard. No key, no scraping of team pages."""
    import urllib.request

    now = now or dt.datetime.now(dt.timezone.utc)
    rows = []
    for offset in range(0, days + 1):
        date = (now + dt.timedelta(days=offset)).strftime("%Y%m%d")
        try:
            with urllib.request.urlopen(ESPN_SCOREBOARD % date, timeout=20) as response:
                payload = json.load(response)
        except Exception as exc:  # network failure is reported, never guessed around
            print("slate: %s unreachable (%s)" % (date, exc))
            continue
        for event in payload.get("events", []):
            competition = (event.get("competitions") or [{}])[0]
            teams = {c["homeAway"]: c["team"] for c in competition.get("competitors", [])}
            home, away = teams.get("home"), teams.get("away")
            if not home or not away:
                continue
            status = (competition.get("status") or event.get("status") or {}).get("type", {})
            rows.append({
                "game_id": str(event.get("id")),
                "kickoff_utc": event.get("date"),
                "home_team_id": str(home.get("id")), "away_team_id": str(away.get("id")),
                "home_team": home.get("displayName") or home.get("shortDisplayName"),
                "away_team": away.get("displayName") or away.get("shortDisplayName"),
                "neutral_site": bool(competition.get("neutralSite", False)),
                "completed": bool(status.get("completed", False)),
                "home_score": _score(competition, "home"), "away_score": _score(competition, "away"),
            })
    slate = pd.DataFrame(rows).drop_duplicates("game_id")
    if slate.empty:
        return slate
    slate["kickoff_utc"] = pd.to_datetime(slate["kickoff_utc"], utc=True)
    return slate.sort_values("kickoff_utc").reset_index(drop=True)


def _score(competition: dict, side: str) -> int | None:
    for competitor in competition.get("competitors", []):
        if competitor.get("homeAway") == side:
            try:
                return int(float(competitor.get("score")))
            except (TypeError, ValueError):
                return None
    return None


def g2_for_slate(frame: pd.DataFrame, slate: pd.DataFrame) -> pd.DataFrame:
    """Score upcoming games with the Phase 1 Elo by appending them to the event history.

    The Elo only updates on completed games, so a synthetic future row is scored with the
    ratings that exist today — no result leaks in because the row carries none.
    """
    seasons = sorted(set(frame["season"].tolist()) | set(slate["kickoff_utc"].dt.year.tolist()))
    events, _, _, _ = base.load_events(service.DEFAULT_DATA_DIR, [s for s in seasons if s >= 2022])
    template = events.iloc[-1].to_dict()
    extra = []
    for row in slate.itertuples(index=False):
        event = dict(template)
        event.update({
            "game_id": str(row.game_id), "season": int(row.kickoff_utc.year),
            "week": int(row.kickoff_utc.isocalendar()[1]),
            "kickoff_utc": row.kickoff_utc,
            "utc_date": row.kickoff_utc.date(),
            "week_start_utc": (row.kickoff_utc - pd.Timedelta(days=row.kickoff_utc.weekday())).date(),
            "home_team_id": str(row.home_team_id), "away_team_id": str(row.away_team_id),
            "home_team": row.home_team, "away_team": row.away_team,
            "home_score": np.nan, "away_score": np.nan, "home_win": np.nan,
            "neutral_site": bool(row.neutral_site), "fbs_game": True,
            "fbs_participant": False, "cfb_completed": False, "evaluation_population": True,
            "result_source": "scheduled", "home_model_favorite": np.nan,
        })
        extra.append(event)
    combined = pd.concat([events, pd.DataFrame(extra)], ignore_index=True)
    forecasts = base.make_predictions(combined, 2022)
    forecasts["game_id"] = forecasts["game_id"].astype(str)
    wanted = set(slate["game_id"].astype(str))
    scored = forecasts[forecasts["game_id"].isin(wanted)].copy()
    scored["p_g2"] = scored["elo_home_prob"].astype(float)
    return scored


def slate_features(ratings: pd.DataFrame, slate: pd.DataFrame, season: int) -> pd.DataFrame:
    """Drive-split features for a future matchup from each team's latest as-of metrics."""
    current = ratings[ratings["season"] == season].copy()
    if current.empty:
        current = ratings.sort_values(["season", "week"]).groupby("pos_team").tail(1)
    latest = (current.sort_values(["season", "week"])
              .groupby("pos_team").tail(1).set_index("pos_team"))
    metrics = {
        "points_per_drive_diff": "points_per_drive",
        "turnovers_per_drive_diff": "turnovers_per_drive",
        "start_field_position_diff": "start_field_position",
        "rz_td_rate_diff": "rz_td_rate",
        "third_down_rate_diff": "third_down_rate",
        "explosive_drive_rate_diff": "explosive_drive_rate",
        "penalties_per_play_diff": "penalties_per_play",
    }
    rows = []
    for row in slate.itertuples(index=False):
        home, away = str(row.home_team_id), str(row.away_team_id)
        if home not in latest.index or away not in latest.index:
            continue
        out = {"game_id": str(row.game_id), "position": "slate"}
        for name, metric in metrics.items():
            out[name] = ((latest.at[home, "off_" + metric] + latest.at[away, "def_" + metric])
                         - (latest.at[away, "off_" + metric] + latest.at[home, "def_" + metric]))
        out["home_has_history"] = latest.at[home, "has_history"]
        out["away_has_history"] = latest.at[away, "has_history"]
        rows.append(out)
    return pd.DataFrame(rows)


def run(days: int = 10, db_path: str = store.DEFAULT_DB, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    frame, ratings = service.build_frame(verbose=True, return_ratings=True)
    season = int(frame["season"].max())
    slate = fetch_slate(days=days, now=now)
    print("slate: %d games from ESPN" % len(slate))
    if slate.empty:
        return {"locked": 0, "graded": 0, "reason": "empty_slate"}

    scored = g2_for_slate(frame, slate)
    feats = slate_features(ratings, slate, season)
    scored = scored.merge(feats, on="game_id", how="left")
    scored = scored[scored["points_per_drive_diff"].notna()].copy()
    if scored.empty:
        return {"locked": 0, "graded": 0, "reason": "no_feature_coverage"}
    for column in FEATURES_C:
        scored[column] = scored[column].fillna(0.0)

    state = service.fit(frame, now)
    print("fitted on %d games through %s" % (state["train_games"], state["train_last_date"].date()))
    predictions = service.predict(frame, state, scored)

    rows = []
    version = "fbs-%s-%s" % ("%s", state["train_last_date"].strftime("%Y%m%d"))
    for row in predictions.itertuples(index=False):
        kickoff = pd.Timestamp(row.utc_date).tz_localize("UTC").isoformat()
        for model in MODEL_ORDER:
            rows.append({
                "game_id": str(row.game_id), "model": model, "season": int(row.season),
                "kickoff_utc": kickoff, "home_team": row.home_team, "away_team": row.away_team,
                "home_team_id": str(row.home_team_id), "away_team_id": str(row.away_team_id),
                "model_version": version % model,
                "p_home": float(getattr(row, "p_" + model)),
                "fitted_through": str(state["train_last_date"].date()),
            })

    results = {}
    for row in frame[frame["y"].notna()].itertuples(index=False):
        results[str(row.game_id)] = {"home_score": int(row.home_score),
                                     "away_score": int(row.away_score)}

    con = store.open_db(db_path)
    try:
        locked = store.lock_forecasts(con, rows, now=now)
        graded = store.grade_forecasts(con, results, now=now)
        store.set_meta(con, last_run_utc=now.isoformat(), model_version=version % "g2h",
                       train_last_date=str(state["train_last_date"].date()),
                       train_games=state["train_games"])
    finally:
        con.close()
    print("locked: %s; graded: %d" % (locked, graded))
    return {"locked": locked, "graded": graded}


def grade_only(db_path: str = store.DEFAULT_DB) -> int:
    frame = service.build_frame()
    results = {str(r.game_id): {"home_score": int(r.home_score), "away_score": int(r.away_score)}
               for r in frame[frame["y"].notna()].itertuples(index=False)}
    con = store.open_db(db_path)
    try:
        return store.grade_forecasts(con, results)
    finally:
        con.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parity", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--grade-only", action="store_true")
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--db", default=store.DEFAULT_DB)
    args = parser.parse_args(argv)

    if args.parity:
        frame = service.build_frame(verbose=True)
        result = check_parity(frame)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
    if args.grade_only:
        print("graded", grade_only(args.db))
        return 0
    if args.run:
        print(json.dumps(run(days=args.days, db_path=args.db), indent=2))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
