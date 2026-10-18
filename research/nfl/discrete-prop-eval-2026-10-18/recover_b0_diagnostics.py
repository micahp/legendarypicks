#!/usr/bin/env python3
"""Regenerate the frozen B0 rushing-carries PMFs and diagnostics, without fitting."""
import argparse
import datetime as dt
import gzip
import hashlib
import importlib
import json
import math
import platform
import random
import sqlite3
import subprocess
import sys
import tempfile
import tarfile
from collections import defaultdict
from pathlib import Path
from statistics import mean


SOURCE_COMMIT = "a9a46bd05ee75456ee906a6f1254ab5176084f13"
SOURCE_ENGINE_BLOB = "ae6b70e30ae1ff5c9902aa13acb794784cec41d8"
PARAM_FILE = "research/nfl/discrete-prop-eval-2026-10-18/frozen-inputs/frozen-v2.json"
SEASONS = (2025, 2026)
WEEKS = set(range(3, 19))
LEVELS = (0.50, 0.80, 0.90)
TAILS = (0, 1, 2, 5, 10, 20)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def pct(sorted_values, p):
    if not sorted_values:
        return None
    x = (len(sorted_values) - 1) * p
    lo, hi = math.floor(x), math.ceil(x)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (x - lo)


def ks_uniform(values):
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        return None
    d_plus = max((i + 1) / n - x for i, x in enumerate(ordered))
    d_minus = max(x - i / n for i, x in enumerate(ordered))
    return max(d_plus, d_minus)


def ks_pvalue(d, n):
    if not n:
        return None
    lam = (math.sqrt(n) + 0.12 + 0.11 / math.sqrt(n)) * d
    return min(1.0, max(0.0, 2.0 * sum(
        (-1) ** (k - 1) * math.exp(-2.0 * k * k * lam * lam)
        for k in range(1, 101))))


def interval_sets(pmf, cdf, alpha):
    lo = next((k for k, f in enumerate(cdf) if f >= (1.0 - alpha) / 2.0), len(cdf) - 1)
    hi = next((k for k, f in enumerate(cdf) if f >= 1.0 - (1.0 - alpha) / 2.0), len(cdf) - 1)
    central = set(range(lo, hi + 1))

    candidates = []
    for left in range(len(pmf)):
        mass = 0.0
        for right in range(left, len(pmf)):
            mass += pmf[right]
            if mass + 1e-15 >= alpha:
                candidates.append((right - left + 1, left, right))
                break
    _, left, right = min(candidates)
    shortest = set(range(left, right + 1))

    hpd = set()
    mass = 0.0
    for k in sorted(range(len(pmf)), key=lambda j: (-pmf[j], j)):
        hpd.add(k)
        mass += pmf[k]
        if mass + 1e-15 >= alpha:
            break
    return {"central": central, "shortest": shortest, "hpd": hpd}


def set_components(values):
    ordered = sorted(values)
    if not ordered:
        return []
    out = [[ordered[0], ordered[0]]]
    for k in ordered[1:]:
        if k == out[-1][1] + 1:
            out[-1][1] = k
        else:
            out.append([k, k])
    return out


def row_metrics(item, pmf, cdf, mod):
    y = int(item["y"])
    mu = sum(k * p for k, p in enumerate(pmf))
    metrics = {
        "crps": mod.crps_discrete(cdf, y),
        "mae": abs(mu - y),
        "p0": pmf[0],
        "obs0": float(y == 0),
        "pit_lo": cdf[y - 1] if 0 < y < len(cdf) else (0.0 if y == 0 else 1.0),
        "pit_mass": pmf[y] if y < len(pmf) else 0.0,
    }
    for k in TAILS:
        if k == 0:
            pred, obs = pmf[0], float(y == 0)
        else:
            pred = 1.0 - (cdf[k - 1] if k - 1 < len(cdf) else 1.0)
            obs = float(y >= k)
        metrics["pred_%d" % k] = pred
        metrics["obs_%d" % k] = obs
        metrics["gap_%d" % k] = pred - obs
        metrics["brier_%d" % k] = (pred - obs) ** 2

    prediction_sets = {}
    for alpha in LEVELS:
        tag = str(int(alpha * 100))
        prediction_sets[tag] = {}
        for method, values in interval_sets(pmf, cdf, alpha).items():
            components = set_components(values)
            prediction_sets[tag][method] = components
            boundary = {v for a, b in components for v in (a, b)}
            mass = sum(pmf[k] for k in values)
            metrics["%s_%s_covered" % (method, tag)] = float(y in values)
            metrics["%s_%s_width" % (method, tag)] = max(values) - min(values)
            metrics["%s_%s_size" % (method, tag)] = len(values)
            metrics["%s_%s_set_mass" % (method, tag)] = mass
            metrics["%s_%s_boundary_mass" % (method, tag)] = sum(pmf[k] for k in boundary)
            metrics["%s_%s_mass_excess" % (method, tag)] = mass - alpha
            metrics["%s_%s_coverage_residual" % (method, tag)] = float(y in values) - mass
            metrics["%s_%s_disconnected" % (method, tag)] = float(len(components) > 1)
    return metrics, prediction_sets


def bootstrap_means(rows, fields, reps, seed):
    clusters = defaultdict(list)
    for row in rows:
        clusters[row["game_id"]].append(row["metrics"])
    game_ids = list(clusters)
    if len(game_ids) < 2 or not rows:
        return {field: None for field in fields}
    sums = {gid: {f: sum(r[f] for r in rs) for f in fields} for gid, rs in clusters.items()}
    counts = {gid: len(rs) for gid, rs in clusters.items()}
    rng = random.Random(seed)
    draws = {f: [] for f in fields}
    for _ in range(reps):
        selected = [rng.choice(game_ids) for _ in game_ids]
        n = sum(counts[g] for g in selected)
        for f in fields:
            draws[f].append(sum(sums[g][f] for g in selected) / n)
    return {
        f: {"lo95": pct(sorted(vals), 0.025), "hi95": pct(sorted(vals), 0.975)}
        for f, vals in draws.items()
    }


def summarize_group(rows, group_name, seed, reps, pit_draws):
    metric_names = sorted(rows[0]["metrics"]) if rows else []
    point = {k: mean(r["metrics"][k] for r in rows) for k in metric_names}
    ci = bootstrap_means(rows, metric_names, reps, seed)

    rng = random.Random(seed + 1)
    ks = []
    hist = [0] * 10
    for row in rows:
        row.setdefault("randomized_pit_draws", {})[group_name] = []
    for _ in range(pit_draws):
        values = []
        for row in rows:
            m = row["metrics"]
            value = m["pit_lo"] + rng.random() * m["pit_mass"]
            row["randomized_pit_draws"][group_name].append(value)
            values.append(value)
        ks.append(ks_uniform(values))
        for u in values:
            hist[min(9, int(u * 10))] += 1
    ks_sorted = sorted(ks)
    clusters = defaultdict(list)
    for row in rows:
        clusters[row["game_id"]].append(row)
    game_ids = list(clusters)
    pit_rng = random.Random(seed + 2)
    pit_boot = []
    for _ in range(reps):
        selected = [pit_rng.choice(game_ids) for _ in game_ids]
        values = []
        for gid in selected:
            for row in clusters[gid]:
                m = row["metrics"]
                values.append(m["pit_lo"] + pit_rng.random() * m["pit_mass"])
        pit_boot.append(ks_uniform(values))
    pit_boot.sort()
    pit = {
        "randomization_draws": pit_draws,
        "seed": seed + 1,
        "mean_ks": mean(ks),
        "randomization_q025_q975": [pct(ks_sorted, 0.025), pct(ks_sorted, 0.975)],
        "game_cluster_bootstrap_reps": reps,
        "game_cluster_bootstrap_seed": seed + 2,
        "game_cluster_bootstrap_95": [pct(pit_boot, 0.025), pct(pit_boot, 0.975)],
        "mean_ks_asymptotic_pvalue": mean(ks_pvalue(x, len(rows)) for x in ks),
        "decile_mean_frequency": [h / (pit_draws * len(rows)) for h in hist] if rows else [],
    }

    paired_intervals = {}
    pair_index = 0
    for alpha in LEVELS:
        tag = str(int(alpha * 100))
        for left, right in (("central", "shortest"), ("central", "hpd"),
                            ("shortest", "hpd")):
            compared = ("covered", "width", "size", "set_mass", "boundary_mass",
                        "mass_excess", "coverage_residual", "disconnected")
            diffs = [{"game_id": row["game_id"], "metrics": {
                name: row["metrics"]["%s_%s_%s" % (left, tag, name)] -
                      row["metrics"]["%s_%s_%s" % (right, tag, name)]
                for name in compared
            }} for row in rows]
            key = "%s|%s-%s" % (tag, left, right)
            paired_ci = bootstrap_means(diffs, list(compared), reps,
                                        seed + 100 + pair_index)
            paired_intervals[key] = {
                name: {
                    "mean_difference": mean(row["metrics"][name] for row in diffs),
                    "game_cluster_bootstrap_95": paired_ci[name],
                }
                for name in compared
            }
            pair_index += 1

    reliability = {}
    for k in TAILS:
        bins = []
        for b in range(10):
            members = [r for r in rows if min(9, int(r["metrics"]["pred_%d" % k] * 10)) == b]
            bins.append({
                "bin": "%0.1f-%0.1f" % (b / 10, (b + 1) / 10),
                "n": len(members),
                "mean_prediction": mean(r["metrics"]["pred_%d" % k] for r in members) if members else None,
                "observed_rate": mean(r["metrics"]["obs_%d" % k] for r in members) if members else None,
            })
        reliability[str(k)] = bins
    return {"n": len(rows), "games": len({r["game_id"] for r in rows}),
            "metrics": point, "game_cluster_bootstrap_95": ci,
            "randomized_pit": pit, "paired_interval_method_differences": paired_intervals,
            "threshold_reliability_deciles": reliability}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="immutable SQLite snapshot used for this replay")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--bootstrap-reps", type=int, default=1000)
    ap.add_argument("--pit-draws", type=int, default=100)
    ap.add_argument("--seed", type=int, default=20261018)
    a = ap.parse_args()
    db = Path(a.db).resolve()
    out_dir = Path(a.output_dir).resolve()
    repo = Path(__file__).resolve().parents[3]
    param_path = repo / PARAM_FILE
    if not db.is_file():
        raise SystemExit("database snapshot does not exist: " + str(db))
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit("refusing to overwrite non-empty output directory: " + str(out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lp-frozen-v2-") as temp:
        archive = subprocess.run(
            ["git", "archive", SOURCE_COMMIT, "backend/nfl_player_projection_v2.py",
             "backend/nfl_rushing_participation_v2.py"],
            cwd=repo, check=True, stdout=subprocess.PIPE)
        with tarfile.open(fileobj=__import__("io").BytesIO(archive.stdout), mode="r:") as tf:
            tf.extractall(temp)
        sys.path.insert(0, str(Path(temp) / "backend"))
        mod = importlib.import_module("nfl_rushing_participation_v2")

        db_sha = sha256(db)
        param_sha = sha256(param_path)
        frozen = json.loads(param_path.read_text())
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        con.execute("PRAGMA query_only=ON")
        hist = mod.eng.History.load(con, [2024, 2025, 2026])
        schedules = {
            gid: {"date": game_date, "away": away, "home": home}
            for gid, game_date, away, home in con.execute(
                "SELECT game_id, gameday, away_team, home_team "
                "FROM nfl_schedule WHERE season IN (2025,2026)")
        }

        recovered = {}
        for season in SEASONS:
            items = mod.build_items(hist, season, weeks=WEEKS)
            expected_n = 2500 if season == 2025 else 489
            expected_games = 240 if season == 2025 else 48
            if len(items) != expected_n or len({i["game_id"] for i in items}) != expected_games:
                raise SystemExit("population mismatch for %d: n=%d games=%d" %
                                 (season, len(items), len({i["game_id"] for i in items})))
            fit = frozen["seasons"][str(season)]["fit"]
            rows = []
            for item in items:
                pmf = mod.pmf_for("B0", item, {"R0": fit["R0"]})
                cdf = mod.cdf_of(pmf)
                metrics, prediction_sets = row_metrics(item, pmf, cdf, mod)
                schedule = schedules.get(item["game_id"], {})
                date = schedule.get("date")
                opponent = schedule.get("home") if item["team"] == schedule.get("away") else schedule.get("away")
                row = {"season": season, "week": item["week"], "game_date": date,
                       "game_id": item["game_id"], "player_id": item["pid"],
                       "team": item["team"], "opponent": opponent, "position": item["pos"],
                       "market": "rushing_attempts", "line": None, "outcome": int(item["y"]),
                       "tier_m": mod.TIER_LABEL[mod.tier_of(item["m"])], "m": item["m"],
                       "model_version": "B0-NB-R0-v2-reference",
                       "model_commit": SOURCE_COMMIT,
                       "parameter_file_sha256": param_sha,
                       "input_snapshot_sha256": db_sha,
                       "pmf": pmf, "cdf": cdf, "metrics": metrics,
                       "prediction_sets": prediction_sets}
                rows.append(row)
            ref = frozen["seasons"][str(season)]["tables"]["all (pregame candidates)|B0"]
            reproduced = {
                "crps": mean(r["metrics"]["crps"] for r in rows),
                "mae": mean(r["metrics"]["mae"] for r in rows),
                "cov50": mean(r["metrics"]["central_50_covered"] for r in rows),
                "cov80": mean(r["metrics"]["central_80_covered"] for r in rows),
                "cov90": mean(r["metrics"]["central_90_covered"] for r in rows),
            }
            delta = {k: reproduced[k] - ref[k] for k in reproduced}
            if max(abs(x) for x in delta.values()) > 1e-10:
                raise SystemExit("strict frozen-statistic reproduction failed for %d: %r" %
                                 (season, delta))

            groups = {"all": rows}
            for tier in ("m<3", "3<=m<8", "m>=8"):
                groups[tier] = [r for r in rows if r["tier_m"] == tier]
            diagnostics = {
                name: summarize_group(group, name, a.seed + season * 10 + idx,
                                      a.bootstrap_reps, a.pit_draws)
                for idx, (name, group) in enumerate(groups.items())
            }

            artifact = out_dir / ("B0-%d.jsonl.gz" % season)
            with gzip.open(artifact, "wt", encoding="utf-8", newline="") as gz:
                for row in rows:
                    gz.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
            recovered[str(season)] = {
                "n": len(rows), "games": expected_games,
                "evaluation_date_range": [min(r["game_date"] for r in rows if r["game_date"]),
                                          max(r["game_date"] for r in rows if r["game_date"])],
                "parameters": {"R0": fit["R0"], "frozen_json_sha256": param_sha},
                "reproduction": {"computed": reproduced, "reported": {k: ref[k] for k in reproduced},
                                 "delta": delta, "tolerance": 1e-10, "match": True},
                "diagnostics": diagnostics,
                "artifact": {"path": str(artifact), "bytes": artifact.stat().st_size,
                             "sha256": sha256(artifact)},
            }
        con.close()

    manifest = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model": "B0: negative-binomial PMF NB(m, R0), v2 reference implementation",
        "model_commit": SOURCE_COMMIT,
        "model_engine_blob_sha256": SOURCE_ENGINE_BLOB,
        "recovery_script": str(Path(__file__).resolve()),
        "recovery_script_sha256": sha256(Path(__file__).resolve()),
        "runtime": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version},
        "artifact_format": "gzip-compressed JSON Lines, one file per season",
        "artifact_schema_version": 2,
        "artifact_row_fields": ["season", "week", "game_date", "game_id", "player_id", "team",
                                "opponent", "position", "market", "line", "outcome", "tier_m", "m",
                                "model_version", "model_commit", "parameter_file_sha256",
                                "input_snapshot_sha256", "pmf", "cdf", "metrics", "prediction_sets",
                                "randomized_pit_draws"],
        "parameter_file": str(param_path), "parameter_file_sha256": param_sha,
        "input_snapshot": str(db), "input_snapshot_bytes": db.stat().st_size,
        "input_snapshot_mtime_utc": dt.datetime.fromtimestamp(
            db.stat().st_mtime, dt.timezone.utc).isoformat(),
        "input_snapshot_sha256": db_sha,
        "evaluation_seasons": list(SEASONS), "weeks_inclusive": [3, 18],
        "support": "integer carries 0..160; frozen source PMF implementation renormalizes on support",
        "stochastic_steps": {"PMF_and_scores": "none", "randomized_PIT": {
                             "seed_formula": "seed_base + season*10 + group_index + 1",
                             "seed_base": a.seed, "draws_per_group": a.pit_draws},
                             "cluster_bootstrap": {"seed_base": a.seed, "reps": a.bootstrap_reps,
                                                    "unit": "game_id, resampled within season/tier group"}},
        "reproduction_command": "python3 %s --db %s --output-dir %s --bootstrap-reps %d --pit-draws %d --seed %d" %
                                (Path(__file__).resolve(), db, out_dir, a.bootstrap_reps, a.pit_draws, a.seed),
        "seasons": recovered,
    }
    manifest_path = out_dir / "manifest-and-diagnostics.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({s: {"n": d["n"], "games": d["games"],
                          "reproduction": d["reproduction"], "artifact": d["artifact"]}
                      for s, d in recovered.items()}, indent=2, sort_keys=True))
    print("manifest=%s sha256=%s" % (manifest_path, sha256(manifest_path)))


if __name__ == "__main__":
    main()
