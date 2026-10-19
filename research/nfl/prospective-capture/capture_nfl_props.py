#!/usr/bin/env python3
"""Freeze NFL prop forecast observations to immutable local artifacts.

The model projection orchestration is imported from nfl_player_projections_job.py;
draws and summaries are imported from nfl_player_projection_v2.py; the forward map
is read and applied through nfl_prop_calibration.py. This harness writes files only.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import hashlib
import json
import math
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import grade_nfl_prop_probabilities as grader  # noqa: E402
import nfl_player_projection_v2 as engine  # noqa: E402
import nfl_player_projections_job as projection_job  # noqa: E402
import nfl_prop_calibration as calibration  # noqa: E402
from capture_validation import SCHEMA_VERSION, validate_row  # noqa: E402


DB_DEFAULT = Path("/root/legendarypicks/backend/data/picks.dev.db")
PARAMETER_FILE = HERE / "parameters/nfl-player-v2-2026-10-19.json"
DRAW_COUNT = 4000
DRAW_SEED = 7
MASS_TOLERANCE = 1e-12
QUERY_VERSION = "nfl-prop-capture-input-v1"

MARKET_TO_STAT = {
    **{market: stat for market, (_index, stat) in grader.RECEIVING.items()},
    **{market: stat for market, (_index, stat) in grader.PASSING.items()},
}
STAT_UNITS = {stat: ("yard" if stat in {"rec_yds", "pass_yds"} else "count") for stat in set(MARKET_TO_STAT.values())}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def jsonl_bytes(rows) -> bytes:
    return b"".join(canonical_json(row) + b"\n" for row in rows)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: Any) -> dt.datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing UTC timestamp: {value!r}")
    text = value.strip().replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp has no timezone: {value!r}")
    return parsed.astimezone(dt.timezone.utc)


def read_only_connection(path: Path) -> sqlite3.Connection:
    if path.resolve() != DB_DEFAULT.resolve() or not path.is_file():
        raise ValueError(f"capture reads only the authorized dev database: {DB_DEFAULT}")
    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    con.execute("BEGIN")
    return con


def frozen_parameters() -> tuple[dict[str, Any], str]:
    raw = PARAMETER_FILE.read_bytes()
    params = json.loads(raw)
    expected = {
        "DEFAULTS": engine.DEFAULTS,
        "DIST": engine.DIST,
        "P_PLAYS": projection_job.P_PLAYS,
        "QB_DEFAULTS": engine.QB_DEFAULTS,
    }
    actual = {
        "DEFAULTS": params["forecast_distribution"]["receiving"]["DEFAULTS"],
        "DIST": params["forecast_distribution"]["receiving"]["DIST"],
        "P_PLAYS": params["forecast_distribution"]["receiving"]["P_PLAYS"],
        "QB_DEFAULTS": params["forecast_distribution"]["passing"]["QB_DEFAULTS"],
    }
    if canonical_json(expected) != canonical_json(actual):
        raise RuntimeError("frozen parameter file differs from the imported model constants")
    return params, sha256_bytes(raw)


def source_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def source_file_hashes() -> dict[str, str]:
    rels = (
        "backend/nfl_player_projections_job.py",
        "backend/nfl_player_projection_v2.py",
        "backend/nfl_prop_calibration.py",
        "backend/routers/players/nfl_projections.py",
    )
    return {rel: sha256_file(ROOT / rel) for rel in rels}


def selected_quote_rows(con: sqlite3.Connection, season: int, weeks: list[int]):
    market_names = sorted(MARKET_TO_STAT)
    query = f"""
        SELECT p.id AS prop_id, p.game_id AS prop_game_pk, p.player_id, p.market, p.line, p.side,
               p.source, p.captured_at, p.odds, p.odds_captured_at,
               pg.id AS prop_game_id, pg.date AS event_date, pg.start_time AS scheduled_start,
               pg.espn_event_id, pg.cancelled_at,
               s.game_id AS nflverse_game_id, s.season, s.week, s.away_team, s.home_team,
               s.away_score, s.home_score, s.espn AS schedule_espn_id
        FROM props p
        JOIN prop_games pg ON pg.id=p.game_id
        JOIN nfl_schedule s ON CAST(s.espn AS TEXT)=CAST(pg.espn_event_id AS TEXT)
        WHERE pg.league='nfl' AND p.source IN ({','.join('?' for _ in grader.BOOKS)})
          AND p.market IN ({','.join('?' for _ in market_names)})
          AND s.season=? AND s.game_type='REG' AND s.week IN ({','.join('?' for _ in weeks)})
          AND p.side IN ('over','under') AND p.player_id IS NOT NULL
        ORDER BY s.week, s.game_id, p.source, p.player_id, p.market, p.line, p.side, p.captured_at, p.id
    """
    rows = [dict(row) for row in con.execute(query, [*grader.BOOKS, *market_names, season, *weeks])]
    latest: dict[tuple, dict] = {}
    quote_after_kickoff = 0
    missing_start = 0
    for row in rows:
        try:
            kickoff = parse_utc(row["scheduled_start"])
            captured = parse_utc(row["captured_at"])
        except ValueError:
            missing_start += 1
            continue
        if captured >= kickoff:
            quote_after_kickoff += 1
            continue
        line = float(row["line"])
        if not math.isfinite(line):
            continue
        row["scheduled_start_utc"] = iso_utc(kickoff)
        row["line"] = line
        key = (row["nflverse_game_id"], int(row["player_id"]), row["market"], row["source"], line, row["side"])
        order = (captured, int(row["prop_id"]))
        previous = latest.get(key)
        if previous is None or order > (parse_utc(previous["captured_at"]), int(previous["prop_id"])):
            latest[key] = row
    by_line: dict[tuple, dict[str, dict]] = collections.defaultdict(dict)
    for key, row in latest.items():
        by_line[key[:-1]][row["side"]] = row
    paired = []
    unpaired_quote_groups = 0
    for key, sides in sorted(by_line.items(), key=lambda item: tuple(str(x) for x in item[0])):
        if set(sides) != {"over", "under"}:
            unpaired_quote_groups += 1
            continue
        paired.append({"key": key, "over": sides["over"], "under": sides["under"]})
    stats = {
        "source_rows_joined_to_slate": len(rows),
        "quotes_at_or_after_kickoff_excluded": quote_after_kickoff,
        "quotes_with_missing_or_invalid_start_excluded": missing_start,
        "unique_side_quotes_before_pairing": len(latest),
        "unpaired_line_groups_excluded": unpaired_quote_groups,
        "paired_line_observations": len(paired),
    }
    return paired, stats


def source_snapshot_rows(con: sqlite3.Connection, season: int, weeks: list[int], paired_quotes: list[dict]):
    yield {"record_type": "header", "schema_version": "nfl-prop-input-snapshot.v1", "query_version": QUERY_VERSION,
           "season": season, "weeks": weeks, "model_input_seasons": [season - 1, season]}
    queries = (
        ("players", "SELECT id,name,team,league,espn_id,nfl_gsis_id,position,publisher,publisher_id FROM players WHERE league='nfl' ORDER BY id"),
        ("nfl_schedule", "SELECT game_id,season,game_type,week,gameday,gametime,away_team,home_team,away_score,home_score,espn,source,ingested_at FROM nfl_schedule WHERE season IN (?,?) ORDER BY season,week,game_id"),
        ("player_game_logs", "SELECT player_id,season,game_id,team,stats,source,game_type FROM player_game_logs WHERE league='nfl' AND season IN (?,?) AND source='nflverse_weekly' AND (game_type='REG' OR game_type IS NULL) AND team IS NOT NULL AND game_id IS NOT NULL ORDER BY season,game_id,player_id"),
        ("player_game_availability", "SELECT season,week,game_id,team,player_id,played,report_status,source,built_at FROM player_game_availability WHERE league='nfl' AND season IN (?,?) ORDER BY season,week,game_id,team,player_id"),
        ("nfl_prop_calibration", "SELECT season,week,model_version,a,b,n_items,n_player_games,fitted_at_utc FROM nfl_prop_calibration WHERE season=? AND week IN (%s) ORDER BY week,model_version" % ",".join("?" for _ in weeks)),
    )
    for table, query in queries:
        if table in {"nfl_schedule", "player_game_logs", "player_game_availability"}:
            params = (season - 1, season)
        elif table == "nfl_prop_calibration":
            params = (season, *weeks)
        else:
            params = ()
        for row in con.execute(query, params):
            yield {"record_type": "table_row", "table": table, "values": list(row)}

    quote_ids = sorted({int(q[side]["prop_id"]) for q in paired_quotes for side in ("over", "under")})
    if quote_ids:
        for start in range(0, len(quote_ids), 400):
            chunk = quote_ids[start:start + 400]
            marks = ",".join("?" for _ in chunk)
            query = f"SELECT id,game_id,player_id,market,line,side,source,captured_at,odds,odds_captured_at FROM props WHERE id IN ({marks}) ORDER BY id"
            for row in con.execute(query, chunk):
                yield {"record_type": "table_row", "table": "props", "values": list(row)}
            query = f"SELECT prop_id,actual_value,hit,settled_at FROM prop_results WHERE prop_id IN ({marks}) ORDER BY prop_id"
            for row in con.execute(query, chunk):
                yield {"record_type": "table_row", "table": "prop_results", "values": list(row)}


def load_box_scores(con: sqlite3.Connection, season: int):
    values: dict[tuple[int, str], dict[str, Any]] = {}
    for pid, game_id, stats in con.execute(
        "SELECT player_id,game_id,stats FROM player_game_logs WHERE league='nfl' AND season=? "
        "AND source='nflverse_weekly' AND (game_type='REG' OR game_type IS NULL) "
        "AND team IS NOT NULL AND game_id IS NOT NULL", (season,)
    ):
        if pid is None:
            # History.load resolves positions first; rows with no canonical id are not forecast inputs.
            continue
        key = (int(pid), str(game_id))
        if key in values:
            raise RuntimeError(f"duplicate nflverse player-game log for {key}")
        values[key] = json.loads(stats)
    return values


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _BackfillScheduleView:
    """Override only the final-score columns so the imported job evaluates past games."""

    def __init__(self, con):
        self.con = con

    def execute(self, sql, params=()):
        compact = " ".join(sql.split()).lower()
        if compact.startswith("select game_id, away_team, home_team, home_score, away_score from nfl_schedule"):
            rows = self.con.execute(sql, params).fetchall()
            return _Rows([tuple(row[:3]) + (None, None) for row in rows])
        return self.con.execute(sql, params)


def imported_projection_entries(con: sqlite3.Connection, season: int, weeks: list[int], backfill: bool):
    history = engine.History.load(con, [season - 1, season])
    view = _BackfillScheduleView(con) if backfill else con
    entries = []
    summaries = {}
    for week in weeks:
        # The capture consumes the job's analytical means only. Quantiles from this auxiliary
        # call are discarded; the artifact PMF uses the endpoint's exact 4,000-draw settings.
        week_entries, summary = projection_job.project_week(con=view, season=season, week=week, n_sims=1, hist=history)
        entries.extend(week_entries)
        summaries[str(week)] = summary
    return history, entries, summaries


def distribution_for_entry(entry: dict):
    base = entry["scenarios"].get("base", {})
    if {"tgt", "rec", "rec_yds", "rec_td"}.issubset(base):
        tgt, rec, yards, td = (float(base[s][0]) for s in ("tgt", "rec", "rec_yds", "rec_td"))
        if tgt <= 0:
            return None
        draws = engine.simulate(tgt, rec / tgt, yards / rec if rec > 0 else 0.0, td / tgt,
                                n=DRAW_COUNT, seed=DRAW_SEED)
        return {"draws": draws, "indexes": {"rec": 0, "rec_yds": 1, "rec_td": 2, "tgt": 3},
                "entry": entry, "model_family": "receiving"}
    if {"att", "cmp", "pass_yds", "pass_td"}.issubset(base):
        att, cmp_, yards, td = (float(base[s][0]) for s in ("att", "cmp", "pass_yds", "pass_td"))
        if att <= 0:
            return None
        draws = engine.simulate_qb(att, cmp_ / att, yards / cmp_ if cmp_ > 0 else 0.0, td / att,
                                   n=DRAW_COUNT, seed=DRAW_SEED)
        return {"draws": draws, "indexes": {"cmp": 0, "pass_yds": 1, "pass_td": 2, "att": 3},
                "entry": entry, "model_family": "passing"}
    raise RuntimeError(f"projection entry has no recognized distribution: {entry['game_id']}/{entry['player_id']}")


def integerize(stat: str, value: float) -> int:
    if stat in {"rec_yds", "pass_yds"}:
        if value < 0:
            raise ValueError(f"negative simulated yards for {stat}: {value}")
        return math.floor(value)
    integer = int(value)
    if integer != value or integer < 0:
        raise ValueError(f"non-integer or negative simulated count for {stat}: {value}")
    return integer


def empirical_pmf(stat: str, draws, draw_index: int):
    integer_draws = [integerize(stat, float(draw[draw_index])) for draw in draws]
    maximum = max(integer_draws)
    counts = collections.Counter(integer_draws)
    probabilities = [counts.get(value, 0) / len(integer_draws) for value in range(maximum + 1)]
    total = math.fsum(probabilities)
    return {
        "method": "empirical_monte_carlo_integerized",
        "sample_count": len(integer_draws),
        "sample_seed": DRAW_SEED,
        "support": {"min": 0, "max": maximum, "integer": True, "units": STAT_UNITS[stat]},
        "probabilities": probabilities,
        "endpoint_mass": {"at_min": probabilities[0], "at_max": probabilities[-1]},
        "tail_mass": {
            "below_support": 0.0,
            "above_support": 0.0,
            "semantics": "tail mass of the finite empirical draw distribution; unsampled analytic model tail is not estimated",
        },
        "truncation": {
            "draws_outside_support": 0,
            "clipped_draws": 0,
            "overflow_bucket": None,
            "support_rule": "0 through the largest integerized value in the complete draw sample",
            "yardage_integerization": "floor nonnegative Gamma draw; count outcomes are already integers",
        },
        "renormalization": {"applied": False, "factor": 1.0},
        "mass_sum": total,
        "mass_tolerance": MASS_TOLERANCE,
    }


def pmf_probabilities(pmf: dict, line: float):
    support = pmf["support"]
    probabilities = pmf["probabilities"]
    below = push = above = 0.0
    for value, probability in enumerate(probabilities, start=support["min"]):
        if value < line:
            below += probability
        elif value > line:
            above += probability
        else:
            push += probability
    return {"under": below, "push": push, "over": above}


def result_fields(history, box_scores, quote: dict, entry: dict, outcome_rows: dict, backfill: bool, side: str):
    row = quote[side]
    event_id = row["nflverse_game_id"]
    pid = int(row["player_id"])
    team = entry["team"]
    status = history.status.get((int(row["season"]), event_id, team), {}).get(pid)
    played = status[1] if status else None
    schedule_final = row["home_score"] is not None and row["away_score"] is not None
    if row["cancelled_at"]:
        return "void", "void", None, "prop_games.cancelled_at", None
    if not schedule_final and not backfill:
        return "unresolved", "unresolved", None, None, None
    if not schedule_final and backfill:
        raise RuntimeError(f"backfill target not final: {event_id}")
    raw = box_scores.get((pid, event_id))
    stat = MARKET_TO_STAT[row["market"]]
    json_key = {"tgt": "targets"}.get(stat, stat)
    if raw is None:
        if played == 0:
            return "dnp", "dnp", None, "player_game_availability.played=0", None
        return "missing", "missing", None, "nflverse_weekly:no_player_game_log", None
    if json_key not in raw or raw[json_key] is None:
        return "missing", "missing", None, "nflverse_weekly:no_stat", None
    actual = float(raw[json_key])
    actual_value = int(actual) if actual.is_integer() else actual
    if actual == 0:
        outcome_state = "true_zero"
    else:
        outcome_state = "resolved"
    line = float(row["line"])
    if abs(actual - line) <= 1e-9:
        settlement = "push"
    elif (side == "over" and actual > line) or (side == "under" and actual < line):
        settlement = "win"
    else:
        settlement = "loss"
    prop_result = outcome_rows.get(int(row["prop_id"]))
    return outcome_state, settlement, actual_value, "player_game_logs:nflverse_weekly", prop_result


def market_mapping_record(market: str):
    index, stat = (grader.RECEIVING.get(market) or grader.PASSING[market])
    return index, stat


def build_observation(quote: dict, side: str, distribution: dict, history, box_scores, outcome_rows,
                      generated_at: dt.datetime, info_cutoff: dt.datetime, mode: str,
                      model_sha: str, params_sha: str, input_sha: str, source_files: dict,
                      capture_sha: str, calibration_by_week: dict, player_meta: dict):
    event_id, pid, market, book, line = quote["key"]
    over_row, under_row = quote["over"], quote["under"]
    stat = MARKET_TO_STAT[market]
    index = distribution["indexes"][stat]
    draws = distribution["draws"]
    pmf_cache = distribution.setdefault("pmf_cache", {})
    if stat not in pmf_cache:
        pmf_cache[stat] = empirical_pmf(stat, draws, index)
    pmf = pmf_cache[stat]
    line_key = float(line)
    line_probability_cache = distribution.setdefault("line_probability_cache", {}).setdefault(stat, {})
    if line_key not in line_probability_cache:
        # This is the same imported engine call used by the player projection endpoint.
        route_summary = engine.summarize(draws, index, line_key)
        line_probability_cache[line_key] = float(route_summary["p_over"])
    raw_p_over = line_probability_cache[line_key]
    pmf_probability_cache = distribution.setdefault("pmf_probability_cache", {}).setdefault(stat, {})
    if line_key not in pmf_probability_cache:
        pmf_probability_cache[line_key] = pmf_probabilities(pmf, line_key)
    pmf_prob = pmf_probability_cache[line_key]
    calrow = calibration_by_week.get(int(over_row["week"]))
    if calrow:
        calibrated_p_over = float(calibration.apply_map(calrow["a"], calrow["b"], raw_p_over))
        calibration_info = {
            "model_version": "v2-platt",
            "status": "applied",
            "a": float(calrow["a"]), "b": float(calrow["b"]),
            "n_items": calrow["n_items"], "n_player_games": calrow["n_player_games"],
            "fitted_at_utc": calrow["fitted_at_utc"],
            "function": "nfl_prop_calibration.apply_map",
            "epsilon": calibration.EPS,
        }
    else:
        calibrated_p_over = raw_p_over
        calibration_info = {"model_version": "v2-platt", "status": "raw_no_map", "function": "nfl_prop_calibration.read"}
    if mode == "backfill":
        proof = {
            "status": "not_prospective",
            "available_before_cutoff": False,
            "asserted_at": iso_utc(generated_at),
            "scheduled_start_utc": over_row["scheduled_start_utc"],
            "basis": "Forecast reconstructed after kickoff from a current dev database containing postgame outcomes; never CP4 evidence.",
        }
        cp4_eligible = False
    else:
        proof = {
            "status": "verified",
            "available_before_cutoff": True,
            "asserted_at": iso_utc(generated_at),
            "scheduled_start_utc": over_row["scheduled_start_utc"],
            "basis": "Capture process and read transaction started before scheduled kickoff; all source reads are frozen in the attached input snapshot.",
        }
        cp4_eligible = True
    outcome_state, settlement_state, actual_value, outcome_source, book_result = result_fields(
        history, box_scores, quote, distribution["entry"], outcome_rows, mode == "backfill", side)
    start = parse_utc(over_row["scheduled_start"])
    player = player_meta.get(pid, {})
    away, home = over_row["away_team"], over_row["home_team"]
    team = distribution["entry"]["team"]
    if team == away:
        opponent = home
    elif team == home:
        opponent = away
    else:
        raise RuntimeError(f"projection team {team} is not a scheduled team in {event_id}")
    player_source_ids = {
        "nfl_gsis_id": player.get("nfl_gsis_id"),
        "espn_id": player.get("espn_id"),
        "publisher": player.get("publisher"),
        "publisher_id": player.get("publisher_id"),
    }
    observation_natural_key = {
        "league": "nfl", "season": int(over_row["season"]), "event_id": event_id,
        "player_id": pid, "market": market, "line": float(line), "side": side, "book": book,
        "lock_time": iso_utc(start), "capture_run_id": f"nfl-{int(over_row['season'])}-w{int(over_row['week']):02d}-{mode}",
    }
    obs_id = sha256_bytes(canonical_json(observation_natural_key))
    mode_label = "backfill" if mode == "backfill" else "live"
    quote_row = over_row if side == "over" else under_row
    opposite_row = under_row if side == "over" else over_row
    selected_odds = quote_row["odds"]
    paired_odds = opposite_row["odds"]
    book_hit = book_actual = book_settled_at = None
    if book_result:
        book_actual = book_result["actual_value"]
        book_hit = book_result["hit"]
        book_settled_at = book_result["settled_at"]
    forecast_label = "v2-platt" if calibration_info["status"] == "applied" else "v2"
    calibrated_side_probability = (calibrated_p_over if over_row["side"] == "over" else None)
    source_commit_hash = model_sha
    record = {
        "schema_version": SCHEMA_VERSION,
        "observation_id": obs_id,
        "capture_run_id": observation_natural_key["capture_run_id"],
        "capture_mode": mode_label,
        "cp4_evidence_eligible": cp4_eligible,
        "league": "nfl",
        "competition": "REG",
        "season": int(over_row["season"]),
        "event": {
            "id": str(event_id),
            "event_date": over_row["event_date"],
            "week": int(over_row["week"]),
            "scheduled_start_utc": iso_utc(start),
            "source_ids": {"nflverse_game_id": str(event_id), "espn_event_id": str(over_row["espn_event_id"]),
                           "prop_game_id": int(over_row["prop_game_id"])},
            "home_team_id": home,
            "away_team_id": away,
        },
        "player": {
            "id": pid,
            "identity_state": "resolved",
            "identity_resolution": "props.player_id -> canonical players.id; NFLGSIS/ESPN source ids retained below",
            "source_ids": player_source_ids,
            "team_id": team,
            "opponent_id": opponent,
            "position": distribution["entry"]["pos"],
        },
        "market": {
            "provider_market": market,
            "stat": stat,
            "units": STAT_UNITS[stat],
            "integer_support": {"minimum": 0, "maximum": pmf["support"]["max"], "integer": True},
        },
        "line": float(line),
        "side": side,
        "book": book,
        "quote": {
            "source": book,
            "prop_id": int(quote_row["prop_id"]),
            "opposite_prop_id": int(opposite_row["prop_id"]),
            "captured_at": quote_row["captured_at"],
            "opposite_captured_at": opposite_row["captured_at"],
            "odds_american": selected_odds,
            "opposite_odds_american": paired_odds,
        },
        "model_name": "nfl-player-v2",
        "model_version": "v2",
        "forecast_label": forecast_label,
        "p_plays": float(distribution["entry"]["p_plays"]),
        "conditional_on_playing": True,
        "forecast_created_at": iso_utc(generated_at),
        "information_cutoff": iso_utc(info_cutoff),
        "lock_time": iso_utc(start),
        "pre_kickoff_assertion": proof,
        "forecast_probability": {
            "p_over_raw": raw_p_over,
            "p_over_served_4dp": round(raw_p_over, 4),
            "p_over_v2_platt": calibrated_p_over,
            "p_over_v2_platt_4dp": round(calibrated_p_over, 4),
            "p_side_from_integer_pmf": pmf_prob[side],
            "p_push_from_integer_pmf": pmf_prob["push"],
            "calibration": calibration_info,
            "note": "v2-platt calibrates the scalar P(over); it does not transform or replace the saved v2 PMF.",
        },
        "pmf": pmf,
        "outcome_state": outcome_state,
        "settlement_state": settlement_state,
        "actual_value": actual_value,
        "outcome_source": outcome_source,
        "book_settlement": {"actual_value": book_actual, "hit": book_hit, "settled_at": book_settled_at},
        "source_commit": source_commit_hash,
        "source_file_sha256": source_files,
        "source_patch_sha256": None,
        "parameter_file": str(PARAMETER_FILE.relative_to(ROOT)),
        "parameter_file_sha256": params_sha,
        "input_snapshot_sha256": input_sha,
        "capture_harness_sha256": capture_sha,
        "capture_provenance": {
            "pmf_model_version": "v2",
            "forecast_generation": "nfl_player_projections_job.project_week",
            "draw_function": "nfl_player_projection_v2.simulate" if distribution["model_family"] == "receiving" else "nfl_player_projection_v2.simulate_qb",
            "summary_function": "nfl_player_projection_v2.summarize",
            "draw_count": DRAW_COUNT,
            "seed": DRAW_SEED,
            "yardage_integerization": "floor nonnegative simulated yards for the integer support; exact route P(over) is separately retained from raw engine draws",
            "source": "reconstructed historical backfill; never prospective" if mode_label == "backfill" else "frozen live capture",
        },
    }
    return record


def snapshot_artifact(con, season: int, weeks: list[int], paired_quotes: list[dict]):
    row_iter = source_snapshot_rows(con, season, weeks, paired_quotes)
    raw = b"".join(canonical_json(row) + b"\n" for row in row_iter)
    compressed = gzip.compress(raw, compresslevel=1, mtime=0)
    # JSONL records are newline-delimited; the header and each selected source row have one record.
    return raw, compressed, raw.count(b"\n")


def immutable_write(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == payload:
            return "already-present-identical"
        raise FileExistsError(f"refusing to mutate frozen artifact: {path}")
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.link(temp, path)
        return "created"
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def existing_frozen_run(directory: Path, run_ids: set[str]):
    if not directory.exists():
        return None
    for path in sorted(directory.glob("*.jsonl.gz")):
        if "input-snapshot" in path.name:
            continue
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if line.strip() and json.loads(line).get("capture_run_id") in run_ids:
                    return path
    return None


def load_book_results(con, paired_quotes):
    ids = sorted({int(q[side]["prop_id"]) for q in paired_quotes for side in ("over", "under")})
    out = {}
    for offset in range(0, len(ids), 400):
        chunk = ids[offset:offset + 400]
        if not chunk:
            continue
        marks = ",".join("?" for _ in chunk)
        for prop_id, actual_value, hit, settled_at in con.execute(
            f"SELECT prop_id,actual_value,hit,settled_at FROM prop_results WHERE prop_id IN ({marks})", chunk
        ):
            out[int(prop_id)] = {"actual_value": actual_value, "hit": hit, "settled_at": settled_at}
    return out


def generate(args) -> int:
    mode = args.mode
    weeks = [int(x) for x in (args.weeks.split(",") if args.weeks else [str(args.week)])]
    weeks = sorted(set(weeks))
    if not weeks or any(w < 1 or w > 18 for w in weeks):
        raise ValueError("weeks must be NFL regular-season weeks 1..18")
    if mode == "live" and (len(weeks) != 1 or args.weeks):
        raise ValueError("live mode accepts exactly one --week")
    output = args.output.resolve()
    snapshot_path = args.input_snapshot.resolve()
    manifest_path = args.manifest.resolve()
    mode_dir = (HERE / mode).resolve()
    if any(path.parent != mode_dir for path in (output, snapshot_path, manifest_path)):
        raise ValueError(f"all immutable {mode} artifacts must be direct children of {mode_dir}")
    if output.exists():
        print(f"idempotent no-op: frozen artifact already exists and was not modified: {output}")
        return 0
    if manifest_path.exists():
        raise FileExistsError(f"refusing to replace an existing manifest without its frozen artifact: {manifest_path}")
    run_ids = {f"nfl-{args.season}-w{week:02d}-{mode}" for week in weeks}
    existing = existing_frozen_run(mode_dir, run_ids)
    if existing:
        print(f"idempotent no-op: immutable observation rows already exist in {existing}; no duplicate written")
        return 0

    db_path = args.db.resolve()
    con = read_only_connection(db_path)
    started_at = utc_now()
    info_cutoff = started_at
    try:
        params, params_sha = frozen_parameters()
        source_sha = source_commit()
        if not source_sha or len(source_sha) != 40:
            raise RuntimeError(f"could not resolve full source commit SHA: {source_sha!r}")
        source_files = source_file_hashes()
        capture_sha = sha256_file(Path(__file__).resolve())
        paired_quotes, quote_stats = selected_quote_rows(con, args.season, weeks)
        min_lock = None
        if mode == "live":
            starts = [parse_utc(q["over"]["scheduled_start"]) for q in paired_quotes]
            if not starts:
                raise RuntimeError("no paired sportsbook quotes found for the requested live week")
            if any(started_at >= start for start in starts):
                raise RuntimeError("live capture began at or after at least one scheduled kickoff")
            min_lock = min(starts)
        raw_snapshot, compressed_snapshot, snapshot_row_count = snapshot_artifact(con, args.season, weeks, paired_quotes)
        input_sha = sha256_bytes(raw_snapshot)
        info_cutoff = utc_now()
        if mode == "live" and (min_lock is None or info_cutoff >= min_lock):
            raise RuntimeError("live input snapshot completed at or after scheduled kickoff")
        player_meta = {
            int(row["id"]): dict(row)
            for row in con.execute("SELECT id,name,team,espn_id,nfl_gsis_id,position,publisher,publisher_id FROM players WHERE league='nfl'")
        }
        history, entries, week_summaries = imported_projection_entries(con, args.season, weeks, mode == "backfill")
        box_scores = load_box_scores(con, args.season)
        outcome_rows = load_book_results(con, paired_quotes)
        calibration_by_week = {}
        for week in weeks:
            mapping = calibration.read(con, args.season, week, "v2-platt")
            if mapping is None:
                continue
            row = con.execute(
                "SELECT a,b,n_items,n_player_games,fitted_at_utc FROM nfl_prop_calibration "
                "WHERE season=? AND week=? AND model_version='v2-platt'", (args.season, week)
            ).fetchone()
            if row:
                calibration_by_week[week] = {
                    "a": float(row[0]), "b": float(row[1]), "n_items": row[2],
                    "n_player_games": row[3], "fitted_at_utc": row[4],
                }

        records = []
        excluded_no_projection = collections.Counter()
        entries_by_key = {}
        for entry in entries:
            key = (str(entry["game_id"]), int(entry["player_id"]))
            if key in entries_by_key:
                raise RuntimeError(f"duplicate projection entry for {key}")
            entries_by_key[key] = entry
        quotes_by_key: dict[tuple[str, int], list[dict]] = collections.defaultdict(list)
        for quote in paired_quotes:
            quotes_by_key[(str(quote["key"][0]), int(quote["key"][1]))].append(quote)
        for key, player_quotes in sorted(quotes_by_key.items()):
            entry = entries_by_key.get(key)
            if entry is None:
                for quote in player_quotes:
                    excluded_no_projection[(quote["key"][2], quote["key"][3])] += 1
                continue
            base_stats = entry["scenarios"].get("base", {})
            eligible_quotes = [q for q in player_quotes if MARKET_TO_STAT[q["key"][2]] in base_stats]
            for quote in player_quotes:
                if MARKET_TO_STAT[quote["key"][2]] not in base_stats:
                    excluded_no_projection[(quote["key"][2], quote["key"][3])] += 1
            if not eligible_quotes:
                continue
            distribution = distribution_for_entry(entry)
            if distribution is None:
                for quote in eligible_quotes:
                    excluded_no_projection[(quote["key"][2], quote["key"][3])] += 1
                continue
            for quote in eligible_quotes:
                for side in ("over", "under"):
                    records.append(build_observation(
                        quote, side, distribution, history, box_scores, outcome_rows, started_at, info_cutoff,
                        mode, source_sha, params_sha, input_sha, source_files,
                        capture_sha, calibration_by_week, player_meta,
                    ))
        records.sort(key=lambda r: (r["season"], r["event"]["id"], r["player"]["id"], r["market"]["provider_market"], r["book"], r["line"], r["side"]))
        if not records:
            raise RuntimeError("capture produced no forecast observations")
        duplicate_ids = [obs for obs, count in collections.Counter(r["observation_id"] for r in records).items() if count > 1]
        if duplicate_ids:
            raise RuntimeError(f"capture produced duplicate observation ids: {duplicate_ids[:3]}")

        frozen_at = utc_now()
        if mode == "live" and (min_lock is None or frozen_at >= min_lock):
            raise RuntimeError("live forecasts finished after a scheduled kickoff; no forecast artifact written")
        for record in records:
            record["forecast_created_at"] = iso_utc(frozen_at)
            record["pre_kickoff_assertion"]["asserted_at"] = iso_utc(frozen_at)
            errors = validate_row(record)
            if errors:
                raise ValueError(f"capture generated invalid observation {record['observation_id']}: {'; '.join(errors)}")

        raw_artifact = jsonl_bytes(records)
        compressed_artifact = gzip.compress(raw_artifact, compresslevel=1, mtime=0)
        if mode == "live" and (min_lock is None or utc_now() >= min_lock):
            raise RuntimeError("live artifact serialization crossed scheduled kickoff; no forecast artifact written")
        artifact_sha = sha256_bytes(compressed_artifact)
        snapshot_write = immutable_write(snapshot_path, compressed_snapshot)
        out_write = immutable_write(output, compressed_artifact)
        outcome_counts = dict(collections.Counter(r["outcome_state"] for r in records))
        settlement_counts = dict(collections.Counter(r["settlement_state"] for r in records))
        rows_by_week = dict(collections.Counter(r["event"]["week"] for r in records))
        rows_by_market = dict(collections.Counter(r["market"]["provider_market"] for r in records))
        rows_by_book = dict(collections.Counter(r["book"] for r in records))
        manifest = {
            "schema_version": "nfl-prop-capture-manifest.v1",
            "capture_mode": mode,
            "capture_run_id": records[0]["capture_run_id"],
            "cp4_evidence_eligible": mode == "live",
            "season": args.season,
            "weeks": weeks,
            "created_at_utc": iso_utc(frozen_at),
            "source_database": str(db_path),
            "database_access": "SQLite mode=ro; PRAGMA query_only=ON; a read transaction pins one source snapshot; no DB writes",
            "forecast_artifact": display_path(output),
            "forecast_artifact_sha256_compressed": artifact_sha,
            "forecast_artifact_sha256_uncompressed": sha256_bytes(raw_artifact),
            "forecast_row_count": len(records),
            "forecast_line_items": len(records) // 2,
            "input_snapshot": display_path(snapshot_path),
            "input_snapshot_sha256_uncompressed": input_sha,
            "input_snapshot_sha256_compressed": sha256_bytes(compressed_snapshot),
            "input_snapshot_row_count": snapshot_row_count,
            "input_snapshot_query_version": QUERY_VERSION,
            "source_commit": source_sha,
            "source_files_sha256": source_files,
            "source_patch_sha256": None,
            "parameter_file": str(PARAMETER_FILE.relative_to(ROOT)),
            "parameter_file_sha256": params_sha,
            "capture_harness_sha256": capture_sha,
            "frozen_parameters": params,
            "quote_population": {
                "markets": sorted(MARKET_TO_STAT),
                "books": list(grader.BOOKS),
                "side_policy": "latest pre-kickoff over and under quote for each event/player/market/book/line; one output row per side",
                "integer_line_policy": "retained; push is represented explicitly",
                "no_carries_candidate": True,
                **quote_stats,
            },
            "model_projection_summary_by_week": week_summaries,
            "projection_player_game_count": len(entries),
            "projection_job_quantile_draws": 1,
            "projection_job_quantile_draws_note": "Only analytical means are consumed from project_week; its auxiliary quantiles are discarded. The saved PMF uses the API's 4,000 draws and seed 7.",
            "paired_quote_groups_without_a_model_projection": sum(excluded_no_projection.values()),
            "unmatched_quote_groups_by_market_book": [
                {"market": m, "book": b, "count": n} for (m, b), n in sorted(excluded_no_projection.items())
            ],
            "outcome_state_counts": outcome_counts,
            "settlement_state_counts": settlement_counts,
            "observation_rows_by_week": rows_by_week,
            "observation_rows_by_market": rows_by_market,
            "observation_rows_by_book": rows_by_book,
            "backfill_disclaimer": "A historical harness run is reconstructed after kickoff and is never CP4 evidence." if mode == "backfill" else None,
            "writes": [str(output), str(snapshot_path), str(manifest_path)],
        }
        manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        manifest_write = immutable_write(manifest_path, manifest_bytes)
        print(f"capture mode={mode}; season={args.season}; weeks={weeks}")
        print(f"model projection player-games={len(entries)}; matched line items={len(records)//2}; observation rows={len(records)}")
        print(f"outcomes={json.dumps(outcome_counts, sort_keys=True)}")
        print(f"settlements={json.dumps(settlement_counts, sort_keys=True)}")
        print(f"input snapshot rows={snapshot_row_count}; sha256={input_sha}")
        print(f"artifact sha256={artifact_sha}; path={output}")
        print(f"immutable writes: input={snapshot_write}, forecast={out_write}, manifest={manifest_write}")
        return 0
    finally:
        con.rollback()
        con.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("live", "backfill"), required=True)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--week", type=int)
    ap.add_argument("--weeks", help="comma-separated weeks; backfill only")
    ap.add_argument("--db", type=Path, default=DB_DEFAULT)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--input-snapshot", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    args = ap.parse_args(argv)
    if (args.week is None) == (args.weeks is None):
        ap.error("provide exactly one of --week or --weeks")
    if args.mode == "backfill" and not args.weeks:
        ap.error("backfill mode requires --weeks")
    if args.mode == "live" and args.weeks:
        ap.error("live mode does not accept --weeks")
    return generate(args)


if __name__ == "__main__":
    raise SystemExit(main())
