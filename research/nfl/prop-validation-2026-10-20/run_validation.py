#!/usr/bin/env python3
"""NFL player-market distribution validation, per market, 2026-10-20.

Research only. Read-only on every database and frozen artifact. Writes only under this directory.

What this reproduces, per market:
  1. Reproducibility. Re-derives the frozen v2 PMF for every player-game in the 2026 weeks 4-5
     capture backfill from the frozen input snapshot + the committed engine, and compares the
     integer PMF and the continuous-draw P(over) byte-for-byte.
  2. Distribution integrity. Randomized PIT, observed/predicted variance ratio, central-interval
     coverage at 50/80/90%, log score and discrete CRPS, from the frozen PMFs.
  3. Baselines on identical player-games: trailing-5-game empirical distribution and the
     position-level league distribution.  Scored the same way.
  4. Market comparison. Proportional de-vig of the frozen over/under quotes, Brier and log loss on
     identical line items, paired player-game-clustered bootstrap.
  5. A 2025 walk-forward pass (weeks 3-18, constants frozen on 2024) for the markets that have no
     2026 sportsbook lines: targets, carries, rushing yards, rushing TDs and receiving TDs.

Inputs (read-only):
  * frozen capture artifact and input snapshot (paths below)
  * frozen parameter file
  * committed engine backend/nfl_player_projection_v2.py and backend/nfl_player_projections_job.py
  * the dev database, read-only, only for the 2025 walk-forward pass

Outputs (written here):
  metrics_2026.json, metrics_2025.json, reproducibility_2026.json,
  per_market_coverage.csv, frozen_predictions_2026.csv, manifest.json

Usage:
  python3 run_validation.py                 # everything
  python3 run_validation.py --skip-2025     # 2026 capture artifact only
"""

from __future__ import annotations

import argparse
import collections
import csv
import gzip
import hashlib
import json
import math
import os
import random
import sqlite3
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

import nfl_player_projection_v2 as eng  # noqa: E402
import nfl_player_projections_job as job  # noqa: E402

CAPTURE = Path("/root/lp-nfl-capture/research/nfl/prospective-capture")
ARTIFACT = CAPTURE / "backfill/nfl-2026-w03-w05.jsonl.gz"
SNAPSHOT = CAPTURE / "backfill/nfl-2026-w03-w05-input-snapshot.jsonl.gz"
PARAMETERS = CAPTURE / "parameters/nfl-player-v2-2026-10-19.json"
MANIFEST = CAPTURE / "backfill/nfl-2026-w03-w05-manifest.json"
DEV_DB = Path("/root/legendarypicks/backend/data/picks.dev.db")

DRAW_COUNT = 4000
DRAW_SEED = 7
COVERAGE_LEVELS = (0.50, 0.80, 0.90)
PIT_BINS = 10

# provider market -> (stat, units, family)
MARKET_STAT = {
    "passing_yards": ("pass_yds", "yard", "passing"),
    "pass_attempts": ("att", "count", "passing"),
    "pass_completions": ("cmp", "count", "passing"),
    "passing_touchdowns": ("pass_td", "count", "passing"),
    "receiving_yards": ("rec_yds", "yard", "receiving"),
    "receptions": ("rec", "count", "receiving"),
    "targets": ("tgt", "count", "receiving"),
    "receiving_touchdowns": ("rec_td", "count", "receiving"),
    "rushing_yards": ("rush_yds", "yard", "rushing"),
    "carries": ("car", "count", "rushing"),
    "rushing_touchdowns": ("rush_td", "count", "rushing"),
}
STAT_UNITS = {v[0]: v[1] for v in MARKET_STAT.values()}
RECEIVING_STATS = ("tgt", "rec", "rec_yds", "rec_td")
PASSING_STATS = ("att", "cmp", "pass_yds", "pass_td")
RUSHING_STATS = ("car", "rush_yds", "rush_td")
RECV_IDX = {"rec": 0, "rec_yds": 1, "rec_td": 2, "tgt": 3}
PASS_IDX = {"cmp": 0, "pass_yds": 1, "pass_td": 2, "att": 3}
# engine Row attribute -> provider stat names
LOG_KEYS = {"tgt": "targets", "rec": "rec", "rec_yds": "rec_yds", "rec_td": "rec_td",
            "car": "carries", "rush_yds": "rush_yds", "rush_td": "rush_td",
            "att": "att", "cmp": "cmp", "pass_yds": "pass_yds", "pass_td": "pass_td"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ------------------------------------------------------------------------------------------------
# in-memory database reconstructed from the frozen input snapshot
# ------------------------------------------------------------------------------------------------

SNAPSHOT_SCHEMA = {
    "players": ("id,name,team,league,espn_id,nfl_gsis_id,position,publisher,publisher_id", 9),
    "nfl_schedule": ("game_id,season,game_type,week,gameday,gametime,away_team,home_team,"
                     "away_score,home_score,espn,source,ingested_at", 13),
    "player_game_logs": ("player_id,season,game_id,team,stats,source,game_type,league", 7),
    "player_game_availability": ("season,week,game_id,team,player_id,played,report_status,source,"
                                 "built_at,league", 9),
    "nfl_prop_calibration": ("season,week,model_version,a,b,n_items,n_player_games,fitted_at_utc", 8),
    "props": ("id,game_id,player_id,market,line,side,source,captured_at,odds,odds_captured_at", 10),
    "prop_results": ("prop_id,actual_value,hit,settled_at", 4),
}


def load_snapshot_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    statements = []
    for table, (cols, ncols) in SNAPSHOT_SCHEMA.items():
        statements.append("CREATE TABLE %s(%s)" % (table, cols))
    con.executescript(";\n".join(statements))
    insert = {
        "players": "INSERT INTO players VALUES(%s)" % ",".join("?" * 9),
        "nfl_schedule": "INSERT INTO nfl_schedule VALUES(%s)" % ",".join("?" * 13),
        "player_game_logs": "INSERT INTO player_game_logs(player_id,season,game_id,team,stats,source,"
                            "game_type,league) VALUES(?,?,?,?,?,?,?,'nfl')",
        "player_game_availability": "INSERT INTO player_game_availability(season,week,game_id,team,"
                                    "player_id,played,report_status,source,built_at,league) "
                                    "VALUES(?,?,?,?,?,?,?,?,?,'nfl')",
        "nfl_prop_calibration": "INSERT INTO nfl_prop_calibration VALUES(%s)" % ",".join("?" * 8),
        "props": "INSERT INTO props VALUES(%s)" % ",".join("?" * 10),
        "prop_results": "INSERT INTO prop_results VALUES(%s)" % ",".join("?" * 4),
    }
    buffers = collections.defaultdict(list)
    with gzip.open(SNAPSHOT, "rt", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("record_type") != "table_row":
                continue
            buffers[row["table"]].append(row["values"])
    for table, rows in buffers.items():
        con.executemany(insert[table], rows)
    con.commit()
    # project_week reads the score columns to decide if a game is final; the frozen capture used a
    # view that nulls them so a historical game is evaluated as a forecast.
    con.execute("UPDATE nfl_schedule SET away_score=NULL, home_score=NULL")
    con.commit()
    return con


# ------------------------------------------------------------------------------------------------
# discrete-distribution scoring
# ------------------------------------------------------------------------------------------------

def cdf(probs: list[float]) -> list[float]:
    out = []
    running = 0.0
    for p in probs:
        running += p
        out.append(running)
    return out


def quantile_index(f: list[float], q: float) -> int:
    """Smallest support index k with F(k) >= q (clamped)."""
    for k, v in enumerate(f):
        if v >= q - 1e-15:
            return k
    return len(f) - 1


def central_interval(f: list[float], level: float) -> tuple[int, int]:
    lo = quantile_index(f, (1.0 - level) / 2.0)
    hi = quantile_index(f, (1.0 + level) / 2.0)
    return lo, hi


def stable_seed(key) -> int:
    return zlib.crc32(repr(key).encode()) & 0xFFFFFFFF


def score_one(probs: list[float], actual: float, seed: int) -> dict:
    """Log score, discrete CRPS, mid and randomized PIT, and central-interval coverage."""
    n = len(probs)
    f = cdf(probs)
    y = int(math.floor(actual))
    # log score with the repository grader's clip
    p_y = probs[y] if 0 <= y < n else 0.0
    log_score = -math.log(max(p_y, 1e-9))
    # CRPS = sum_k (F(k) - 1{y<=k})^2 over the declared integer support
    crps = 0.0
    for k in range(n):
        crps += (f[k] - (1.0 if y <= k else 0.0)) ** 2
    # PIT: F(y-1) + U*p_y, with the discrete edge cases handled explicitly
    if y <= 0:
        below, p_mass = 0.0, (probs[0] if n else 0.0)
    elif y > n:
        below, p_mass = 1.0, 0.0
    else:
        below = f[y - 1]
        p_mass = probs[y] if y < n else 0.0
    pit_mid = below + 0.5 * p_mass
    pit_rand = below + random.Random(seed).random() * p_mass
    cov = {}
    for level in COVERAGE_LEVELS:
        lo, hi = central_interval(f, level)
        cov["cov%02d" % int(round(level * 100))] = 1 if lo <= y <= hi else 0
    # predictive moments
    mean = sum(k * p for k, p in enumerate(probs))
    var = sum((k - mean) ** 2 * p for k, p in enumerate(probs))
    return {"log_score": log_score, "crps": crps, "pit_mid": pit_mid, "pit_rand": pit_rand,
            "pred_mean": mean, "pred_var": var, **cov}


def empirical_pmf(values: list[int], extra: int = 1) -> list[float]:
    """Laplace-smoothed empirical PMF over 0..max(values)."""
    if not values:
        return None
    top = max(max(values), 0)
    counts = [0.0] * (top + 1)
    for v in values:
        if 0 <= v <= top:
            counts[v] += 1.0
    # add a small floor so an unseen actual is not -inf
    smooth = 1.0 / (len(values) + 1.0) * 0.05
    probs = [c / sum(counts) for c in counts]
    total = sum(probs) + smooth * len(probs)
    return [(p + smooth) / total for p in probs]


def summarize_scores(rows: list[dict]) -> dict:
    if not rows:
        return {}
    n = len(rows)
    out = {
        "n_player_games": len({r["key"] for r in rows}),
        "n_observations": n,
        "log_score": sum(r["score"]["log_score"] for r in rows) / n,
        "crps": sum(r["score"]["crps"] for r in rows) / n,
        "pit_mid_mean": sum(r["score"]["pit_mid"] for r in rows) / n,
        "pit_rand_mean": sum(r["score"]["pit_rand"] for r in rows) / n,
    }
    actual = [r["actual"] for r in rows]
    mean_a = sum(actual) / n
    var_a = sum((a - mean_a) ** 2 for a in actual) / n
    pred_var = sum(r["score"]["pred_var"] for r in rows) / n
    out["observed_mean"] = mean_a
    out["observed_var"] = var_a
    out["predicted_var_mean"] = pred_var
    out["variance_ratio_obs_over_pred"] = (var_a / pred_var) if pred_var > 0 else None
    for level in COVERAGE_LEVELS:
        out["coverage_pct_%d" % int(round(level * 100))] = 100.0 * sum(
            r["score"]["cov%02d" % int(round(level * 100))] for r in rows) / n
    bins = [0] * PIT_BINS
    for r in rows:
        bins[min(PIT_BINS - 1, int(r["score"]["pit_rand"] * PIT_BINS))] += 1
    out["pit_hist_pct"] = [100.0 * b / n for b in bins]
    return out


# ------------------------------------------------------------------------------------------------
# frozen capture artifact
# ------------------------------------------------------------------------------------------------

def load_frozen_artifact() -> dict:
    """Return side rows and paired line items indexed by (event, player, market, book, line)."""
    sides = []
    with gzip.open(ARTIFACT, "rt", encoding="utf-8") as fh:
        for line in fh:
            sides.append(json.loads(line))
    items = collections.defaultdict(dict)
    for row in sides:
        key = (row["event"]["id"], int(row["player"]["id"]), row["market"]["provider_market"],
               row["book"], float(row["line"]))
        items[key][row["side"]] = row
    pairs = []
    for key, by_side in items.items():
        if set(by_side) != {"over", "under"}:
            continue
        pairs.append((key, by_side["over"], by_side["under"]))
    return sides, pairs


def american_implied(odds) -> float:
    o = float(odds)
    return 100.0 / (o + 100.0) if o > 0 else -o / (-o + 100.0)


def devig(over_odds, under_odds) -> float:
    a, b = american_implied(over_odds), american_implied(under_odds)
    return a / (a + b)


def reproduce_2026(con: sqlite3.Connection, hist) -> dict:
    """Re-derive every frozen PMF and compare it exactly. Returns per-stat and per-market counts."""
    frozen: dict[tuple, dict] = {}
    with gzip.open(ARTIFACT, "rt", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row["side"] != "over":
                continue
            stat = row["market"]["stat"]
            frozen[(row["event"]["id"], int(row["player"]["id"]), stat)] = row

    entries_by_week = {w: job.project_week(con, 2026, w, n_sims=1, hist=hist)[0] for w in (3, 4, 5)}
    entry_index = {}
    for week, entries in entries_by_week.items():
        for e in entries:
            entry_index[(week, e["game_id"], e["player_id"])] = e

    per_stat = collections.defaultdict(lambda: {"tested": 0, "pmf_exact": 0, "p_over_exact": 0})
    per_market = collections.defaultdict(lambda: {"tested": 0, "pmf_exact": 0, "p_over_exact": 0})
    mismatches = []
    family_cache = {}

    def draws_for(week, event_id, pid):
        key = (week, event_id, pid)
        if key in family_cache:
            return family_cache[key]
        e = entry_index.get(key)
        if e is None:
            family_cache[key] = None
            return None
        base = e["scenarios"].get("base", {})
        if {"tgt", "rec", "rec_yds", "rec_td"}.issubset(base):
            tgt, rec, yards, td = (float(base[s][0]) for s in RECEIVING_STATS)
            if tgt <= 0:
                family_cache[key] = None
                return None
            d = eng.simulate(tgt, rec / tgt, yards / rec if rec > 0 else 0.0, td / tgt,
                             n=DRAW_COUNT, seed=DRAW_SEED)
            family_cache[key] = (d, RECV_IDX)
            return family_cache[key]
        if {"att", "cmp", "pass_yds", "pass_td"}.issubset(base):
            att, cmp_, yards, td = (float(base[s][0]) for s in PASSING_STATS)
            if att <= 0:
                family_cache[key] = None
                return None
            d = eng.simulate_qb(att, cmp_ / att, yards / cmp_ if cmp_ > 0 else 0.0, td / att,
                                n=DRAW_COUNT, seed=DRAW_SEED)
            family_cache[key] = (d, PASS_IDX)
            return family_cache[key]
        family_cache[key] = None
        return None

    for (event_id, pid, stat), row in frozen.items():
        market = row["market"]["provider_market"]
        week = int(row["event"]["week"])
        got = draws_for(week, event_id, pid)
        if got is None or stat not in got[1]:
            mismatches.append({"event": event_id, "player": pid, "stat": stat, "reason": "no entry"})
            per_stat[stat]["tested"] += 1
            per_market[market]["tested"] += 1
            continue
        draws, idx_map = got
        draw_index = idx_map[stat]
        vals = [math.floor(float(d[draw_index])) for d in draws]
        top = max(vals)
        counts = collections.Counter(vals)
        probs = [counts.get(v, 0) / len(vals) for v in range(top + 1)]
        frozen_probs = row["pmf"]["probabilities"]
        pmf_ok = len(probs) == len(frozen_probs) and all(
            abs(a - b) < 1e-12 for a, b in zip(probs, frozen_probs))
        line = float(row["line"])
        p_cont = sum(1 for d in draws if float(d[draw_index]) > line) / len(draws)
        p_over_ok = abs(p_cont - float(row["forecast_probability"]["p_over_raw"])) < 1e-12
        per_stat[stat]["tested"] += 1
        per_stat[stat]["pmf_exact"] += int(pmf_ok)
        per_stat[stat]["p_over_exact"] += int(p_over_ok)
        per_market[market]["tested"] += 1
        per_market[market]["pmf_exact"] += int(pmf_ok)
        per_market[market]["p_over_exact"] += int(p_over_ok)
        if not (pmf_ok and p_over_ok):
            mismatches.append({"event": event_id, "player": pid, "stat": stat,
                               "pmf_ok": pmf_ok, "p_over_ok": p_over_ok})
    return {"per_stat": dict(per_stat), "per_market": dict(per_market),
            "n_mismatches": len(mismatches), "mismatches": mismatches[:25],
            "player_games": len({(k[0], k[1]) for k in frozen})}


def frozen_distribution_rows() -> list[dict]:
    """One row per (event, player, stat) using the over-side frozen PMF and the actual outcome."""
    seen = {}
    with gzip.open(ARTIFACT, "rt", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row["side"] != "over":
                continue
            stat = row["market"]["stat"]
            key = (row["event"]["id"], int(row["player"]["id"]), stat)
            if key in seen:
                continue
            actual = row.get("actual_value")
            outcome = row["outcome_state"]
            if outcome not in ("resolved", "true_zero"):
                continue
            seen[key] = {
                "key": key, "event": row["event"]["id"], "player": int(row["player"]["id"]),
                "week": int(row["event"]["week"]), "stat": stat,
                "market": row["market"]["provider_market"], "position": row["player"]["position"],
                "team": row["player"]["team_id"], "actual": float(actual),
                "probs": row["pmf"]["probabilities"],
                "p_over_raw": float(row["forecast_probability"]["p_over_raw"]),
                "p_over_platt": float(row["forecast_probability"]["p_over_v2_platt"]),
                "line": float(row["line"]),
            }
    return list(seen.values())


# ------------------------------------------------------------------------------------------------
# baselines from the frozen input snapshot logs
# ------------------------------------------------------------------------------------------------

class LogView:
    """Player-game log access for the trailing-5 and position-level baselines."""

    def __init__(self, con: sqlite3.Connection):
        pos = {pid: p for pid, p in con.execute("SELECT id, position FROM players WHERE league='nfl'")}
        self.pos = pos
        self.by_player = collections.defaultdict(list)
        self.by_pos = collections.defaultdict(list)
        for pid, season, game_id, team, stats, source, game_type in con.execute(
                "SELECT player_id, season, game_id, team, stats, source, game_type "
                "FROM player_game_logs WHERE league='nfl' AND source='nflverse_weekly' "
                "AND (game_type='REG' OR game_type IS NULL) ORDER BY season, game_id"):
            p = pos.get(pid)
            if p is None:
                continue
            try:
                week = int(game_id.split("_")[1])
            except (ValueError, IndexError):
                continue
            self.by_player[(season, pid)].append((week, game_id, stats))
            self.by_pos[p].append((season, week, stats))

    def prior_values(self, stat: str, season: int, pid: int, week: int) -> list[int]:
        key = LOG_KEYS[stat]
        vals = []
        for s in (season - 1, season):
            for w, _gid, stats in self.by_player.get((s, pid), []):
                if s == season and w >= week:
                    continue
                blob = json.loads(stats)
                if blob.get(key) is not None:
                    vals.append(int(float(blob[key])))
        return vals

    def position_values(self, stat: str, position: str, season: int, week: int) -> list[int]:
        key = LOG_KEYS[stat]
        model_seasons = (season - 1, season)
        vals = []
        for s, w, stats in self.by_pos.get(position, []):
            if s not in model_seasons:
                continue
            if s == season and w >= week:
                continue
            blob = json.loads(stats)
            if blob.get(key) is not None:
                vals.append(int(float(blob[key])))
        return vals


def baseline_rows(distribution_rows: list[dict], view: LogView, season: int = 2026) -> dict:
    """Per-stat trailing-5 and position-level baseline PMFs for the same player-games.

    Returns {stat: {"trailing_5": [rows], "position_league": [rows]}}.  Using only games
    before the target week, so the baselines respect the same walk-forward split as the model.
    """
    out = collections.defaultdict(lambda: {"trailing_5": [], "position_league": []})
    for r in distribution_rows:
        stat, week = r["stat"], r["week"]
        prior = view.prior_values(stat, season, r["player"], week)
        if prior:
            pmf = empirical_pmf(prior[-5:])
            if pmf is not None:
                out[stat]["trailing_5"].append(
                    {"key": r["key"], "actual": r["actual"],
                     "score": score_one(pmf, r["actual"], stable_seed(r["key"]))})
        league = view.position_values(stat, r["position"], season, week)
        if league:
            pmf = empirical_pmf(league)
            if pmf is not None:
                out[stat]["position_league"].append(
                    {"key": r["key"], "actual": r["actual"],
                     "score": score_one(pmf, r["actual"], stable_seed(r["key"]) ^ 0x5A5A)})
    return {stat: {"trailing_5": summarize_scores(v["trailing_5"]),
                   "position_league": summarize_scores(v["position_league"])}
            for stat, v in out.items()}


def integrity_verdict(stat: str, integrity: dict) -> tuple[str, str]:
    """A per-market classification of the predictive distribution alone (no prices)."""
    it = integrity.get(stat)
    if not it:
        return "UNMEASURED", "no distribution in the capture artifact"
    cov80 = it.get("coverage_pct_80")
    cov90 = it.get("coverage_pct_90")
    vr = it.get("variance_ratio_obs_over_pred")
    reasons = []
    if cov80 is not None and cov80 > 95.0:
        reasons.append("80%% coverage %.1f%% (nominal 80)" % cov80)
    if cov90 is not None and cov90 > 99.0:
        reasons.append("90%% coverage %.1f%% (nominal 90)" % cov90)
    if vr is not None and vr < 0.7:
        reasons.append("variance ratio %.2f (underdispersed)" % vr)
    if reasons:
        return "NOT_ADOPTED", "; ".join(reasons)
    return "INCONCLUSIVE", "distribution integrity not decisively failed"



# ------------------------------------------------------------------------------------------------
# market comparison on the frozen line items
# ------------------------------------------------------------------------------------------------

def market_comparison(pairs: list[tuple], reps: int = 2000) -> dict:
    by_market = collections.defaultdict(list)
    all_items = []
    for key, over, under in pairs:
        if over["outcome_state"] not in ("resolved", "true_zero"):
            continue
        if over["settlement_state"] not in ("win", "loss"):
            continue
        event_id, pid, market, book, line = key
        y = 1 if over["settlement_state"] == "win" else 0
        p_raw = float(over["forecast_probability"]["p_over_raw"])
        p_platt = float(over["forecast_probability"]["p_over_v2_platt"])
        q = devig(over["quote"]["odds_american"], under["quote"]["odds_american"])
        item = {"market": market, "event": event_id, "player": pid, "y": y,
                "p_raw": p_raw, "p_platt": p_platt, "q": q,
                "brier_raw": (p_raw - y) ** 2, "brier_platt": (p_platt - y) ** 2,
                "brier_market": (q - y) ** 2,
                "ll_raw": -math.log(max(p_raw if y == 1 else 1 - p_raw, 1e-9)),
                "ll_platt": -math.log(max(p_platt if y == 1 else 1 - p_platt, 1e-9)),
                "ll_market": -math.log(max(q if y == 1 else 1 - q, 1e-9))}
        by_market[market].append(item)
        all_items.append(item)

    def mean(rows, field):
        return sum(r[field] for r in rows) / len(rows) if rows else None

    def bootstrap_delta(rows, a, b, reps=reps, seed=20261020):
        clusters = collections.defaultdict(list)
        for r in rows:
            clusters[(r["event"], r["player"])].append(r[a] - r[b])
        keys = list(clusters)
        rng = random.Random(seed)
        out = []
        for _ in range(reps):
            tot, n = 0.0, 0
            for _ in range(len(keys)):
                rows_c = clusters[keys[rng.randrange(len(keys))]]
                tot += sum(rows_c)
                n += len(rows_c)
            out.append(tot / n)
        out.sort()
        return {"delta": mean(rows, a) - mean(rows, b),
                "lo": out[int(0.025 * (reps - 1))], "hi": out[int(0.975 * (reps - 1))]}

    summary = {}
    for market, rows in sorted(by_market.items()):
        summary[market] = {
            "n_items": len(rows),
            "player_games": len({(r["event"], r["player"]) for r in rows}),
            "brier_raw": mean(rows, "brier_raw"),
            "brier_platt": mean(rows, "brier_platt"),
            "brier_market": mean(rows, "brier_market"),
            "log_loss_raw": mean(rows, "ll_raw"),
            "log_loss_platt": mean(rows, "ll_platt"),
            "log_loss_market": mean(rows, "ll_market"),
            "delta_brier_platt_minus_market": bootstrap_delta(rows, "brier_platt", "brier_market"),
            "delta_brier_raw_minus_market": bootstrap_delta(rows, "brier_raw", "brier_market"),
        }
    overall = {
        "n_items": len(all_items),
        "player_games": len({(r["event"], r["player"]) for r in all_items}),
        "brier_raw": mean(all_items, "brier_raw"),
        "brier_platt": mean(all_items, "brier_platt"),
        "brier_market": mean(all_items, "brier_market"),
        "delta_brier_platt_minus_market": bootstrap_delta(all_items, "brier_platt", "brier_market"),
        "delta_brier_raw_minus_market": bootstrap_delta(all_items, "brier_raw", "brier_market"),
    }
    return {"per_market": summary, "overall": overall}


# ------------------------------------------------------------------------------------------------
# 2025 walk-forward pass (constants frozen on 2024)
# ------------------------------------------------------------------------------------------------

def _pmf_from_draws(draws, index: int) -> list[float]:
    vals = [math.floor(float(d[index])) for d in draws]
    top = max(vals)
    counts = collections.Counter(vals)
    return [counts.get(v, 0) / len(vals) for v in range(top + 1)]


WF_CACHE = HERE / "walk_forward_2025.json"


def run_2025_pass(draw_count: int = 2000, cache: bool = True) -> dict:
    """2025 weeks 3-18 walk-forward integrity for every market, constants frozen on 2024.

    Receiving and passing have Monte-Carlo simulators.  Rushing (carries, rushing yards, rushing
    TDs) has point means only in the committed engine, so there is no predictive distribution to
    score; that absence is itself reported per market.
    """
    if cache and WF_CACHE.exists():
        return json.loads(WF_CACHE.read_text())
    import backtest_nfl_player_projection_v2 as bt
    con = sqlite3.connect("file:%s?mode=ro" % DEV_DB, uri=True)
    con.row_factory = sqlite3.Row
    hist = eng.History.load(con, [2024, 2025])
    view = LogView(con)
    scored = collections.defaultdict(list)
    baseline_src = []
    rushing_means = collections.defaultdict(list)

    for i, r in enumerate(bt.eligible(hist, 2025)):
        v = eng.project(hist, 2025, r.week, r.pid, r.pos, r.team, r.opp, r.game_id)
        if v is None:
            continue
        key = (2025, r.game_id, r.pid)
        if "tgt" in v and v["tgt"] > 0:
            draws = eng.simulate(v["tgt"], v["rec"] / v["tgt"],
                                 v["rec_yds"] / v["rec"] if v["rec"] > 0 else 0.0,
                                 v["rec_td"] / v["tgt"], n=draw_count, seed=i)
            for stat in RECEIVING_STATS:
                probs = _pmf_from_draws(draws, RECV_IDX[stat])
                actual = getattr(r, stat)
                scored[stat].append({"key": key, "actual": actual,
                                     "score": score_one(probs, actual, stable_seed(key + (stat,)))})
                baseline_src.append({"key": key + (stat,), "stat": stat, "week": r.week,
                                     "player": r.pid, "position": r.pos, "actual": actual})
        for stat in RUSHING_STATS:
            rushing_means[stat].append({"actual": getattr(r, stat), "pred": v.get(stat)})

    for i, r in enumerate(bt.qb_games(hist, 2025)):
        v = eng.project_qb(hist, 2025, r.week, r.pid, r.team, r.opp, r.game_id)
        if v is None or v["att"] <= 0:
            continue
        draws = eng.simulate_qb(v["att"], v["cmp"] / v["att"],
                                v["pass_yds"] / v["cmp"] if v["cmp"] > 0 else 0.0,
                                v["pass_td"] / v["att"], n=draw_count, seed=100000 + i)
        key = (2025, r.game_id, r.pid)
        for stat in PASSING_STATS:
            probs = _pmf_from_draws(draws, PASS_IDX[stat])
            actual = getattr(r, stat)
            scored[stat].append({"key": key, "actual": actual,
                                 "score": score_one(probs, actual, stable_seed(key + (stat,)))})
            baseline_src.append({"key": key + (stat,), "stat": stat, "week": r.week,
                                 "player": r.pid, "position": "QB", "actual": actual})

    integrity = {stat: summarize_scores(rows) for stat, rows in scored.items()}
    baselines = baseline_rows(baseline_src, view, season=2025)
    rushing = {}
    for stat, rows in rushing_means.items():
        n = len(rows)
        mae = sum(abs(x["actual"] - x["pred"]) for x in rows if x["pred"] is not None) / n
        rushing[stat] = {"n_player_games": n, "point_mae": mae,
                         "distribution": "none in committed engine"}
    con.close()
    result = {"integrity": integrity, "baselines": baselines, "rushing": rushing,
              "draw_count": draw_count,
              "split": "fit on 2024, scored walk-forward 2025 weeks 3-18"}
    if cache:
        WF_CACHE.write_text(json.dumps(result, indent=2) + "\n")
    return result


# ------------------------------------------------------------------------------------------------
# verdicts
# ------------------------------------------------------------------------------------------------

def verdict_for(market: str, stat: str, repro: dict, integrity: dict, mkt: dict,
                has_prices: bool) -> tuple[str, str]:
    """Combine reproducibility, distribution integrity and the market comparison, in that order."""
    r = repro.get("per_market", {}).get(market)
    if r is not None and r["tested"] and (r["pmf_exact"] < r["tested"] or r["p_over_exact"] < r["tested"]):
        return "NOT_REPRODUCIBLE", "frozen PMF/P(over) not re-derived for %d/%d" % (
            r["pmf_exact"], r["tested"])
    iv, ireason = integrity_verdict(stat, integrity)
    if iv == "NOT_ADOPTED":
        return "NOT_ADOPTED", ireason
    if not has_prices:
        return "NO_PRICE_ARCHIVE", "no sportsbook lines in the capture artifact"
    m = mkt.get(market)
    if m is None:
        return "NO_PRICE_ARCHIVE", "no sportsbook lines in the capture artifact"
    d = m["delta_brier_platt_minus_market"]
    if d["delta"] > 0 and d["lo"] > 0:
        return "NOT_ADOPTED", "v2-platt Brier worse than the de-vigged market, interval excludes zero"
    return "INCONCLUSIVE", "clustered interval spans zero; no established edge or deficit"



def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-2025", action="store_true")
    ap.add_argument("--force-2025", action="store_true",
                    help="ignore walk_forward_2025.json and re-run the 2025 pass (~17 min)")
    ap.add_argument("--bootstrap-reps", type=int, default=2000)
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text())
    source_hashes = {rel: sha256_file(REPO / rel) for rel in manifest["source_files_sha256"]}
    hash_ok = source_hashes == manifest["source_files_sha256"]

    con = load_snapshot_db()
    hist = eng.History.load(con, [2025, 2026])

    # 1. reproducibility
    repro = reproduce_2026(con, hist)
    repro["source_hashes_match_manifest"] = hash_ok
    repro["artifact_sha256"] = sha256_file(ARTIFACT)
    repro["input_snapshot_sha256"] = sha256_file(SNAPSHOT)
    (HERE / "reproducibility_2026.json").write_text(json.dumps(repro, indent=2) + "\n")

    # 2. distribution integrity from the frozen PMFs
    dist_rows = frozen_distribution_rows()
    integrity_rows = collections.defaultdict(list)
    for r in dist_rows:
        integrity_rows[r["stat"]].append(
            {"key": r["key"], "actual": r["actual"],
             "score": score_one(r["probs"], r["actual"], stable_seed(r["key"]))})
    integrity = {stat: summarize_scores(rows) for stat, rows in integrity_rows.items()}

    # 3. baselines, per market
    view = LogView(con)
    baselines = baseline_rows(dist_rows, view, season=2026)

    # 4. market comparison
    _sides, pairs = load_frozen_artifact()
    mkt = market_comparison(pairs, reps=args.bootstrap_reps)

    # 5. 2025 walk-forward, all markets, constants frozen on 2024
    if args.force_2025 and WF_CACHE.exists():
        WF_CACHE.unlink()
    wf = {} if args.skip_2025 else run_2025_pass()

    # 6. verdicts: 2026 integrity where it exists, otherwise the 2025 walk-forward
    combined_integrity = dict(wf.get("integrity", {}))
    combined_integrity.update(integrity)
    stat_to_market = {}
    for market, (stat, _u, _f) in MARKET_STAT.items():
        stat_to_market.setdefault(stat, market)
    verdicts, verdict_reasons = {}, {}
    for stat, market in sorted(stat_to_market.items()):
        has_prices = market in mkt["per_market"]
        v, reason = verdict_for(market, stat, repro, combined_integrity,
                                mkt["per_market"], has_prices)
        verdicts[stat] = v
        verdict_reasons[stat] = reason
    for stat in RUSHING_STATS:
        verdicts[stat] = "NOT_ADOPTED"
        verdict_reasons[stat] = ("no predictive distribution in the committed v2 engine "
                                 "(point means only); the reported rushing-carries candidates "
                                 "are not reproducible on this branch")

    metrics = {
        "reproducibility": repro,
        "integrity_2026": integrity,
        "baselines_2026": baselines,
        "market_comparison_2026": mkt,
        "walk_forward_2025": wf,
        "verdicts": verdicts,
        "verdict_reasons": verdict_reasons,
    }
    (HERE / "metrics_2026.json").write_text(json.dumps(metrics, indent=2) + "\n")

    # frozen predictions CSV
    with (HERE / "frozen_predictions_2026.csv").open("w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["event_id", "player_id", "position", "market", "stat", "actual",
                     "p_over_raw", "p_over_v2_platt", "line", "pmf_mean", "pmf_p10", "pmf_p90"])
        for r in dist_rows:
            f = cdf(r["probs"])
            mean = sum(k * p for k, p in enumerate(r["probs"]))
            wr.writerow([r["event"], r["player"], r["position"], r["market"], r["stat"],
                         r["actual"], "%.6f" % r["p_over_raw"], "%.6f" % r["p_over_platt"],
                         r["line"], "%.4f" % mean, quantile_index(f, 0.1), quantile_index(f, 0.9)])

    # per-market coverage / reproducibility table
    wf = metrics.get("walk_forward_2025", {})

    def fnum(d, key, spec="%.4f"):
        v = d.get(key)
        return spec % v if v is not None else ""

    with (HERE / "per_market_coverage.csv").open("w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["market", "stat", "repro_tested", "repro_pmf_exact", "repro_p_over_exact",
                     "n_2026", "cov50_2026", "cov80_2026", "cov90_2026", "var_ratio_2026",
                     "log_2026", "crps_2026",
                     "n_2025", "cov50_2025", "cov80_2025", "cov90_2025", "var_ratio_2025",
                     "log_2025", "crps_2025",
                     "baseline_trailing5_log_2025", "baseline_league_log_2025",
                     "model_log_2025", "verdict", "reason"])
        for market, (stat, _u, _f) in sorted(MARKET_STAT.items()):
            rm = repro["per_market"].get(market, {})
            it26 = integrity.get(stat, {})
            it25 = wf.get("integrity", {}).get(stat, {})
            bl = wf.get("baselines", {}).get(stat, {})
            t5 = bl.get("trailing_5", {})
            lg = bl.get("position_league", {})
            wr.writerow([market, stat, rm.get("tested", 0), rm.get("pmf_exact", 0),
                         rm.get("p_over_exact", 0),
                         it26.get("n_player_games", ""),
                         fnum(it26, "coverage_pct_50", "%.1f"),
                         fnum(it26, "coverage_pct_80", "%.1f"),
                         fnum(it26, "coverage_pct_90", "%.1f"),
                         fnum(it26, "variance_ratio_obs_over_pred", "%.3f"),
                         fnum(it26, "log_score"), fnum(it26, "crps"),
                         it25.get("n_player_games", ""),
                         fnum(it25, "coverage_pct_50", "%.1f"),
                         fnum(it25, "coverage_pct_80", "%.1f"),
                         fnum(it25, "coverage_pct_90", "%.1f"),
                         fnum(it25, "variance_ratio_obs_over_pred", "%.3f"),
                         fnum(it25, "log_score"), fnum(it25, "crps"),
                         fnum(t5, "log_score"), fnum(lg, "log_score"),
                         fnum(it25, "log_score"),
                         verdicts.get(stat, ""), verdict_reasons.get(stat, "")])

    (HERE / "manifest.json").write_text(json.dumps({
        "generated_by": "run_validation.py",
        "source_commit": os.popen("git -C %s rev-parse HEAD" % REPO).read().strip(),
        "engine_hashes": source_hashes,
        "engine_hashes_match_manifest": hash_ok,
        "capture_artifact": str(ARTIFACT),
        "capture_artifact_sha256": repro["artifact_sha256"],
        "input_snapshot": str(SNAPSHOT),
        "input_snapshot_sha256": repro["input_snapshot_sha256"],
    }, indent=2) + "\n")

    print(json.dumps({"reproducibility": {k: v for k, v in repro.items() if k != "mismatches"},
                      "verdicts": verdicts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
