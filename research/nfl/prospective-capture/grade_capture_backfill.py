#!/usr/bin/env python3
"""Grade one frozen NFL prop capture artifact; read-only, with clustered bootstrap intervals."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import hashlib
import json
import math
import random
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
import grade_nfl_prop_probabilities as grader  # noqa: E402


OUTCOME_STATES = {"resolved", "true_zero", "dnp", "missing", "unresolved", "void"}
SETTLEMENT_STATES = {"win", "loss", "push", "void", "dnp", "missing", "unresolved"}
GRADEABLE_SETTLEMENTS = {"win", "loss"}
MODEL_NAMES = ("v2_raw", "v2_platt", "market_no_vig")
METRIC_NAMES = (
    "brier_v2_raw", "log_loss_v2_raw",
    "brier_v2_platt", "log_loss_v2_platt",
    "brier_market_no_vig", "log_loss_market_no_vig",
    "delta_brier_v2_raw_minus_market", "delta_brier_v2_platt_minus_market",
    "delta_log_loss_v2_raw_minus_market", "delta_log_loss_v2_platt_minus_market",
)
LOGLOSS_EPSILON = 1e-9


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_records(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def american_implied(odds: int) -> float:
    if isinstance(odds, bool) or not isinstance(odds, (int, float)) or odds == 0:
        raise ValueError(f"invalid American odds: {odds!r}")
    odds = float(odds)
    return 100.0 / (odds + 100.0) if odds > 0 else -odds / (-odds + 100.0)


def pmf_over_probability(row: dict) -> float:
    pmf = row["pmf"]
    support = pmf["support"]
    low, high = support["min"], support["max"]
    probabilities = pmf["probabilities"]
    if not support.get("integer") or len(probabilities) != high - low + 1:
        raise ValueError(f"invalid integer PMF on {row['observation_id']}")
    return math.fsum(p for value, p in enumerate(probabilities, start=low) if value > float(row["line"]))


def _pair_key(row: dict) -> tuple:
    return (
        int(row["season"]), row["event"]["id"], int(row["player"]["id"]),
        row["market"]["provider_market"], row["book"], float(row["line"]),
    )


def _scores(probabilities: tuple[float, float, float], outcome: int) -> tuple[float, ...]:
    values = []
    for p in probabilities:
        if not math.isfinite(p) or not 0.0 <= p <= 1.0:
            raise ValueError(f"probability outside [0,1]: {p!r}")
        values.extend(((p - outcome) ** 2, grader.logloss(p, outcome)))
    raw_brier, raw_loss, platt_brier, platt_loss, market_brier, market_loss = values
    return (
        raw_brier, raw_loss, platt_brier, platt_loss, market_brier, market_loss,
        raw_brier - market_brier, platt_brier - market_brier,
        raw_loss - market_loss, platt_loss - market_loss,
    )


def _mean_scores(items: list[dict]) -> dict:
    if not items:
        return {}
    n = len(items)
    return {name: math.fsum(item["scores"][i] for item in items) / n
            for i, name in enumerate(METRIC_NAMES)}


def _cluster_bootstrap(items: list[dict], key_fn, reps: int, seed: int) -> dict:
    groups = collections.defaultdict(list)
    for item in items:
        groups[key_fn(item)].append(item["scores"])
    keys = sorted(groups, key=repr)
    group_count = len(keys)
    if group_count < 2:
        raise ValueError(f"cluster bootstrap requires at least two clusters; got {group_count}")
    group_n = [len(groups[key]) for key in keys]
    group_sums = [
        [math.fsum(row[j] for row in groups[key]) for j in range(len(METRIC_NAMES))]
        for key in keys
    ]
    rng = random.Random(seed)
    estimates = [[] for _ in METRIC_NAMES]
    for _ in range(reps):
        numerators = [0.0] * len(METRIC_NAMES)
        denominator = 0
        for _draw in range(group_count):
            index = rng.randrange(group_count)
            denominator += group_n[index]
            sums = group_sums[index]
            for metric_index, total in enumerate(sums):
                numerators[metric_index] += total
        if denominator <= 0:
            raise RuntimeError("bootstrap replicate has no observations")
        for metric_index, total in enumerate(numerators):
            estimates[metric_index].append(total / denominator)

    low_index = int(0.025 * (reps - 1))
    high_index = int(0.975 * (reps - 1))
    intervals = {}
    for index, name in enumerate(METRIC_NAMES):
        ordered = sorted(estimates[index])
        intervals[name] = {"low": ordered[low_index], "high": ordered[high_index]}
    return {
        "clusters": group_count,
        "replicates": reps,
        "seed": seed,
        "method": "cluster resample with replacement; retain all line-items in sampled clusters; row-weighted mean; percentile order statistics",
        "intervals": intervals,
    }


def grade(path: Path, reps: int = 10000, seed: int = 20261019) -> dict:
    records = read_records(path)
    if not records:
        raise ValueError("forecast artifact is empty")
    ids = [row.get("observation_id") for row in records]
    if None in ids or len(set(ids)) != len(ids):
        raise ValueError("observation_id is absent or duplicated")
    if any(row.get("capture_mode") != "backfill" or row.get("cp4_evidence_eligible") is not False for row in records):
        raise ValueError("input is not exclusively CP4-ineligible backfill")
    unknown_outcomes = {row.get("outcome_state") for row in records} - OUTCOME_STATES
    unknown_settlements = {row.get("settlement_state") for row in records} - SETTLEMENT_STATES
    if unknown_outcomes or unknown_settlements:
        raise ValueError(f"unknown state values: outcomes={unknown_outcomes}, settlements={unknown_settlements}")

    outcome_rows = collections.Counter(row["outcome_state"] for row in records)
    settlement_rows = collections.Counter(row["settlement_state"] for row in records)
    calibration_status_rows = collections.Counter(
        row["forecast_probability"].get("calibration", {}).get("status", "missing") for row in records
    )
    forecast_label_rows = collections.Counter(row.get("forecast_label", "missing") for row in records)
    served_alias_raw_matches = 0
    served_alias_platt_matches = 0
    for row in records:
        probability = row["forecast_probability"]
        alias = probability.get("p_over_served_4dp")
        if alias == round(float(probability["p_over_raw"]), 4):
            served_alias_raw_matches += 1
        if alias == round(float(probability["p_over_v2_platt"]), 4):
            served_alias_platt_matches += 1
    discrepancy_by_market = collections.defaultdict(list)
    discrepancy_all = []
    grouped = collections.defaultdict(list)
    for row in records:
        delta = float(row["forecast_probability"]["p_over_raw"]) - pmf_over_probability(row)
        discrepancy_all.append(delta)
        discrepancy_by_market[row["market"]["provider_market"]].append(delta)
        grouped[_pair_key(row)].append(row)

    items = []
    over_side_item_settlements = collections.Counter()
    item_outcomes = collections.Counter()
    excluded_item_settlements = collections.Counter()
    book_settlement_check = collections.Counter()
    all_items_by_market = collections.Counter()
    gradeable_by_market = collections.Counter()
    all_items_by_week = collections.Counter()
    gradeable_by_week = collections.Counter()

    for key, members in grouped.items():
        if len(members) != 2 or {row["side"] for row in members} != {"over", "under"}:
            raise ValueError(f"line item lacks exactly one over and one under row: {key}")
        over = next(row for row in members if row["side"] == "over")
        under = next(row for row in members if row["side"] == "under")
        market = over["market"]["provider_market"]
        week = int(over["event"]["week"])
        all_items_by_market[market] += 1
        all_items_by_week[week] += 1

        for field in ("outcome_state", "actual_value"):
            if over[field] != under[field]:
                raise ValueError(f"paired sides disagree on {field}: {key}")
        for field in ("p_over_raw", "p_over_v2_platt"):
            a = float(over["forecast_probability"][field])
            b = float(under["forecast_probability"][field])
            if not math.isclose(a, b, rel_tol=0.0, abs_tol=1e-15):
                raise ValueError(f"paired sides disagree on {field}: {key}")
        pmf_o = pmf_over_probability(over)
        pmf_u = pmf_over_probability(under)
        if not math.isclose(pmf_o, pmf_u, rel_tol=0.0, abs_tol=1e-15):
            raise ValueError(f"paired sides disagree on integer PMF: {key}")

        outcome_state = over["outcome_state"]
        settlement = over["settlement_state"]
        item_outcomes[outcome_state] += 1
        over_side_item_settlements[settlement] += 1
        if outcome_state in {"resolved", "true_zero"}:
            actual = float(over["actual_value"])
            if (outcome_state == "true_zero") != (actual == 0.0):
                raise ValueError(f"resolved/true_zero does not match actual_value: {key}")
            expected_over = "win" if actual > float(over["line"]) else "loss" if actual < float(over["line"]) else "push"
            expected_under = "loss" if expected_over == "win" else "win" if expected_over == "loss" else "push"
            if over["settlement_state"] != expected_over or under["settlement_state"] != expected_under:
                raise ValueError(f"stored settlement does not match actual_value and line: {key}")
        if outcome_state == "true_zero" and over["actual_value"] != 0:
            raise ValueError(f"true_zero does not have actual_value=0: {key}")
        if outcome_state in {"dnp", "missing", "unresolved", "void"} and over["actual_value"] is not None:
            raise ValueError(f"{outcome_state} row carries an actual value: {key}")

        if settlement not in GRADEABLE_SETTLEMENTS:
            if under["settlement_state"] != settlement:
                raise ValueError(f"non-gradeable paired sides disagree on settlement state: {key}")
            excluded_item_settlements[settlement] += 1
            continue
        if outcome_state not in {"resolved", "true_zero"}:
            raise ValueError(f"gradeable settlement has non-gradeable outcome state: {key}")
        if {over["settlement_state"], under["settlement_state"]} != {"win", "loss"}:
            raise ValueError(f"win/loss sides are not complementary: {key}")

        quote_over, quote_under = over["quote"], under["quote"]
        if quote_over.get("source") != over["book"] or quote_under.get("source") != under["book"]:
            raise ValueError(f"captured quote source does not match book: {key}")
        lock = dt.datetime.fromisoformat(over["lock_time"].replace("Z", "+00:00"))
        for captured_at in (quote_over.get("captured_at"), quote_under.get("captured_at")):
            quote_time = dt.datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
            if quote_time.tzinfo is None or lock.tzinfo is None or quote_time >= lock:
                raise ValueError(f"quote is not strictly pre-kickoff: {key}")
        over_odds = quote_over.get("odds_american")
        under_odds = quote_under.get("odds_american")
        if quote_over.get("opposite_odds_american") != under_odds or quote_under.get("opposite_odds_american") != over_odds:
            raise ValueError(f"paired captured odds do not match: {key}")
        if quote_over.get("opposite_prop_id") != quote_under.get("prop_id") or quote_under.get("opposite_prop_id") != quote_over.get("prop_id"):
            raise ValueError(f"paired quote ids do not match: {key}")

        market_probability = grader.devig(over_odds, under_odds)
        manual_over = american_implied(over_odds)
        manual_under = american_implied(under_odds)
        independent_market_probability = manual_over / (manual_over + manual_under)
        if not math.isclose(market_probability, independent_market_probability, rel_tol=0.0, abs_tol=1e-15):
            raise ValueError(f"market de-vig implementation mismatch: {key}")

        p_raw = float(over["forecast_probability"]["p_over_raw"])
        p_platt = float(over["forecast_probability"]["p_over_v2_platt"])
        y_over = 1 if over["settlement_state"] == "win" else 0
        book_result = over.get("book_settlement", {})
        if book_result.get("hit") is not None:
            book_settlement_check["items_with_hit"] += 1
            if int(book_result["hit"]) != y_over:
                book_settlement_check["hit_disagreements"] += 1
        if book_result.get("actual_value") is not None:
            book_settlement_check["items_with_actual_value"] += 1
            if float(book_result["actual_value"]) != float(over["actual_value"]):
                book_settlement_check["actual_value_disagreements"] += 1
        scores = _scores((p_raw, p_platt, market_probability), y_over)
        item = {
            "market": market,
            "week": week,
            "event_id": over["event"]["id"],
            "player_id": int(over["player"]["id"]),
            "outcome_state": outcome_state,
            "settlement_state": settlement,
            "y_over": y_over,
            "scores": scores,
        }
        items.append(item)
        gradeable_by_market[market] += 1
        gradeable_by_week[week] += 1

    if len(records) != 2 * len(grouped):
        raise RuntimeError("side-row and paired-line-item counts do not reconcile")
    gradeable_side_rows = 2 * len(items)
    if gradeable_side_rows + 2 * sum(excluded_item_settlements.values()) != len(records):
        raise RuntimeError("gradeable and excluded line-item counts do not reconcile")

    overall_scores = _mean_scores(items)
    player_game_bootstrap = _cluster_bootstrap(
        items, lambda item: (item["event_id"], item["player_id"]), reps, seed
    )
    event_bootstrap = _cluster_bootstrap(items, lambda item: item["event_id"], reps, seed + 1)

    per_market = {}
    all_markets = sorted(all_items_by_market)
    for market in all_markets:
        subset = [item for item in items if item["market"] == market]
        per_market[market] = {
            "captured_line_items": all_items_by_market[market],
            "gradeable_line_items": len(subset),
            "excluded_line_items_by_settlement_state": {
                state: sum(1 for key, members in grouped.items()
                           if members[0]["market"]["provider_market"] == market
                           and members[0]["settlement_state"] == state)
                for state in sorted(excluded_item_settlements)
            },
            "player_games": len({(item["event_id"], item["player_id"]) for item in subset}),
            "events": len({item["event_id"] for item in subset}),
            "gradeable_line_items_by_week": {
                str(week): sum(1 for item in subset if item["week"] == week)
                for week in sorted({item["week"] for item in subset})
            },
            "scores": _mean_scores(subset),
        }

    by_week = {}
    for week in sorted(all_items_by_week):
        subset = [item for item in items if item["week"] == week]
        by_week[str(week)] = {
            "captured_line_items": all_items_by_week[week],
            "gradeable_line_items": len(subset),
            "excluded_line_items": all_items_by_week[week] - len(subset),
            "player_games": len({(item["event_id"], item["player_id"]) for item in subset}),
            "events": len({item["event_id"] for item in subset}),
            "scores": _mean_scores(subset),
        }

    def discrepancy_summary(values: list[float]) -> dict:
        if not values:
            return {"n_side_rows": 0}
        mean = math.fsum(values) / len(values)
        variance = math.fsum((value - mean) ** 2 for value in values) / len(values)
        low, high = min(values), max(values)
        return {
            "n_side_rows": len(values),
            "mean_raw_minus_integer_pmf_over": mean,
            "population_sd": math.sqrt(variance),
            "min": 0.0 if abs(low) < 1e-15 else low,
            "max": 0.0 if abs(high) < 1e-15 else high,
            "positive_side_rows": sum(value > 1e-12 for value in values),
            "zero_within_1e-12_side_rows": sum(abs(value) <= 1e-12 for value in values),
            "negative_side_rows": sum(value < -1e-12 for value in values),
        }

    by_market_discrepancy = {
        market: discrepancy_summary(values)
        for market, values in sorted(discrepancy_by_market.items())
    }
    cluster_interval_map = {
        "player_game": player_game_bootstrap,
        "event": event_bootstrap,
    }
    output = {
        "schema_version": "nfl-capture-backfill-grade.v1",
        "input_artifact": str(path.resolve()),
        "input_artifact_sha256_compressed": sha256_file(path),
        "capture_mode": "backfill",
        "cp4_evidence_eligible": False,
        "grading_unit": "one paired over/under sportsbook line item; score P(over) once against the over outcome; the under row is used to validate complementary settlement and to de-vig the market",
        "market_probability_method": "American-odds implied probabilities on the captured over and under prices, normalized proportionally: q_over = implied(over)/(implied(over)+implied(under)); same method as grade_nfl_prop_probabilities.devig",
        "log_loss_probability_clip": LOGLOSS_EPSILON,
        "log_loss_clip_source": "grade_nfl_prop_probabilities.tight",
        "state_counts": {
            "side_rows": len(records),
            "outcome_state_side_rows": dict(sorted(outcome_rows.items())),
            "settlement_state_side_rows": dict(sorted(settlement_rows.items())),
            "calibration_status_side_rows": dict(sorted(calibration_status_rows.items())),
            "forecast_label_side_rows": dict(sorted(forecast_label_rows.items())),
            "paired_line_items": len(grouped),
            "outcome_state_line_items": dict(sorted(item_outcomes.items())),
            "over_side_settlement_line_items": dict(sorted(over_side_item_settlements.items())),
            "gradeable_side_rows": gradeable_side_rows,
            "gradeable_line_items": len(items),
            "excluded_line_items_by_settlement_state": dict(sorted(excluded_item_settlements.items())),
        },
        "versioned_probability_field_audit": {
            "forecast_label_side_rows": dict(sorted(forecast_label_rows.items())),
            "p_over_served_4dp_matches_rounded_raw_rows": served_alias_raw_matches,
            "p_over_served_4dp_matches_rounded_v2_platt_rows": served_alias_platt_matches,
            "note": "For CP4, select the explicit scalar field matching the frozen model_version; do not rely on the generic served alias until its label is aligned with the designated version.",
        },
        "population": {
            "gradeable_line_items": len(items),
            "gradeable_side_rows": gradeable_side_rows,
            "player_games": len({(item["event_id"], item["player_id"]) for item in items}),
            "events": len({item["event_id"] for item in items}),
            "weeks": sorted({item["week"] for item in items}),
            "gradeable_line_items_by_week": {str(w): gradeable_by_week[w] for w in sorted(gradeable_by_week)},
        },
        "overall_scores": overall_scores,
        "book_settlement_crosscheck": {
            "gradeable_line_items": len(items),
            "over_side_items_with_book_hit": book_settlement_check["items_with_hit"],
            "over_side_items_with_book_actual_value": book_settlement_check["items_with_actual_value"],
            "hit_disagreements": book_settlement_check["hit_disagreements"],
            "actual_value_disagreements": book_settlement_check["actual_value_disagreements"],
            "use": "independent consistency check only; frozen NFL player-game outcome/settlement states remain the scoring target",
        },
        "cluster_bootstrap_95_percent": cluster_interval_map,
        "per_market": per_market,
        "by_week": by_week,
        "integerization_discrepancy": {
            "definition": "p_over_raw - sum(PMF[x] for integer support x > line), computed on each stored side row; over/under sides repeat the same forecast",
            "all_captured_rows": discrepancy_summary(discrepancy_all),
            "by_market": by_market_discrepancy,
            "interpretation": "Positive yardage differences arise because p_over_raw thresholds the unrounded continuous draw, while the stored PMF thresholds floor(draw); at a half-yard line, draws between the line and the next integer are counted only by the continuous value.",
        },
        "limitations": [
            "Historical reconstructed backfill only; never CP4 evidence or prospective model evaluation.",
            "Bootstrap intervals quantify clustered variation in this selected 2026 week 4-5 backfill population; they do not establish adoption or prospective performance.",
            "Per-market scores are point estimates; the reported bootstrap intervals are for the full gradeable population.",
        ],
    }
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--bootstrap-reps", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261019)
    parser.add_argument("--output", type=Path, help="write JSON exclusively to a new local file")
    args = parser.parse_args(argv)
    if args.bootstrap_reps < 1000:
        parser.error("--bootstrap-reps must be at least 1000")
    result = grade(args.artifact.resolve(), args.bootstrap_reps, args.seed)
    rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as fh:
            fh.write(rendered)
        print(f"wrote {args.output.resolve()}")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
