"""FBS model runner: parity certificate, previews, T-90 locks, grading.

Usage
  python fbs_model_runner.py --parity          # reproduce the research walk-forward numbers
  python fbs_model_runner.py --run --days 10   # preview the slate; lock inside T-90 if certified
  python fbs_model_runner.py --grade-only
  python fbs_model_runner.py --audit           # read-only provenance check of the stored rows

Parity is the gate for locks. --parity writes a certificate bound to the frozen ledger and to
the code that produced it. --run writes previews regardless, and writes locks only when a
passing certificate matches the current code and ledger. A certificate for other code is not
a certificate. Nothing locks after kickoff.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fbs_game_winner_baseline as base  # noqa: E402
import fbs_model_service as service  # noqa: E402
import fbs_model_store as store  # noqa: E402
import fbs_lifecycle as life  # noqa: E402
import fbs_phase3_features_c as feat_c  # noqa: E402
from fbs_phase3_features_c import FEATURE_NAMES_C as FEATURES_C  # noqa: E402

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
CERTIFICATE_NAME = "fbs-parity-certificate.json"
# Every module whose code changes the forecast. A certificate is bound to these bytes.
FINGERPRINT_MODULES = (
    "fbs_model_runner.py", "fbs_model_service.py", "fbs_model_store.py", "fbs_lifecycle.py",
    "fbs_game_winner_baseline.py",
    "fbs_phase3_features_c.py", "fbs_phase3_hierarchical.py", "fbs_phase3_increment.py",
    "fbs_phase3_increment_g.py",
)


def brier(rows: pd.DataFrame, column: str) -> float:
    y = rows["y"].to_numpy(dtype=float)
    p = rows[column].to_numpy(dtype=float)
    return float(np.mean((p - y) ** 2))


def production_forecasts(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Score every date block of the frame with the production forecaster.

    Each block is scored by a model that service.fit fitted on games strictly before the block's
    first date, then service.predict scores the block's rows: the same functions the live forecaster
    calls. Blocks without enough training games fall back to G2, as the research walk-forward does,
    and are counted rather than hidden.
    """
    work = frame[frame["season"].between(2022, 2026)].copy()
    work["block"] = work["season"].astype(str) + "-" + work["utc_date"].astype(str)
    pieces, grads, fitted = [], [], 0
    for _, idx in work.groupby("block", sort=True).groups.items():
        rows = work.loc[np.asarray(idx)]
        cutoff = rows["utc_date"].min()
        train = work[(work["utc_date"] < cutoff) & work["y"].notna()].dropna(subset=["p_g2"] + FEATURES_C)
        if len(train) < service.MIN_TRAIN_GAMES:
            pieces.append(pd.DataFrame({"game_id": rows["game_id"].to_numpy(),
                                        "p_c2": rows["p_g2"].to_numpy(), "p_g2h": rows["p_g2"].to_numpy()}))
            continue
        state = service.fit(work, cutoff)
        scored = service.predict(work, state, rows)
        pieces.append(pd.DataFrame({"game_id": scored["game_id"].to_numpy(),
                                    "p_c2": scored["p_c2"].to_numpy(), "p_g2h": scored["p_g2h"].to_numpy()}))
        grads.append(float(state["g2h"].grad_norm))
        fitted += 1
    audit = {"blocks": len(pieces), "fitted_blocks": fitted, "max_grad": max(grads) if grads else 0.0}
    return pd.concat(pieces, ignore_index=True), audit


def check_parity(frame: pd.DataFrame, ledger_path: str = PARITY_LEDGER) -> dict:
    """Replay the production forecast path, then compare per game with the frozen ledger.

    The forecasts come from service.fit and service.predict at every date block, not from the
    research walk-forward, so the gate tests the code that forecasts. The comparison is per game on
    the ledger's own 2023-2025 games at the 1e-6 threshold, plus the aggregate Brier on the same games.
    """
    result = {"models": {}, "estimator": "service.fit/predict per date block"}
    if not os.path.exists(ledger_path):
        result.update({"ok": False, "reason": "missing parity ledger %s" % ledger_path})
        return result
    try:
        preds, audit = production_forecasts(frame)
    except service.FBSModelError as exc:
        result.update({"ok": False, "reason": "production path failed: %s" % exc})
        return result
    result.update(audit)
    merged = frame[["game_id", "season", "y", "p_g2"]].merge(preds, on="game_id", how="inner")
    merged["game_id"] = merged["game_id"].astype(str)

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


def file_sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def code_fingerprint() -> str:
    digest = hashlib.sha256()
    here = os.path.dirname(os.path.abspath(__file__))
    for name in FINGERPRINT_MODULES:
        digest.update(name.encode())
        digest.update(file_sha256(os.path.join(here, name)).encode())
    return digest.hexdigest()


def coverage_manifest_sha256() -> str | None:
    path = os.path.join(service.COVERAGE_DIR, service.COVERAGE_MANIFEST)
    return file_sha256(path) if os.path.exists(path) else None


def certificate_path(db_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), CERTIFICATE_NAME)


def write_certificate(result: dict, db_path: str, now: dt.datetime) -> str:
    """Record a parity result. Written atomically so a crash never leaves half a certificate."""
    cert = {
        "ok": bool(result.get("ok")),
        "games": result.get("games"),
        "ledger_games": result.get("ledger_games"),
        "ledger_path": PARITY_LEDGER,
        "ledger_sha256": file_sha256(PARITY_LEDGER) if os.path.exists(PARITY_LEDGER) else None,
        "code_fingerprint": code_fingerprint(),
        "coverage_manifest_sha256": coverage_manifest_sha256(),
        "models": result.get("models"),
        "reason": result.get("reason"),
        "checked_at_utc": now.isoformat(),
    }
    path = certificate_path(db_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(cert, handle, indent=2, sort_keys=True)
    os.replace(tmp, path)
    return path


def parity_certified(db_path: str) -> tuple[bool, str]:
    """True only for a passing certificate that matches the current code and frozen ledger."""
    path = certificate_path(db_path)
    if not os.path.exists(path):
        return False, "no parity certificate at %s; run --parity" % path
    with open(path) as handle:
        cert = json.load(handle)
    if not cert.get("ok"):
        return False, "parity certificate at %s records a failure" % path
    if cert.get("code_fingerprint") != code_fingerprint():
        return False, "parity certificate was made for different code; re-run --parity"
    if not os.path.exists(PARITY_LEDGER) or cert.get("ledger_sha256") != file_sha256(PARITY_LEDGER):
        return False, "parity ledger changed since the certificate; re-run --parity"
    current = coverage_manifest_sha256()
    if current is None or cert.get("coverage_manifest_sha256") != current:
        return False, "cfbfastR coverage manifest changed or is missing; re-run --parity"
    return True, "certified %s" % cert.get("checked_at_utc")


# --------------------------------------------------------------------------------------- slate

class SlateUnavailable(service.FBSModelError):
    """The current scoreboard window could not be read completely. Forecasting must stop."""


class GradeSourceUnavailable(service.FBSModelError):
    """A historical scoreboard could not be read. Grading stops; forecasting is not affected."""


def read_scoreboard(date: str) -> dict:
    """One scoreboard date. An unreadable or malformed board raises; it is never an empty day."""
    import urllib.request
    try:
        with urllib.request.urlopen(ESPN_SCOREBOARD % date, timeout=20) as response:
            payload = json.load(response)
    except Exception as exc:
        raise SlateUnavailable("ESPN scoreboard %s unreadable (%s)" % (date, exc))
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise SlateUnavailable("ESPN scoreboard %s malformed: no events list" % date)
    return payload


def event_facts(event: dict) -> dict | None:
    """Lifecycle and result facts for one scoreboard event, from ESPN's own status fields only."""
    competition = (event.get("competitions") or [{}])[0]
    teams = {c.get("homeAway"): c for c in competition.get("competitors", [])}
    home, away = teams.get("home"), teams.get("away")
    if not home or not away:
        return None
    status = (competition.get("status") or event.get("status") or {}).get("type", {})
    completed = status.get("completed")
    name = status.get("name")
    season = (event.get("season") or {}).get("year")
    return {
        "game_id": str(event.get("id")),
        "season": int(season) if season is not None else None,
        "kickoff_utc": event.get("date"),
        "home_team_id": str((home.get("team") or {}).get("id", "")),
        "away_team_id": str((away.get("team") or {}).get("id", "")),
        "home_team": (home.get("team") or {}).get("displayName") or (home.get("team") or {}).get("location"),
        "away_team": (away.get("team") or {}).get("displayName") or (away.get("team") or {}).get("location"),
        "neutral_site": bool(competition.get("neutralSite", False)),
        "week": (event.get("week") or {}).get("number"),
        "status_name": name,
        "completed": bool(completed) if completed is not None else None,
        "lifecycle": life.classify_status(name, completed),
        "home_score": _score(competition, "home"), "away_score": _score(competition, "away"),
    }


def fetch_slate(days: int = 10, now: dt.datetime | None = None) -> pd.DataFrame:
    """Every FBS event in the current window, with ESPN's lifecycle. Any unreadable date raises."""
    now = now or dt.datetime.now(dt.timezone.utc)
    rows, unreadable = [], []
    for offset in range(0, days + 1):
        date = (now + dt.timedelta(days=offset)).strftime("%Y%m%d")
        try:
            payload = read_scoreboard(date)
        except SlateUnavailable as exc:
            unreadable.append(str(exc))
            continue
        for event in payload["events"]:
            facts = event_facts(event)
            if facts is None:
                # An event without two competitors makes the board inconsistent: the slate is unverified.
                unreadable.append("ESPN scoreboard %s event %s has no home and away team" % (date, event.get("id")))
                continue
            rows.append(facts)
    if unreadable:
        raise SlateUnavailable("current slate incomplete: " + "; ".join(unreadable)
                               + "; no forecasts or locks written")
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


def _current_fbs_team_conferences(frame: pd.DataFrame, season: int) -> dict[str, str]:
    """Verified current-season FBS membership and conference, never a prior-game template.

    The Phase 1 evaluation population includes only FBS-vs-FBS games. A team
    without a current-season FBS observation is not silently presumed eligible.
    """
    current = frame[(frame["season"] == season) & frame["fbs_game"].fillna(False)]
    teams: dict[str, str] = {}
    for side in ("home", "away"):
        for team_id, conference in zip(
                current[f"{side}_team_id"], current[f"{side}_conference"]):
            if pd.isna(team_id) or pd.isna(conference) or not str(conference).strip():
                continue
            key, label = str(team_id), str(conference).strip()
            if key in teams and teams[key] != label:
                raise service.FBSModelError(
                    f"conflicting {season} FBS conferences for team {key}: "
                    f"{teams[key]} vs {label}"
                )
            teams[key] = label
    return teams


def g2_for_slate(frame: pd.DataFrame, slate: pd.DataFrame) -> pd.DataFrame:
    """Forecast confirmed FBS-FBS fixtures from their real kickoff and team identity.

    Never copy conference, game phase, or venue fields from an unrelated
    historical game: the hierarchical model uses conference as a predictor.
    """
    seasons = sorted(set(frame["season"].tolist()) | set(slate["kickoff_utc"].dt.year.tolist()))
    events, _, _, _ = base.load_events(service.DEFAULT_DATA_DIR, [s for s in seasons if s >= 2022])
    extra = []
    team_maps: dict[int, dict[str, str]] = {}
    for row in slate.itertuples(index=False):
        season = int(row.kickoff_utc.year)
        if season not in team_maps:
            team_maps[season] = _current_fbs_team_conferences(frame, season)
        team_conferences = team_maps[season]
        home, away = str(row.home_team_id), str(row.away_team_id)
        if home not in team_conferences or away not in team_conferences:
            print("slate: skipping game %s (%s @ %s): current-season FBS membership/"
                  "conference unverified" % (row.game_id, away, home))
            continue
        # The schedule's full timestamp survives the prediction and lock paths.
        # Construct a fresh event from an explicit schema, not events.iloc[-1].
        event = {column: None for column in events.columns}
        event.update({
            "game_id": str(row.game_id), "season": season,
            "week": getattr(row, "week", None),
            "kickoff_utc": row.kickoff_utc.to_pydatetime(),
            "utc_date": row.kickoff_utc.date(),
            "week_start_utc": (row.kickoff_utc - pd.Timedelta(
                days=row.kickoff_utc.weekday())).date().isoformat(),
            "home_team_id": home, "away_team_id": away,
            "home_team": row.home_team, "away_team": row.away_team,
            "home_conference": team_conferences[home],
            "away_conference": team_conferences[away],
            "home_score": np.nan, "away_score": np.nan, "home_win": np.nan,
            "neutral_site": bool(row.neutral_site),
            "fbs_game": True, "fbs_participant": False, "cfb_completed": False,
            "evaluation_population": True,
            "game_phase": "Regular season", "season_type": "regular",
            "result_source": "upcoming ESPN scoreboard",
            "home_model_favorite": np.nan,
        })
        extra.append(event)
    if not extra:
        raise service.FBSModelError(
            "no verified FBS-vs-FBS matchups in upcoming slate; no forecasts written"
        )
    combined = pd.concat([events, pd.DataFrame(extra)], ignore_index=True)
    forecasts = base.make_predictions(combined, 2022)
    forecasts["game_id"] = forecasts["game_id"].astype(str)
    wanted = {r["game_id"] for r in extra}
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


def team_ratings(state: dict, frame: pd.DataFrame, season: int) -> list[dict]:
    """Team-season strength from the fitted hierarchy: conference mean plus the team effect."""
    hier = state["g2h"]
    sides = []
    for side in ("home", "away"):
        sides.append(frame[["utc_date", side + "_team_id", side + "_team", side + "_conference"]]
                     .set_axis(["utc_date", "team_id", "team", "conference"], axis=1))
    # Name and conference come from each team's most recent appearance, not its first row ever.
    names = (pd.concat(sides).sort_values("utc_date")
             .drop_duplicates("team_id", keep="last").set_index("team_id"))
    # Games used counts completed games up to the rating cutoff, never scheduled future rows.
    completed = frame[(frame["season"] == season) & frame["y"].notna()]
    games_played = (completed
                    .melt(id_vars=["game_id"], value_vars=["home_team_id", "away_team_id"],
                          value_name="team_id")
                    .groupby("team_id").size())
    rows = []
    conf_index = getattr(hier, "conf_index", {})
    for (team_season, team_id), index in getattr(hier, "ts_index", {}).items():
        if int(team_season) != season:
            continue
        conference = names.at[team_id, "conference"] if team_id in names.index else None
        baseline = float(hier.m[conf_index[conference]]) if conference in conf_index else 0.0
        rows.append({
            "season": int(team_season), "team_id": team_id,
            "team": names.at[team_id, "team"] if team_id in names.index else team_id,
            "conference": conference,
            "rating": float(hier.u[index] + baseline),
            "games_used": int(games_played.get(team_id, 0)),
        })
    return sorted(rows, key=lambda row: -row["rating"])


BOARD_PACE_SECONDS = 1.0   # ESPN burst limit: one historical board request per second


def board_for_pending(pending: list[tuple[str, str]], paced: float | None = None) -> dict[str, dict | None]:
    """Find each pending game on ESPN's boards. Eastern date first; neighbouring dates only for games
    absent from their own date, so a reschedule across midnight is not lost. Raises GradeSourceUnavailable
    if any requested board cannot be read. Returns game_id -> facts, or None when absent everywhere."""
    import time
    found: dict[str, dict | None] = {game_id: None for game_id, _ in pending}
    kickoffs = dict(pending)

    def scan(dates_by_game: dict[str, list[str]]) -> None:
        wanted: dict[str, set[str]] = {}
        for game_id, dates in dates_by_game.items():
            for date in dates:
                wanted.setdefault(date, set()).add(game_id)
        for date, game_ids in sorted(wanted.items()):
            try:
                payload = read_scoreboard(date)
            except SlateUnavailable as exc:
                raise GradeSourceUnavailable(str(exc))
            time.sleep(BOARD_PACE_SECONDS if paced is None else paced)
            for event in payload["events"]:
                facts = event_facts(event)
                if facts and facts["game_id"] in game_ids and found.get(facts["game_id"]) is None:
                    found[facts["game_id"]] = facts

    first = {gid: [life.eastern_dates(pd.Timestamp(ko).to_pydatetime())[0]] for gid, ko in pending}
    scan(first)
    absent = {gid: life.eastern_dates(pd.Timestamp(kickoffs[gid]).to_pydatetime())[1:]
              for gid in found if found[gid] is None}
    if absent:
        scan(absent)
    return found


def archive_scores(frame: pd.DataFrame | None) -> dict[str, tuple[int, int]]:
    if frame is None:
        return {}
    rows = frame[frame["y"].notna() & (frame["coverage_status"] == "has_plays")]
    return {str(r.game_id): (int(r.home_score), int(r.away_score)) for r in rows.itertuples(index=False)}


def plan_grades(pending: list[tuple[str, str]], facts: dict[str, dict | None],
                archive: dict[str, tuple[int, int]]) -> list[dict]:
    """Pure decision for each pending game: grade, void, hold, quarantine, or keep unresolved."""
    plan = []
    for game_id, kickoff in pending:
        fact = facts.get(game_id)
        if fact is None:
            plan.append({"action": "unresolved", "game_id": game_id, "reason": "absent_from_board"})
            continue
        lifecycle = fact["lifecycle"]
        base = {"game_id": game_id, "lifecycle": lifecycle, "status_name": fact["status_name"],
                "season": fact["season"]}
        if lifecycle in life.VOID_LIFECYCLES:
            plan.append({**base, "action": "void", "reason": lifecycle})
        elif lifecycle == "completed":
            if not life.is_gradeable(lifecycle, fact["home_score"], fact["away_score"]):
                plan.append({**base, "action": "unresolved", "reason": "completed_without_scores"})
            elif game_id in archive and archive[game_id] != (fact["home_score"], fact["away_score"]):
                plan.append({**base, "action": "quarantine", "reason": "archive_espn_score_mismatch",
                             "archive": archive[game_id],
                             "espn": (fact["home_score"], fact["away_score"])})
            else:
                plan.append({**base, "action": "grade", "home_score": fact["home_score"],
                             "away_score": fact["away_score"]})
        elif lifecycle in life.HOLD_LIFECYCLES:
            plan.append({**base, "action": "hold", "reason": "schedule_unresolved_" + lifecycle})
        else:
            plan.append({**base, "action": "unresolved", "reason": "status_" + lifecycle})
    return plan


def grade_step(db_path: str, now: dt.datetime, frame: pd.DataFrame | None = None) -> dict:
    """Historical grading. Independent of forecasting: it never writes a preview or a lock.

    The boards are read first. If any is unreadable nothing is written. Otherwise every decision is
    planned and then applied in one batch, so a failure cannot leave a half-graded run behind.
    """
    con = store.open_db(db_path)
    try:
        pending = store.pending_grades(con, now)
        if not pending:
            store.record_run(con, "grade", "nothing_due", {}, now)
            return {"status": "nothing_due", "graded": 0}
        try:
            facts = board_for_pending(pending)
        except GradeSourceUnavailable as exc:
            store.record_run(con, "grade", "grade_source_unavailable", {"error": str(exc)}, now)
            return {"status": "grade_source_unavailable", "graded": 0, "error": str(exc)}
        plan = plan_grades(pending, facts, archive_scores(frame))
        results = {}
        for item in plan:
            game_id = item["game_id"]
            status = store.game_status(con, game_id)
            season = item.get("season") or (status or {}).get("season") or 0
            revision = (status or {}).get("revision", 1)
            observed = now.isoformat()
            if item["action"] == "grade":
                results[game_id] = {"home_score": item["home_score"], "away_score": item["away_score"]}
                store.resolve_unresolved(con, game_id, now, commit=False)
            elif item["action"] == "void":
                store.set_game_status(con, game_id, season, revision, item["lifecycle"], item["status_name"],
                                      observed, "espn_scoreboard", "void", item["reason"], commit=False)
                store.resolve_unresolved(con, game_id, now, commit=False)
            elif item["action"] == "quarantine":
                store.set_grading_state(con, game_id, "quarantined", item["reason"], observed,
                                        "espn_scoreboard", commit=False)
                store.record_unresolved(con, game_id, season, dict(pending)[game_id], item["reason"], now,
                                        commit=False)
            elif item["action"] == "hold":
                store.set_game_status(con, game_id, season, revision, item["lifecycle"], item["status_name"],
                                      observed, "espn_scoreboard", "pending", item["reason"], commit=False)
            else:
                kickoff = dict(pending)[game_id]
                store.record_unresolved(con, game_id, season, kickoff, item["reason"], now, commit=False)
        graded = store.grade_forecasts(con, results, now=now, commit=False)
        con.commit()
        alerts = [u["game_id"] for u in store.unresolved_queue(con) if u["alert_state"] == "alerted"]
        counts = {a: sum(1 for p in plan if p["action"] == a) for a in
                  ("grade", "void", "quarantine", "hold", "unresolved")}
        detail = {**counts, "pending": len(pending), "alerts": alerts}
        store.record_run(con, "grade", "ok", detail, now)
        return {"status": "ok", "graded": graded, **detail}
    finally:
        con.close()


def reconcile_final_scores(finals: dict[str, dict], archive: dict[str, tuple[int, int]]) -> None:
    """Retained for callers that hold finals and an archive: raise on any confirmed disagreement."""
    for game_id, final in finals.items():
        if game_id in archive and archive[game_id] != (final["home_score"], final["away_score"]):
            raise service.FBSModelError(
                "archive and ESPN final scores disagree for %s: %s vs %s"
                % (game_id, archive[game_id], (final["home_score"], final["away_score"])))


def eastern_date(kickoff_utc: str) -> str:
    return life.eastern_dates(pd.Timestamp(kickoff_utc).to_pydatetime())[0]


FORECAST_OK = ("ok", "empty_slate", "no_feature_coverage")


def _board_dates(now: dt.datetime, days: int) -> set[str]:
    """The scoreboard dates one slate fetch requests. A game filed on another date is not expected here."""
    return {(now + dt.timedelta(days=offset)).strftime("%Y%m%d") for offset in range(days + 1)}


def _slate_unavailable(con, now: dt.datetime, error: str) -> dict:
    """The current slate could not be verified, so nothing is previewed or locked. Expired windows are still
    classified, and every known-scheduled game due within 24 hours becomes an immediate lock risk."""
    store.begin(con)
    try:
        missed = store.record_missed_windows(con, now=now, commit=False)
        horizon = now + dt.timedelta(hours=24)
        at_risk = []
        for row in con.execute("SELECT game_id, season FROM fbs_game_status WHERE lifecycle = 'scheduled'").fetchall():
            kickoff = store.current_fixture(con, row["game_id"])["kickoff_utc"]
            if now < store.parse_time(kickoff) <= horizon:
                store.record_unresolved(con, row["game_id"], row["season"], kickoff, "slate_unavailable_pregame",
                                        now, commit=False, lock_risk=True)
                at_risk.append(row["game_id"])
        store.record_run(con, "forecast", "slate_unavailable",
                         {"error": error, "missed": missed, "lock_risk": at_risk}, now, commit=False)
        con.commit()
    except Exception:
        con.rollback()
        raise
    return {"status": "slate_unavailable", "error": error, "previewed": 0,
            "locked": {"blocked": "slate_unavailable"}, "missed": missed, "lock_risk": at_risk}


def _write_forecast(con, slate: pd.DataFrame, predictions: pd.DataFrame, now: dt.datetime, days: int,
                    certified: bool, reason: str | None, rating_rows: list[dict], version: str, state: dict) -> dict:
    """Every write of one forecast run. The caller owns the transaction and commits once."""
    board = _board_dates(now, days)
    seen = {}
    for rec in slate.to_dict("records"):
        game_id, season = rec["game_id"], int(rec["season"])
        obs = store.observe_fixture(con, rec, now, "espn_scoreboard")
        lifecycle = rec["lifecycle"]
        grading = "void" if lifecycle in life.VOID_LIFECYCLES else "pending"
        status_reason = None
        if obs["identity_changed"]:
            lifecycle, grading, status_reason = "unknown", "unresolved", "identity_changed"
        elif lifecycle == "unknown":
            grading, status_reason = "unresolved", "status_unknown"
        elif lifecycle in life.HOLD_LIFECYCLES:
            status_reason = "schedule_unresolved_" + lifecycle
        store.set_game_status(con, game_id, season, obs["revision"], lifecycle, rec["status_name"],
                              now.isoformat(), "espn_scoreboard", grading, status_reason, commit=False)
        seen[game_id] = (lifecycle, obs)
        if lifecycle == "unknown" and now < store.parse_time(obs["kickoff_utc"]):
            # A pregame verification failure: visible at once, because the lock may still be taken.
            store.record_unresolved(con, game_id, season, obs["kickoff_utc"], status_reason, now,
                                    commit=False, lock_risk=True)
        elif lifecycle == "unknown" or lifecycle in life.HOLD_LIFECYCLES:
            store.record_unresolved(con, game_id, season, obs["kickoff_utc"], status_reason, now, commit=False)
        else:
            store.resolve_unresolved(con, game_id, now, commit=False)

    for row in con.execute("SELECT game_id, season FROM fbs_game_status WHERE lifecycle = 'scheduled'").fetchall():
        game_id, season = row["game_id"], row["season"]
        fixture = store.current_fixture(con, game_id)
        if game_id in seen or eastern_date(fixture["kickoff_utc"]) not in board:
            continue
        revision = store.game_status(con, game_id)["revision"]
        store.set_game_status(con, game_id, season, revision, "unknown", None, now.isoformat(),
                              "espn_scoreboard", "unresolved", "absent_from_board", commit=False)
        future = now < store.parse_time(fixture["kickoff_utc"])
        store.record_unresolved(con, game_id, season, fixture["kickoff_utc"], "absent_from_board", now,
                                commit=False, lock_risk=future)

    rows, lock_rows = [], []
    for row in predictions.itertuples(index=False):
        lifecycle, obs = seen.get(str(row.game_id), ("unknown", None))
        if obs is None or obs["identity_changed"] or lifecycle in life.VOID_LIFECYCLES:
            continue
        for model in MODEL_ORDER:
            item = {
                "game_id": str(row.game_id), "model": model, "season": int(row.season),
                "kickoff_utc": obs["kickoff_utc"], "home_team": row.home_team, "away_team": row.away_team,
                "home_team_id": str(row.home_team_id), "away_team_id": str(row.away_team_id),
                "model_version": version % model,
                "p_home": float(getattr(row, "p_" + model)),
                "fitted_through": str(state["train_last_date"].date()),
            }
            rows.append(item)
            if lifecycle == "scheduled":
                lock_rows.append(item)

    previewed = store.upsert_previews(con, rows, now=now, commit=False)
    locked = store.lock_forecasts(con, lock_rows, now=now, commit=False) if certified else {"blocked": reason}
    missed = store.record_missed_windows(con, now=now, commit=False)
    store.store_ratings(con, rating_rows, now.isoformat(), commit=False)
    store.set_meta(con, commit=False, last_run_utc=now.isoformat(), model_version=version % "g2h",
                   train_last_date=str(state["train_last_date"].date()),
                   train_games=state["train_games"], parity_certified=certified, parity_note=reason)
    lock_risk = [u["game_id"] for u in store.unresolved_queue(con) if u["alert_state"] == "lock_risk"]
    report = {"previewed": previewed, "locked": locked, "missed": missed, "lock_risk": lock_risk,
              "games": len(seen)}
    store.record_run(con, "forecast", "ok", report, now, commit=False)
    return {**report, "locks_blocked": None if certified else reason}


def forecast_step(db_path: str, days: int, now: dt.datetime, frame: pd.DataFrame,
                  ratings: pd.DataFrame) -> dict:
    """Current-slate subsystem. Preflight reads the live board and the model before anything is written.
    Every write then happens in one transaction, so a failure anywhere leaves the database as it was."""
    season = int(frame["season"].max())
    con = store.open_db(db_path)
    try:
        try:
            slate = fetch_slate(days=days, now=now)
        except SlateUnavailable as exc:
            return _slate_unavailable(con, now, str(exc))
        if slate.empty:
            store.record_run(con, "forecast", "empty_slate", {}, now)
            return {"status": "empty_slate", "previewed": 0, "locked": {}, "missed": {}}
        print("slate: %d games from ESPN" % len(slate))
        scored = g2_for_slate(frame, slate)
        feats = slate_features(ratings, slate, season)
        scored = scored.merge(feats, on="game_id", how="left")
        uncovered = scored[scored["points_per_drive_diff"].isna()]
        if not uncovered.empty:
            print("slate: %d game(s) without drive-feature coverage, not forecast: %s"
                  % (len(uncovered), ", ".join(uncovered["game_id"].astype(str))))
        scored = scored[scored["points_per_drive_diff"].notna()].copy()
        if scored.empty:
            store.record_run(con, "forecast", "no_feature_coverage", {}, now)
            return {"status": "no_feature_coverage", "previewed": 0, "locked": {}, "missed": {}}
        imputed = scored[FEATURES_C].isna().any(axis=1)
        if imputed.any():
            print("slate: %d game(s) with a missing drive feature filled with 0.0, as in training"
                  % int(imputed.sum()))
        for column in FEATURES_C:
            scored[column] = scored[column].fillna(0.0)

        state = service.fit(frame, now)
        print("fitted on %d games through %s" % (state["train_games"], state["train_last_date"].date()))
        predictions = service.predict(frame, state, scored)
        rating_rows = team_ratings(state, frame, season)
        certified, reason = parity_certified(db_path)
        if not certified:
            print("LOCKS NOT WRITTEN: %s" % reason, file=sys.stderr)
        version = "fbs-%s-%s" % ("%s", state["train_last_date"].strftime("%Y%m%d"))

        store.begin(con)
        try:
            report = _write_forecast(con, slate, predictions, now, days, certified, reason,
                                     rating_rows, version, state)
            con.commit()
        except Exception as exc:
            con.rollback()
            print("forecast rolled back, nothing written: %r" % exc, file=sys.stderr)
            store.record_run(con, "forecast", "rolled_back", {"error": repr(exc)}, now)
            return {"status": "rolled_back", "error": repr(exc), "previewed": 0, "locked": {}, "missed": {}}
        return {"status": "ok", **report}
    finally:
        con.close()


def run(days: int = 10, db_path: str = store.DEFAULT_DB, now: dt.datetime | None = None) -> dict:
    """Forecast the current slate, then grade history. Each step reports its own status, and a failure
    in one does not stop the other. The result keys stay flat for existing callers."""
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        frame, ratings = service.build_frame(verbose=True, return_ratings=True)
    except service.FBSModelError as exc:
        forecast = {"status": "model_unavailable", "error": str(exc), "previewed": 0, "locked": {}, "missed": {}}
        frame = None
    else:
        try:
            forecast = forecast_step(db_path, days, now, frame, ratings)
        except service.FBSModelError as exc:
            forecast = {"status": "model_error", "error": str(exc), "previewed": 0, "locked": {}, "missed": {}}
    grade = grade_step(db_path, now, frame)
    return {"forecast": forecast, "grade": grade,
            "previewed": forecast.get("previewed", 0), "locked": forecast.get("locked", {}),
            "missed": forecast.get("missed", {}), "lock_risk": forecast.get("lock_risk", []),
            "graded": grade.get("graded", 0), "locks_blocked": forecast.get("locks_blocked"),
            "reason": forecast.get("status")}


def audit(db_path: str = store.DEFAULT_DB) -> dict:
    """Read-only provenance counts for stored rows. Changes nothing, labels nothing."""
    con = store.open_db(db_path, readonly=True)
    try:
        columns = {row[1] for row in con.execute("PRAGMA table_info(fbs_forecasts)")}
        protocol = "COALESCE(lock_protocol, 'legacy')" if "lock_protocol" in columns else "'legacy'"
        count = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
        report = {
            "forecast_rows": count("SELECT COUNT(*) FROM fbs_forecasts"),
            "games": count("SELECT COUNT(DISTINCT game_id) FROM fbs_forecasts"),
            "midnight_utc_kickoff_rows": count(
                "SELECT COUNT(*) FROM fbs_forecasts WHERE kickoff_utc LIKE '%T00:00:00%'"),
            "rows_by_protocol": {row[0]: row[1] for row in con.execute(
                "SELECT %s, COUNT(*) FROM fbs_forecasts GROUP BY 1" % protocol)},
            "late_rows": count("SELECT COUNT(*) FROM fbs_forecasts WHERE late = 1"),
            "graded_rows": count("SELECT COUNT(*) FROM fbs_forecasts WHERE result IS NOT NULL"),
        }
        if "lock_protocol" in columns:
            locked = con.execute("SELECT kickoff_utc, locked_at_utc FROM fbs_forecasts "
                                 "WHERE lock_protocol = ?", (store.LOCK_PROTOCOL,)).fetchall()
            report["t90_rows_locked_at_or_after_kickoff"] = sum(
                1 for row in locked
                if store.parse_time(row["locked_at_utc"]) >= store.parse_time(row["kickoff_utc"]))
        if store._table_exists(con, "fbs_previews"):
            report["preview_rows"] = count("SELECT COUNT(*) FROM fbs_previews")
            report["missed_lock_events"] = count("SELECT COUNT(*) FROM fbs_lock_events")
        return report
    finally:
        con.close()


def grade_only(db_path: str = store.DEFAULT_DB) -> int:
    """Grade due games from ESPN's boards alone. The archive is cross-checked in run()."""
    return grade_step(db_path, dt.datetime.now(dt.timezone.utc), None)["graded"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parity", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--grade-only", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--db", default=store.DEFAULT_DB)
    args = parser.parse_args(argv)

    if args.parity:
        frame = service.build_frame(verbose=True)
        result = check_parity(frame)
        path = write_certificate(result, args.db, dt.datetime.now(dt.timezone.utc))
        print(json.dumps(result, indent=2))
        print("certificate: %s (ok=%s)" % (path, result["ok"]))
        return 0 if result["ok"] else 1
    if args.grade_only:
        print("graded", grade_only(args.db))
        return 0
    if args.run:
        result = run(days=args.days, db_path=args.db)
        print(json.dumps(result, indent=2, default=str))
        if result["reason"] not in FORECAST_OK:
            return 4
        return 3 if result["locks_blocked"] else 0
    if args.audit:
        print(json.dumps(audit(args.db), indent=2, default=str))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
