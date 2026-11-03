#!/usr/bin/env python3
"""Build weekly NFL observed-signature evolution measures from the dev DB.

All joins are exact source keys. Signatures are tuples of recorded fields,
not named plays or inferred concepts. The database is opened read-only.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import random
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from urllib.parse import quote


SEASONS = range(2022, 2027)
FAMILIES = ("action", "presentation", "chart_tags", "combined")
ALPHA = 0.5
BOOTSTRAP_REPS = 4000
PERIODS = ((1, 1, "week_1"), (2, 3, "weeks_2_3"), (4, 8, "weeks_4_8"),
           (9, 13, "weeks_9_13"), (14, 18, "weeks_14_18"))

QUERY = """
SELECT p.season, p.week, p.game_id, p.play_id, p.posteam, p.play_type,
       p.run_gap, p.run_location, p.pass_location, p.shotgun, p.no_huddle,
       (i.nflverse_game_id IS NOT NULL) AS participation_joined,
       i.offense_formation, i.offense_personnel,
       (c.nflverse_game_id IS NOT NULL) AS ftn_joined,
       c.is_motion, c.is_play_action, c.is_no_huddle,
       c.is_screen_pass, c.is_rpo, c.is_trick_play, c.is_qb_sneak
FROM nfl_pbp p
LEFT JOIN nfl_hist_participation i
  ON p.game_id=i.nflverse_game_id AND p.play_id=i.play_id
LEFT JOIN nfl_hist_ftn_charting c
  ON p.game_id=c.nflverse_game_id AND p.play_id=c.nflverse_play_id
WHERE p.season BETWEEN 2022 AND 2026
  AND p.week BETWEEN 1 AND 18
  AND p.play_type IN ('run', 'pass')
  AND p.posteam IS NOT NULL
ORDER BY p.season, p.week, p.posteam, p.game_id, p.play_id
"""


def open_readonly(path: Path) -> sqlite3.Connection:
    resolved = path.resolve()
    if not resolved.is_file():
        raise SystemExit(f"dev database does not exist: {resolved}")
    uri = f"file:{quote(str(resolved), safe='/')}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    if con.execute("PRAGMA query_only").fetchone()[0] != 1:
        con.close()
        raise RuntimeError("SQLite did not enable query_only")
    con.execute("BEGIN")
    return con


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def signature_payloads(row: sqlite3.Row) -> dict[str, dict]:
    action = {
        "play_type": row["play_type"],
        "run_gap": row["run_gap"],
        "run_location": row["run_location"],
        "pass_location": row["pass_location"],
    }
    presentation = {
        "participation_joined": bool(row["participation_joined"]),
        "offense_formation": row["offense_formation"],
        "offense_personnel": row["offense_personnel"],
        "shotgun": row["shotgun"],
        "pbp_no_huddle": row["no_huddle"],
        "ftn_joined": bool(row["ftn_joined"]),
        "is_motion": row["is_motion"],
        "is_play_action": row["is_play_action"],
        "ftn_no_huddle": row["is_no_huddle"],
    }
    chart_tags = {
        "is_screen_pass": row["is_screen_pass"],
        "is_rpo": row["is_rpo"],
        "is_trick_play": row["is_trick_play"],
        "is_qb_sneak": row["is_qb_sneak"],
    }
    return {
        "action": action,
        "presentation": presentation,
        "chart_tags": chart_tags,
        "combined": {"action": action, "presentation": presentation, "chart_tags": chart_tags},
    }


def entropy_bits(counter: Counter) -> float | None:
    total = sum(counter.values())
    if not total:
        return None
    return -sum((n / total) * math.log2(n / total) for n in counter.values() if n)


def hhi(counter: Counter) -> float | None:
    total = sum(counter.values())
    if not total:
        return None
    return sum((n / total) ** 2 for n in counter.values())


def top_share(counter: Counter) -> float | None:
    total = sum(counter.values())
    return max(counter.values()) / total if total else None


def js_divergence(left: Counter, right: Counter) -> float | None:
    nl, nr = sum(left.values()), sum(right.values())
    if not nl or not nr:
        return None
    keys = left.keys() | right.keys()
    result = 0.0
    for key in keys:
        p, q = left.get(key, 0) / nl, right.get(key, 0) / nr
        m = (p + q) / 2
        if p:
            result += 0.5 * p * math.log2(p / m)
        if q:
            result += 0.5 * q * math.log2(q / m)
    return result


def predictive_score(train: Counter, test: Counter, alpha: float = ALPHA) -> tuple[float | None, float | None]:
    """Score known exact signatures plus one aggregate unseen-signature bucket."""
    n = sum(train.values())
    if n == 0 or not test:
        return None, None
    k = len(train)
    denominator = n + alpha * (k + 1)
    p_new = alpha / denominator
    entropy = -p_new * math.log2(p_new)
    for count in train.values():
        p = (count + alpha) / denominator
        entropy -= p * math.log2(p)
    loss = 0.0
    test_n = sum(test.values())
    for signature, count in test.items():
        p = ((train[signature] + alpha) / denominator) if signature in train else p_new
        loss -= count * math.log2(p)
    return entropy, loss / test_n


def summarize_counter(counter: Counter, prior: Counter | None = None) -> dict:
    total = sum(counter.values())
    previous = prior or Counter()
    prior_n = sum(previous.values())
    novel_keys = set(counter) - set(previous)
    singleton_n = sum(n == 1 for n in previous.values())
    return {
        "unique_week": len(counter),
        "unique_first_seen_this_week": len(novel_keys),
        "rows_first_seen_this_week": sum(counter[key] for key in novel_keys),
        "novel_row_share_vs_prior_weeks": (
            sum(counter[key] for key in novel_keys) / total if total and prior_n else None
        ),
        "prior_rows": prior_n,
        "prior_unique": len(previous),
        "prior_entropy_bits": entropy_bits(previous),
        "week_entropy_bits": entropy_bits(counter),
        "week_hhi": hhi(counter),
        "week_top1_share": top_share(counter),
        "jsd_vs_prior_cumulative": js_divergence(counter, previous),
        "good_turing_unseen_mass_estimate": singleton_n / prior_n if prior_n else None,
    }


def sum_counters(counters) -> Counter:
    total = Counter()
    for counter in counters:
        total.update(counter)
    return total


def novel_against(counter: Counter, catalog: Counter) -> tuple[int | None, float | None, int | None]:
    if not catalog:
        return None, None, None
    new_keys = set(counter) - set(catalog)
    rows = sum(counter.values())
    novel_rows = sum(counter[key] for key in new_keys)
    return len(new_keys), novel_rows / rows if rows else None, sum(catalog.values())


def metric_mean(records: list[dict], key: str) -> float | None:
    values = [r[key] for r in records if r.get(key) is not None]
    return mean(values) if values else None


def period_for(week: int) -> str:
    for low, high, label in PERIODS:
        if low <= week <= high:
            return label
    return "outside_defined_periods"


def bootstrap_team_ci(values_by_team: dict[str, list[float]], reps: int, seed: int) -> list[float] | None:
    teams = sorted(values_by_team)
    if len(teams) < 2:
        return None
    rng = random.Random(seed)
    samples = []
    for _ in range(reps):
        chosen = [rng.choice(teams) for _ in teams]
        observations = [value for team in chosen for value in values_by_team[team]]
        if observations:
            samples.append(mean(observations))
    samples.sort()
    return [samples[int(0.025 * (len(samples) - 1))], samples[int(0.975 * (len(samples) - 1))]]


def build(db_path: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    con = open_readonly(db_path)
    try:
        rows = list(con.execute(QUERY))
        schema_version = con.execute("PRAGMA schema_version").fetchone()[0]
        data_version = con.execute("PRAGMA data_version").fetchone()[0]
        duplicate_pbp = con.execute(
            """SELECT COUNT(*) FROM (SELECT game_id,play_id FROM nfl_pbp
               WHERE season BETWEEN 2022 AND 2026 AND play_type IN ('run','pass')
               GROUP BY game_id,play_id HAVING COUNT(*)>1)"""
        ).fetchone()[0]
        if duplicate_pbp:
            raise RuntimeError(f"PBP run/pass key audit found {duplicate_pbp} duplicate groups")
        duplicate_part = con.execute(
            """SELECT COUNT(*) FROM (SELECT nflverse_game_id,play_id FROM nfl_hist_participation
               WHERE season BETWEEN 2022 AND 2025 GROUP BY nflverse_game_id,play_id HAVING COUNT(*)>1)"""
        ).fetchone()[0]
        duplicate_ftn = con.execute(
            """SELECT COUNT(*) FROM (SELECT nflverse_game_id,nflverse_play_id FROM nfl_hist_ftn_charting
               WHERE season BETWEEN 2022 AND 2025 GROUP BY nflverse_game_id,nflverse_play_id HAVING COUNT(*)>1)"""
        ).fetchone()[0]
        if duplicate_part or duplicate_ftn:
            raise RuntimeError(f"source join key audit found duplicate groups: participation={duplicate_part}, ftn={duplicate_ftn}")
        raw_counts = {
            str(s): con.execute(
                "SELECT COUNT(*) FROM nfl_pbp WHERE season=? AND play_type IN ('run','pass') AND posteam IS NOT NULL",
                (s,),
            ).fetchone()[0]
            for s in SEASONS
        }
        if sum(raw_counts.values()) != len(rows):
            raise RuntimeError(f"joined query row count {len(rows)} != PBP run/pass row count {sum(raw_counts.values())}")
        db_stat = db_path.stat()
    finally:
        con.close()

    teams = sorted({row["posteam"] for row in rows})
    max_week = {int(s): max(int(row["week"]) for row in rows if int(row["season"]) == s) for s in SEASONS}
    weekly = defaultdict(lambda: {
        "rows": 0, "runs": 0, "passes": 0, "games": set(), "sources": Counter(),
        "field_presence": Counter(), "signatures": {family: Counter() for family in FAMILIES},
        "payloads": {family: {} for family in FAMILIES},
    })
    season_team: dict[tuple[int, str, str], Counter] = defaultdict(Counter)
    season_league: dict[tuple[int, str], Counter] = defaultdict(Counter)

    for row in rows:
        season, week, team = int(row["season"]), int(row["week"]), row["posteam"]
        key = (season, week, team)
        bucket = weekly[key]
        bucket["rows"] += 1
        bucket["runs"] += row["play_type"] == "run"
        bucket["passes"] += row["play_type"] == "pass"
        bucket["games"].add(row["game_id"])
        bucket["sources"]["participation_joined"] += bool(row["participation_joined"])
        bucket["sources"]["ftn_joined"] += bool(row["ftn_joined"])
        for field in ("offense_formation", "offense_personnel", "is_motion", "is_play_action"):
            bucket["field_presence"][field] += row[field] is not None
        payloads = signature_payloads(row)
        for family, payload in payloads.items():
            signature = canonical(payload)
            bucket["signatures"][family][signature] += 1
            bucket["payloads"][family][signature] = payload
            season_team[(season, team, family)][signature] += 1
            season_league[(season, family)][signature] += 1

    all_period_rows = []
    signature_usage = []
    historical_weekly: dict[tuple[int, int, str], dict] = {}
    for team in teams:
        for season in SEASONS:
            prior = {family: Counter() for family in FAMILIES}
            previous_week_counter = {family: None for family in FAMILIES}
            previous_observed_week = None
            prior_season = season_team.get((season - 1, team, "action"), Counter())
            older_team = sum_counters(
                season_team[(s, team, "action")] for s in SEASONS if s < season
            )
            prior_league = sum_counters(
                season_league[(s, "action")] for s in SEASONS if s < season
            )
            for week in range(1, max_week[int(season)] + 1):
                group_key = (int(season), week, team)
                bucket = weekly.get(group_key)
                out = {
                    "season": int(season), "week": week, "period": period_for(week), "team": team,
                    "plays": bucket["rows"] if bucket else 0,
                    "runs": bucket["runs"] if bucket else 0,
                    "passes": bucket["passes"] if bucket else 0,
                    "games": len(bucket["games"]) if bucket else 0,
                    "previous_observed_team_week": previous_observed_week,
                }
                for field in ("participation_joined", "ftn_joined"):
                    out[f"{field}_share"] = (
                        bucket["sources"][field] / bucket["rows"] if bucket else None
                    )
                for field in ("offense_formation", "offense_personnel", "is_motion", "is_play_action"):
                    out[f"{field}_present_share"] = (
                        bucket["field_presence"][field] / bucket["rows"] if bucket else None
                    )

                if bucket:
                    for family in FAMILIES:
                        counter = bucket["signatures"][family]
                        summary = summarize_counter(counter, prior[family])
                        for name, value in summary.items():
                            out[f"{family}_{name}"] = value
                        prior_week = previous_week_counter[family]
                        out[f"{family}_jsd_vs_previous_observed_week"] = js_divergence(counter, prior_week) if prior_week else None
                        for signature, count in counter.items():
                            signature_usage.append({
                                "season": int(season), "week": week, "team": team,
                                "signature_family": family, "signature": signature,
                                "plays": count, "first_seen_in_team_season": signature not in prior[family],
                                "prior_team_season_plays": sum(prior[family].values()),
                            })
                        prior[family].update(counter)
                        previous_week_counter[family] = counter

                    action = bucket["signatures"]["action"]
                    action_unique, action_share, action_catalog_rows = novel_against(action, prior_season)
                    out["action_unique_not_in_previous_season"] = action_unique
                    out["action_novel_row_share_vs_previous_season"] = action_share
                    out["previous_season_action_rows"] = action_catalog_rows
                    out["previous_season_action_unique"] = len(prior_season) if prior_season else None
                    out["action_jsd_vs_previous_season"] = js_divergence(action, prior_season)
                    older_unique, older_share, older_rows = novel_against(action, older_team)
                    out["action_unique_not_in_older_team_history"] = older_unique
                    out["action_novel_row_share_vs_older_team_history"] = older_share
                    out["older_team_action_rows"] = older_rows
                    out["older_team_action_unique"] = len(older_team) if older_team else None
                    out["action_jsd_vs_older_team_history"] = js_divergence(action, older_team)
                    league_unique, league_share, league_rows = novel_against(action, prior_league)
                    out["action_unique_not_in_prior_league_history"] = league_unique
                    out["action_novel_row_share_vs_prior_league_history"] = league_share
                    out["prior_league_action_rows"] = league_rows
                    out["prior_league_action_unique"] = len(prior_league) if prior_league else None
                    out["action_jsd_vs_prior_league_history"] = js_divergence(action, prior_league)

                    # `prior` now includes this week; recover the exact past-only catalog from prior minus current.
                    expanding_train = prior["action"].copy()
                    expanding_train.subtract(action)
                    expanding_train += Counter()
                    expanding_entropy, expanding_loss = predictive_score(expanding_train, action)
                    previous_entropy, previous_loss = predictive_score(prior_season, action)
                    older_entropy, older_loss = predictive_score(older_team, action)
                    league_entropy, league_loss = predictive_score(prior_league, action)
                    for prefix, entropy, loss in (
                        ("expanding", expanding_entropy, expanding_loss),
                        ("previous_season", previous_entropy, previous_loss),
                        ("older_team", older_entropy, older_loss),
                        ("prior_league", league_entropy, league_loss),
                    ):
                        out[f"action_predictive_entropy_{prefix}_bits"] = entropy
                        out[f"action_open_set_logloss_{prefix}_bits"] = loss
                    previous_observed_week = week
                else:
                    for family in FAMILIES:
                        for suffix in (
                            "unique_week", "unique_first_seen_this_week", "rows_first_seen_this_week",
                            "novel_row_share_vs_prior_weeks", "prior_rows", "prior_unique",
                            "prior_entropy_bits", "week_entropy_bits", "week_hhi", "week_top1_share",
                            "jsd_vs_prior_cumulative", "good_turing_unseen_mass_estimate",
                            "jsd_vs_previous_observed_week",
                        ):
                            out[f"{family}_{suffix}"] = None
                    for field in (
                        "action_unique_not_in_previous_season", "action_novel_row_share_vs_previous_season",
                        "previous_season_action_rows", "previous_season_action_unique", "action_jsd_vs_previous_season",
                        "action_unique_not_in_older_team_history", "action_novel_row_share_vs_older_team_history",
                        "older_team_action_rows", "older_team_action_unique", "action_jsd_vs_older_team_history",
                        "action_unique_not_in_prior_league_history", "action_novel_row_share_vs_prior_league_history",
                        "prior_league_action_rows", "prior_league_action_unique", "action_jsd_vs_prior_league_history",
                    ):
                        out[field] = None
                    for prefix in ("expanding", "previous_season", "older_team", "prior_league"):
                        out[f"action_predictive_entropy_{prefix}_bits"] = None
                        out[f"action_open_set_logloss_{prefix}_bits"] = None

                all_period_rows.append(out)
                historical_weekly[group_key] = out

    weekly_fields = sorted({key for row in all_period_rows for key in row})
    with (out_dir / "phase2_weekly_evolution_dev_2026-11-03.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=weekly_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(all_period_rows)

    usage_fields = ["season", "week", "team", "signature_family", "signature", "plays",
                    "first_seen_in_team_season", "prior_team_season_plays"]
    usage_path = out_dir / "phase2_signature_usage_dev_2026-11-03.csv.gz"
    with usage_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=usage_fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(signature_usage)

    period_summary = {}
    metric_keys = tuple(
        f"{family}_{suffix}"
        for family in FAMILIES
        for suffix in ("unique_week", "novel_row_share_vs_prior_weeks",
                       "good_turing_unseen_mass_estimate", "jsd_vs_prior_cumulative",
                       "week_entropy_bits", "week_hhi", "week_top1_share")
    ) + (
        "action_predictive_entropy_expanding_bits", "action_open_set_logloss_expanding_bits",
        "action_open_set_logloss_previous_season_bits", "action_novel_row_share_vs_previous_season",
    )
    for period in (label for _, _, label in PERIODS):
        period_summary[period] = {}
        for season in SEASONS:
            subset = [r for r in all_period_rows if r["period"] == period and r["season"] == season and r["plays"]]
            if subset:
                period_summary[period][str(season)] = {
                    "team_weeks": len(subset),
                    "plays": sum(r["plays"] for r in subset),
                    "metrics_team_week_mean": {key: metric_mean(subset, key) for key in metric_keys},
                }

    # Compare early and late open-set forecast loss on complete 2022-25 seasons,
    # paired within each team-season and bootstrapped by franchise.
    paired = []
    for season in range(2022, 2026):
        for team in teams:
            early = [historical_weekly[(season, w, team)]["action_open_set_logloss_expanding_bits"] for w in (2, 3)
                     if (season, w, team) in historical_weekly]
            late = [historical_weekly[(season, w, team)]["action_open_set_logloss_expanding_bits"] for w in range(14, 19)
                    if (season, w, team) in historical_weekly]
            early = [v for v in early if v is not None]
            late = [v for v in late if v is not None]
            if early and late:
                paired.append({"season": season, "team": team,
                               "early_mean": mean(early), "late_mean": mean(late),
                               "early_minus_late": mean(early) - mean(late)})
    by_team = defaultdict(list)
    for item in paired:
        by_team[item["team"]].append(item["early_minus_late"])
    early_late = {
        "metric": "early weeks 2-3 mean open-set log loss minus late weeks 14-18 mean; positive means lower late loss",
        "team_season_pairs": len(paired),
        "franchises": len(by_team),
        "mean_early_minus_late_bits_per_play": mean(x["early_minus_late"] for x in paired) if paired else None,
        "franchise_cluster_bootstrap_95_ci": bootstrap_team_ci(dict(by_team), BOOTSTRAP_REPS, 20261103),
        "bootstrap_replicates": BOOTSTRAP_REPS,
        "bootstrap_seed": 20261103,
    }

    db_stat = db_path.stat()
    manifest = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": {"path": str(db_path.resolve()), "bytes": db_stat.st_size,
                     "mtime_ns": db_stat.st_mtime_ns, "schema_version": schema_version,
                     "data_version": data_version, "read_only": True, "query_only": True},
        "scope": {"seasons": [2022, 2023, 2024, 2025, 2026], "regular_season_weeks": "PBP rows with week 1-18",
                  "row_filter": "play_type IN ('run','pass') AND posteam IS NOT NULL",
                  "team_count": len(teams), "teams": teams,
                  "rows_by_season": raw_counts, "total_rows": len(rows),
                  "weekly_team_grid_rows": len(all_period_rows), "signature_usage_rows": len(signature_usage)},
        "key_audit": {"duplicate_pbp_run_pass_groups": duplicate_pbp,
                      "duplicate_participation_groups": duplicate_part,
                      "duplicate_ftn_groups": duplicate_ftn},
        "sources": {
            "participation_joined_rows": sum(bool(row["participation_joined"]) for row in rows),
            "ftn_joined_rows": sum(bool(row["ftn_joined"]) for row in rows),
            "participation_rows_2026": 0,
            "ftn_rows_2026": 0,
            "play_name_or_concept_ids": "not available; signatures remain observed-field tuples",
        },
        "signature_definition": {
            "action": ["play_type", "run_gap", "run_location", "pass_location"],
            "presentation": ["participation join state", "offense_formation", "offense_personnel", "shotgun",
                             "PBP no_huddle", "FTN join state", "is_motion", "is_play_action", "FTN is_no_huddle"],
            "chart_tags": ["is_screen_pass", "is_rpo", "is_trick_play", "is_qb_sneak"],
            "combined": "nested raw-field action, presentation, and chart-tag signatures",
            "missing_values": "retained as null and kept distinct from absent source joins",
            "cross_season": "action signature only; raw participation vocabularies are not harmonized",
            "excluded": ["air_yards and other outcomes", "invented play/concept names", "postseason rows"],
        },
        "methods": {
            "within_season_novelty": "current week's signatures absent from the team's earlier weeks; week 1 is null for this measure",
            "novelty_expected_rate": "Good-Turing singleton mass f1/N from prior team-season signatures, held as next-week first-snap estimate",
            "stability": "Jensen-Shannon divergence in bits between weekly distributions and prior cumulative / prior observed week",
            "concentration": "Shannon entropy, HHI, and top-signature share of exact observed signatures",
            "cross_season_baselines": "previous season team, all older team seasons, and all prior league seasons; action fields only",
            "open_set_forecast": {"alpha": ALPHA, "model": "Dirichlet smoothing over observed exact signatures plus one aggregate unseen-signature bucket",
                                  "interpretation": "tests known-versus-unseen descriptor probability, not which unseen signature occurs"},
            "early_late_test": "paired 2022-25 team-season early (weeks 2-3) versus late (weeks 14-18) open-set loss; bootstrap resamples franchises",
        },
        "period_summary": period_summary,
        "early_late_open_set_loss": early_late,
    }
    manifest_path = out_dir / "phase2_weekly_evolution_dev_2026-11-03.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest["artifact_sha256"] = {
        name: hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
        for name in ("phase2_weekly_evolution_dev_2026-11-03.csv", "phase2_signature_usage_dev_2026-11-03.csv.gz")
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="dev SQLite database; opened read-only")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.db, args.out_dir)
    print(json.dumps({
        "rows_by_season": result["scope"]["rows_by_season"],
        "total_rows": result["scope"]["total_rows"],
        "weekly_team_grid_rows": result["scope"]["weekly_team_grid_rows"],
        "signature_usage_rows": result["scope"]["signature_usage_rows"],
        "early_late_open_set_loss": result["early_late_open_set_loss"],
        "artifacts": result["artifact_sha256"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
