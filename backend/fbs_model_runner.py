"""FBS model runner: parity certificate, projections, T-90 freezes, grading.

One projection per game and model. Projections are computed before each game's lock cutoff (kickoff - 90 minutes).
At the cutoff each model's latest projection is frozen. The frozen row is immutable, and it is graded once against
a verified final. Postseason games follow the same workflow.

  python fbs_model_runner.py --run --days 10   # project the slate; freeze at the cutoff if certified
  python fbs_model_runner.py --grade-only      # grade frozen projections against verified finals
  python fbs_model_runner.py --parity          # the 1e-6 parity gate that issues the certificate

Freezing needs a parity certificate beside the database, and a certificate is never issued for an operational
database by this code. Projections are written regardless of the certificate.
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
import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fbs_game_winner_baseline as base  # noqa: E402
import fbs_model_service as service  # noqa: E402
import fbs_model_store as store  # noqa: E402
import fbs_lifecycle as life  # noqa: E402
import fbs_phase3_features as feat_base  # noqa: E402
import fbs_phase3_features_c as feat_c  # noqa: E402
from fbs_phase3_features_c import FEATURE_NAMES_C as FEATURES_C  # noqa: E402

RESEARCH = {
    ("walk-forward 2023-2025", "g2"): 0.21326326867759376,
    ("walk-forward 2023-2025", "c2"): 0.19649426790375815,
    ("walk-forward 2023-2025", "g2h"): 0.19459583502356598,
}
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
        "season_type": (event.get("season") or {}).get("type"),
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


ET_ZONE = pytz.timezone("America/New_York")
PLACEHOLDER = "slate:"
FORECAST_OK = ("ok", "empty_slate")


def scoreboard_dates(now: dt.datetime, days: int) -> list[str]:
    """ESPN scoreboard dates, by Eastern date, that cover every kickoff in (now, now + days].

    ESPN files each game under its Eastern date, so a UTC date is the wrong key: a 10 p.m. Eastern kickoff is 02:00
    UTC the next day. The Eastern date is taken from each instant, so daylight saving is exact. The Eastern date
    before now is included as well, so that a game which began yesterday and runs past midnight keeps its status.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    first = now.astimezone(ET_ZONE).date() - dt.timedelta(days=1)
    last = (now + dt.timedelta(days=days)).astimezone(ET_ZONE).date()
    dates, day = [], first
    while day <= last:
        dates.append(day.strftime("%Y%m%d"))
        day += dt.timedelta(days=1)
    return dates


def calendar_season(kickoff_utc) -> int:
    """The football season a kickoff falls in, by its Eastern calendar date: from June on, the season of that year;
    January to May, the season that began the year before. Only ever used to check ESPN's season field."""
    local = pd.Timestamp(kickoff_utc).tz_convert(ET_ZONE)
    return local.year if local.month >= 6 else local.year - 1


def forecast_horizon_end(now: dt.datetime, days: int) -> dt.datetime:
    """Exclusive end of the preview horizon: the midnight after the Eastern date that contains now + days elapsed.

    The Eastern date comes from the instant after `days` elapsed days, and the boundary is an Eastern local midnight,
    so daylight saving is exact and the horizon always ends on a whole Eastern day. A game kicking off at that
    midnight belongs to the next day, outside the horizon.
    """
    last_day = (now + dt.timedelta(days=days)).astimezone(ET_ZONE).date()
    return ET_ZONE.localize(dt.datetime.combine(last_day + dt.timedelta(days=1), dt.time(0)))


# Fields that two copies of one ESPN event must agree on. Final scores are compared only when both copies are final.
# Live scores are the one source exception: they legitimately differ between two fetches made seconds apart.
def _identity_fields(facts: dict) -> dict:
    fields = {
        "home_team_id": facts["home_team_id"], "away_team_id": facts["away_team_id"],
        "home_team": facts["home_team"], "away_team": facts["away_team"],
        "kickoff": pd.Timestamp(facts["kickoff_utc"]).value, "season": facts["season"],
        "season_type": facts["season_type"], "week": facts["week"],
        "neutral_site": bool(facts["neutral_site"]), "lifecycle": facts["lifecycle"],
        "status_name": facts["status_name"], "completed": facts["completed"],
    }
    if facts["completed"]:
        fields["home_score"] = facts["home_score"]
        fields["away_score"] = facts["away_score"]
    return fields


def fetch_slate(days: int = 10, now: dt.datetime | None = None) -> pd.DataFrame:
    """Each FBS event on the Eastern scoreboard dates for (now, horizon end), once, with ESPN's lifecycle and season.

    An event copied onto two dates is kept once, and only when every copy agrees on every field in _identity_fields().
    Any disagreement, unreadable date, event without two teams, or event without a season raises, so the slate is
    unverified and nothing is written from it. The requested dates are kept in slate.attrs, so the absent-from-board
    check asks about exactly the dates that were read.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    dates = scoreboard_dates(now, days)
    copies: dict[str, list[dict]] = {}
    unreadable = []
    for date in dates:
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
            elif facts["season"] is None:
                unreadable.append("ESPN scoreboard %s event %s has no season" % (date, facts["game_id"]))
            else:
                copies.setdefault(facts["game_id"], []).append(facts)
    if unreadable:
        raise SlateUnavailable("current slate incomplete: " + "; ".join(unreadable)
                               + "; no forecasts or locks written")
    rows, duplicates = [], []
    for game_id, group in copies.items():
        first = _identity_fields(group[0])
        for other in group[1:]:
            fields = _identity_fields(other)
            if fields != first:
                differing = sorted(k for k in set(first) | set(fields) if first.get(k) != fields.get(k))
                raise SlateUnavailable("ESPN event %s differs between scoreboard copies (%s); no forecasts or locks "
                                       "written" % (game_id, ", ".join(differing)))
        if len(group) > 1:
            duplicates.append(game_id)
        rows.append(group[0])
    slate = pd.DataFrame(rows)
    if not slate.empty:
        slate["kickoff_utc"] = pd.to_datetime(slate["kickoff_utc"], utc=True)
        slate = slate.sort_values("kickoff_utc").reset_index(drop=True)
    slate.attrs["requested_dates"] = dates
    slate.attrs["duplicates"] = sorted(duplicates)
    return slate


def forecast_candidates(slate: pd.DataFrame, now: dt.datetime, days: int) -> tuple[pd.DataFrame, dict]:
    """Games that may receive a NEW forecast or lock: scheduled, kickoff strictly after now and before the horizon end,
    with a season that agrees with the kickoff date. Every other game is returned with its reason."""
    horizon_end = forecast_horizon_end(now, days)
    keep, reasons = [], {}
    for rec in slate.to_dict("records"):
        kickoff = rec["kickoff_utc"]
        if kickoff <= now:
            reason = "started"
        elif kickoff >= horizon_end:
            reason = "beyond_horizon"
        elif rec["lifecycle"] != "scheduled":
            reason = "not_scheduled:%s" % rec["lifecycle"]
        elif rec["season"] != calendar_season(kickoff):
            reason = "season_contradicted"
        elif rec.get("season_type") not in (2, 3):
            reason = "season_type_missing"
        else:
            keep.append(rec)
            continue
        reasons.setdefault(reason, []).append(str(rec["game_id"]))
    return pd.DataFrame(keep, columns=slate.columns), reasons


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
    """Forecast confirmed FBS-FBS fixtures from their real kickoff, team identity and ESPN football season.

    Never copy conference, game phase, or venue fields from an unrelated historical game: the hierarchical model
    uses conference as a predictor. The season is ESPN's, never the kickoff's calendar year: a January bowl belongs
    to the season that started the previous year.
    """
    seasons = sorted(set(frame["season"].tolist()) | set(slate["season"].astype(int).tolist()))
    events, _, _, _ = base.load_events(service.DEFAULT_DATA_DIR, [s for s in seasons if s >= 2022])
    extra = []
    team_maps: dict[int, dict[str, str]] = {}
    for row in slate.itertuples(index=False):
        season = int(row.season)
        if season not in team_maps:
            team_maps[season] = _current_fbs_team_conferences(frame, season)
        team_conferences = team_maps[season]
        home, away = str(row.home_team_id), str(row.away_team_id)
        if home not in team_conferences or away not in team_conferences:
            print("slate: skipping game %s (%s @ %s): %s FBS membership/conference unverified"
                  % (row.game_id, away, home, season))
            continue
        # ESPN's season type, not a hardcoded phase: a postseason event carries its postseason provenance.
        postseason = int(row.season_type) == 3
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
            "game_phase": "Postseason" if postseason else "Regular season",
            "season_type": "postseason" if postseason else "regular",
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


SLATE_METRICS = {
    "points_per_drive_diff": "points_per_drive",
    "turnovers_per_drive_diff": "turnovers_per_drive",
    "start_field_position_diff": "start_field_position",
    "rz_td_rate_diff": "rz_td_rate",
    "third_down_rate_diff": "third_down_rate",
    "explosive_drive_rate_diff": "explosive_drive_rate",
    "penalties_per_play_diff": "penalties_per_play",
}


def _placeholder_key(rec: dict, team_games: pd.DataFrame) -> tuple[int, int]:
    """(season, week) for the placeholder row of a game's team. Regular-season games use ESPN's week, the same week
    key the research recurrence uses. Postseason games all carry week 1 in the source, so they are placed after the
    season's last completed week instead. A placeholder must sort after every completed row of its team."""
    season = int(rec["season"])
    season_rows = team_games[team_games["season"] == season]
    last_completed = int(season_rows["week"].max()) if not season_rows.empty else 0
    if rec["season_type"] == 3:
        return season, last_completed + 1
    week = rec.get("week")
    if week is None or pd.isna(week):
        raise service.FBSModelError("regular-season game %s has no ESPN week" % rec["game_id"])
    if int(week) <= last_completed:
        raise service.FBSModelError("game %s week %s does not follow the completed history of season %s"
                                    % (rec["game_id"], week, season))
    return season, int(week)


def slate_features(team_games: pd.DataFrame, frame: pd.DataFrame, candidates: pd.DataFrame,
                   now: dt.datetime) -> pd.DataFrame:
    """Drive features for each candidate, from each team's state as of now.

    Every completed game is strictly before now, and every candidate kicks off after now, so the state built from
    completed games is strictly as-of each kickoff. The research recurrence (build_team_ratings) runs unchanged,
    with one placeholder row per team placed after its completed history. The placeholder's emitted state is the
    state after all of that history. Per side, the result says whether the team has any history, and whether that
    history is only from earlier seasons (an explicit prior-season carry-over, never an unrelated season).
    """
    if candidates.empty:
        return pd.DataFrame()
    now_naive = pd.Timestamp(now).tz_convert("UTC").tz_localize(None)
    history_ids = set(team_games["game_id"].astype(str))
    dated = frame[frame["game_id"].astype(str).isin(history_ids)]
    if not dated.empty and dated["utc_date"].max() > now_naive:
        raise service.FBSModelError("completed history runs past now (%s); features would not be as-of"
                                    % dated["utc_date"].max())
    history_season = team_games.groupby(team_games["pos_team"].astype(str))["season"].max().to_dict()

    placeholders, keys = [], {}
    for rec in candidates.sort_values("kickoff_utc").to_dict("records"):
        key = _placeholder_key(rec, team_games)
        for side in ("home", "away"):
            team = str(rec[side + "_team_id"])
            if team not in keys:
                keys[team] = key
                row = {column: np.nan for column in team_games.columns}
                row.update(game_id=PLACEHOLDER + team, pos_team=team, season=key[0], week=key[1],
                           off_plays=0.0, def_plays=0.0)
                placeholders.append(row)
    combined = pd.concat([team_games, pd.DataFrame(placeholders, columns=team_games.columns)],
                         ignore_index=True)
    combined["game_id"] = combined["game_id"].astype(str)
    combined["pos_team"] = combined["pos_team"].astype(str)
    ratings = feat_base.build_team_ratings(combined, feat_c.METRIC_COLS_C)
    state = ratings[ratings["game_id"].str.startswith(PLACEHOLDER)].copy()
    state["team"] = state["game_id"].str[len(PLACEHOLDER):]
    state = state.set_index("team")

    rows = []
    for rec in candidates.to_dict("records"):
        home, away = str(rec["home_team_id"]), str(rec["away_team_id"])
        out = {"game_id": str(rec["game_id"]), "position": "slate"}
        for name, metric in SLATE_METRICS.items():
            out[name] = ((state.at[home, "off_" + metric] + state.at[away, "def_" + metric])
                         - (state.at[away, "off_" + metric] + state.at[home, "def_" + metric]))
        for side, team in (("home", home), ("away", away)):
            last = history_season.get(team)
            out[side + "_has_history"] = bool(state.at[team, "has_history"])
            out[side + "_no_history"] = last is None
            out[side + "_prior_season_only"] = last is not None and int(last) < int(rec["season"])
        out["feature_season"] = int(rec["season"])
        rows.append(out)
    return pd.DataFrame(rows)


def g2h_effect_gaps(state: dict, scored: pd.DataFrame) -> list[dict]:
    """Team-seasons and conferences the fitted hierarchy never saw. Those effects enter as zero, which is the
    conference-level prior. The gap is reported on every forecast; it is never silently treated as fitted."""
    hier = state["g2h"]
    gaps = []
    for rec in scored.to_dict("records"):
        for side in ("home", "away"):
            team = str(rec[side + "_team_id"])
            if (int(rec["season"]), team) not in hier.ts_index:
                gaps.append({"game_id": str(rec["game_id"]), "side": side, "team_id": team,
                             "season": int(rec["season"]), "reason": "team_season_unfitted"})
            conference = rec[side + "_conference"]
            if conference not in hier.conf_index:
                gaps.append({"game_id": str(rec["game_id"]), "side": side, "team_id": team,
                             "season": int(rec["season"]), "reason": "conference_unfitted"})
    return gaps


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
                results[game_id] = {"home_score": item["home_score"], "away_score": item["away_score"],
                                    "verified": True}
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
    return {"status": "slate_unavailable", "error": error, "projected": 0,
            "frozen": {"blocked": "slate_unavailable"}, "missed": missed, "lock_risk": at_risk}


def _write_forecast(con, slate: pd.DataFrame, board: set[str], predictions, now: dt.datetime, days: int,
                    certified: bool, reason: str | None, rating_rows: list[dict], version: str, state,
                    extra: dict) -> dict:
    """Every write of one forecast run, in the caller's transaction. Nothing here commits.

    Statuses are written for every game on the board, so lifecycle stays current for grading. `predictions` holds the
    games still before their lock cutoff, or is None. The freeze then copies stored projections for every game whose
    cutoff has passed and whose pregame status verifies. Postseason games follow the same path as any other game.
    """
    horizon_end = forecast_horizon_end(now, days)
    seen = {}
    for rec in slate.to_dict("records"):
        game_id = rec["game_id"]
        season = int(rec["season"])
        obs = store.observe_fixture(con, rec, now, "espn_scoreboard")
        lifecycle = rec["lifecycle"]
        grading = "void" if lifecycle in life.VOID_LIFECYCLES else "pending"
        status_reason = None
        if obs["identity_changed"]:
            lifecycle, grading, status_reason = "unknown", "unresolved", "identity_changed"
        elif rec["season"] != calendar_season(rec["kickoff_utc"]):
            lifecycle, grading, status_reason = "unknown", "unresolved", "season_contradicted"
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
        game_id = row["game_id"]
        if game_id in seen:
            continue
        fixture = store.current_fixture(con, game_id)
        kickoff = store.parse_time(fixture["kickoff_utc"])
        if eastern_date(fixture["kickoff_utc"]) not in board or kickoff >= horizon_end:
            continue                      # not on a board this run read, or past the horizon: its absence says nothing
        revision = store.game_status(con, game_id)["revision"]
        store.set_game_status(con, game_id, row["season"], revision, "unknown", None, now.isoformat(),
                              "espn_scoreboard", "unresolved", "absent_from_board", commit=False)
        store.record_unresolved(con, game_id, row["season"], fixture["kickoff_utc"], "absent_from_board", now,
                                commit=False, lock_risk=now < kickoff)

    rows = []
    for row in (predictions.itertuples(index=False) if predictions is not None else []):
        lifecycle, obs = seen.get(str(row.game_id), ("unknown", None))
        if obs is None or obs["identity_changed"] or lifecycle != "scheduled":
            continue
        if now >= store.cutoff_for(store.parse_time(obs["kickoff_utc"])):
            continue                      # projections are never computed after the cutoff
        for model in MODEL_ORDER:
            rows.append({
                "game_id": str(row.game_id), "model": model, "season": int(row.season),
                "kickoff_utc": obs["kickoff_utc"], "home_team": row.home_team, "away_team": row.away_team,
                "home_team_id": str(row.home_team_id), "away_team_id": str(row.away_team_id),
                "model_version": version % model,
                "p_home": float(getattr(row, "p_" + model)),
                "fitted_through": str(state["train_last_date"].date()),
            })

    projected = store.upsert_projections(con, rows, now=now, commit=False)
    frozen = store.freeze_projections(con, now=now, commit=False) if certified else {"blocked": reason}
    missed = store.record_missed_windows(con, now=now, commit=False)
    if rating_rows:
        store.store_ratings(con, rating_rows, now.isoformat(), commit=False)
    if state is not None:
        store.set_meta(con, commit=False, last_run_utc=now.isoformat(), model_version=version % "g2h",
                       train_last_date=str(state["train_last_date"].date()),
                       train_games=state["train_games"], parity_certified=certified, parity_note=reason)
    lock_risk = [u["game_id"] for u in store.unresolved_queue(con) if u["alert_state"] == "lock_risk"]
    statuses = {}
    for row in con.execute("SELECT lifecycle, grading_state, COUNT(*) AS n FROM fbs_game_status "
                           "WHERE game_id IN (%s) GROUP BY 1, 2" % ",".join("?" * len(seen)), list(seen)).fetchall():
        statuses["%s/%s" % (row["lifecycle"], row["grading_state"])] = row["n"]
    report = {"projected": projected, "frozen": frozen, "missed": missed, "lock_risk": lock_risk,
              "games": len(seen), "statuses": statuses,
              "projected_games": sorted({r["game_id"] for r in rows}), **extra}
    store.record_run(con, "forecast", "ok", report, now, commit=False)
    return {**report, "locks_blocked": None if certified else reason}


def forecast_step(db_path: str, days: int, now: dt.datetime, frame: pd.DataFrame,
                  team_games: pd.DataFrame) -> dict:
    """Current-slate subsystem. Everything that can fail (the fetch, the candidate and season checks, the model and
    the features) runs before the one write transaction. Every write in that transaction is rolled back together."""
    con = store.open_db(db_path)
    try:
        try:
            slate = fetch_slate(days=days, now=now)
        except SlateUnavailable as exc:
            return _slate_unavailable(con, now, str(exc))
        board = set(slate.attrs["requested_dates"])
        inventory = {"requested_dates": sorted(board), "slate_games": len(slate),
                     "duplicates": slate.attrs["duplicates"],
                     "horizon_end_utc": forecast_horizon_end(now, days).astimezone(dt.timezone.utc).isoformat()}
        if slate.empty:
            store.record_run(con, "forecast", "empty_slate", inventory, now)
            return {"status": "empty_slate", "projected": 0, "frozen": {}, "missed": {}, **inventory}

        candidates, excluded = forecast_candidates(slate, now, days)
        if candidates.empty:
            projectable = candidates
        else:
            before_cutoff = candidates["kickoff_utc"].map(lambda kickoff: now < store.cutoff_for(kickoff))
            projectable = candidates[before_cutoff].copy()
        inventory.update(excluded=excluded, candidates=sorted(candidates["game_id"].astype(str)),
                         projectable=sorted(projectable["game_id"].astype(str)),
                         past_cutoff=sorted(set(candidates["game_id"].astype(str))
                                            - set(projectable["game_id"].astype(str))))
        print("slate: %d games on %d scoreboard dates; %d eligible; %d still before their cutoff"
              % (len(slate), len(board), len(candidates), len(projectable)))
        certified, reason = parity_certified(db_path)
        if not certified:
            print("LOCKS NOT WRITTEN: %s" % reason, file=sys.stderr)

        predictions, state, rating_rows = None, None, []
        if not projectable.empty:
            scored = g2_for_slate(frame, projectable)
            feats = slate_features(team_games, frame, projectable, now)
            scored = scored.merge(feats, on="game_id", how="left")
            covered = scored["points_per_drive_diff"].notna()
            inventory["uncovered"] = sorted(scored.loc[~covered, "game_id"].astype(str))
            scored = scored[covered].copy()
            if not scored.empty:
                imputed = scored[FEATURES_C].isna().any(axis=1)
                if imputed.any():
                    print("slate: %d game(s) with a missing drive feature filled with 0.0, as in training"
                          % int(imputed.sum()))
                for column in FEATURES_C:
                    scored[column] = scored[column].fillna(0.0)
                state = service.fit(frame, now)
                print("fitted on %d games through %s" % (state["train_games"], state["train_last_date"].date()))
                predictions = service.predict(frame, state, scored)
                unfitted, gaps = [], g2h_effect_gaps(state, scored)
                for season in sorted(set(scored["season"].astype(int))):
                    fitted = team_ratings(state, frame, season)
                    if fitted:
                        rating_rows += fitted
                    else:
                        unfitted.append(season)
                inventory.update(g2h_gaps=gaps, rating_seasons_unfitted=unfitted,
                                 prior_season_only=sorted(scored.loc[scored["home_prior_season_only"]
                                                                     | scored["away_prior_season_only"], "game_id"]),
                                 no_history=sorted(scored.loc[scored["home_no_history"] | scored["away_no_history"],
                                                              "game_id"]))
        date_tag = state["train_last_date"].strftime("%Y%m%d") if state is not None else "none"
        version = "fbs-%s-" + date_tag

        store.begin(con)
        try:
            report = _write_forecast(con, slate, board, predictions, now, days, certified, reason,
                                     rating_rows, version, state, inventory)
            con.commit()
        except Exception as exc:
            con.rollback()
            print("forecast rolled back, nothing written: %r" % exc, file=sys.stderr)
            store.record_run(con, "forecast", "rolled_back", {"error": repr(exc)}, now)
            return {"status": "rolled_back", "error": repr(exc), "projected": 0, "frozen": {}, "missed": {}}
        return {"status": "ok", **report}
    finally:
        con.close()


def run(days: int = 10, db_path: str = store.DEFAULT_DB, now: dt.datetime | None = None) -> dict:
    """Forecast the current slate, then grade history. Each step reports its own status, and a failure
    in one does not stop the other. The result keys stay flat for existing callers."""
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        frame, team_games = service.build_frame(verbose=True, return_team_games=True)
    except service.FBSModelError as exc:
        forecast = {"status": "model_unavailable", "error": str(exc), "projected": 0, "frozen": {}, "missed": {}}
        frame = None
    else:
        try:
            forecast = forecast_step(db_path, days, now, frame, team_games)
        except service.FBSModelError as exc:
            forecast = {"status": "model_error", "error": str(exc), "projected": 0, "frozen": {}, "missed": {}}
    grade = grade_step(db_path, now, frame)
    return {"forecast": forecast, "grade": grade,
            "projected": forecast.get("projected", 0), "frozen": forecast.get("frozen", {}),
            "missed": forecast.get("missed", {}), "lock_risk": forecast.get("lock_risk", []),
            "graded": grade.get("graded", 0), "locks_blocked": forecast.get("locks_blocked"),
            "reason": forecast.get("status")}


FEATURE_OF_TABLE = {
    "fbs_projections": "pregame projections",
    "fbs_game_status": "fixture lifecycle and grading state",
    "fbs_fixture_revisions": "fixture revision history",
    "fbs_window_outcomes": "T-90 window classification",
    "fbs_unresolved": "unresolved and lock-risk queue",
    "fbs_run_reports": "run log",
    "fbs_lock_events": "legacy missed-window events",
    "fbs_ratings": "team ratings",
    "fbs_model_meta": "model metadata",
}


def audit(db_path: str = store.DEFAULT_DB) -> dict:
    """Read-only provenance counts. Never changes the file and never writes a row.

    schema_status is current, migration_required (a legacy schema: the counts that schema supports are returned, and
    each absent table is listed with the feature it would provide) or not_initialized. Each table and column is
    checked before it is queried, so the caller never receives a raw sqlite error for a legacy file.
    """
    report = {"path": db_path, "schema_version_required": store.SCHEMA_VERSION}
    if not os.path.exists(db_path):
        return {**report, "schema_status": "not_initialized", "schema_version": None,
                "unavailable": [{"table": None, "feature": "all", "reason": "database file does not exist"}]}
    con = store.open_db(db_path, readonly=True)
    try:
        state = store.schema_state(con)
        tables = store.user_tables(con)
        report["schema_version"] = con.execute("PRAGMA user_version").fetchone()[0]
        report["schema_status"] = {"current": "current", "legacy": "migration_required",
                                   "empty": "not_initialized"}[state]
        report["unavailable"] = [
            {"table": t, "feature": FEATURE_OF_TABLE.get(t, t), "reason": "table absent in this schema"}
            for t in store.REQUIRED_TABLES if t not in tables]
        for table, column in store.REQUIRED_COLUMNS:
            if table in tables and column not in store.table_columns(con, table):
                report["unavailable"].append({"table": table, "column": column,
                                              "feature": FEATURE_OF_TABLE.get(table, table),
                                              "reason": "column absent in this schema"})
        if "fbs_forecasts" not in tables:
            return report
        columns = store.table_columns(con, "fbs_forecasts")
        count = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
        protocol = "COALESCE(lock_protocol, 'legacy')" if "lock_protocol" in columns else "'legacy'"
        report.update({
            "forecast_rows": count("SELECT COUNT(*) FROM fbs_forecasts"),
            "games": count("SELECT COUNT(DISTINCT game_id) FROM fbs_forecasts"),
            "midnight_utc_kickoff_rows": count(
                "SELECT COUNT(*) FROM fbs_forecasts WHERE kickoff_utc LIKE '%T00:00:00%'"),
            "rows_by_protocol": {row[0]: row[1] for row in con.execute(
                "SELECT %s, COUNT(*) FROM fbs_forecasts GROUP BY 1" % protocol)},
            "late_rows": count("SELECT COUNT(*) FROM fbs_forecasts WHERE late = 1") if "late" in columns else None,
            "graded_rows": count("SELECT COUNT(*) FROM fbs_forecasts WHERE result IS NOT NULL")
            if "result" in columns else None,
        })
        if "lock_protocol" in columns:
            locked = con.execute("SELECT kickoff_utc, locked_at_utc FROM fbs_forecasts "
                                 "WHERE lock_protocol = ?", (store.LOCK_PROTOCOL,)).fetchall()
            report["t90_rows_locked_at_or_after_kickoff"] = sum(
                1 for row in locked
                if store.parse_time(row["locked_at_utc"]) >= store.parse_time(row["kickoff_utc"]))
        if "fbs_projections" in tables:
            report["projection_rows"] = count("SELECT COUNT(*) FROM fbs_projections")
        if "fbs_lock_events" in tables:
            report["missed_lock_events"] = count("SELECT COUNT(*) FROM fbs_lock_events")
        if "fbs_window_outcomes" in tables:
            report["window_outcomes"] = {"%s|%s" % (row[0], row[1] or ""): row[2] for row in con.execute(
                "SELECT outcome, reason, COUNT(*) FROM fbs_window_outcomes GROUP BY 1, 2")}
        return report
    finally:
        con.close()


def grade_only(db_path: str = store.DEFAULT_DB) -> int:
    """Grade due games from ESPN's boards alone. The archive is cross-checked in run()."""
    return grade_step(db_path, dt.datetime.now(dt.timezone.utc), None)["graded"]


def _main(argv=None) -> int:
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
        report = audit(args.db)
        print(json.dumps(report, indent=2, default=str))
        return 0 if report["schema_status"] == "current" else 5
    parser.print_help()
    return 2


def main(argv=None) -> int:
    try:
        return _main(argv)
    except store.SchemaError as exc:
        # Fail closed: the database is untouched. Migration is an explicit, separately authorized command.
        print(str(exc), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
