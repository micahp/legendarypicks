"""Run deterministic NHL replay against the pinned full-frame ledgers."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from replay_data import (
    DEFAULT_ARTIFACT_DIR, DEFAULT_LABEL_DIR, DEFAULT_OFFICIAL_DIR, DEFAULT_RAW_DIR,
    InputBundle, InputIntegrityError, iter_game_event_groups, iter_shift_intervals,
    load_bundle, verify_all_source_bodies, verify_issue_ledger,
)
from replay_model import (
    ORDINARY_PERIOD_TYPES, SHOT_EVENTS, GameReplay, ReplayIntegrityError,
    compare_team_targets, reconcile_player_targets, replay_game,
)


HERE = Path(__file__).resolve().parent


def _metric_int(bundle: InputBundle, gid: str, key: str) -> int:
    try:
        return int(bundle.game_metrics[gid][key])
    except (KeyError, ValueError) as exc:
        raise InputIntegrityError(f"GAME_METRIC_INVALID {gid}/{key}") from exc


def _target_eligible(target, purpose: str) -> bool:
    return bool(target.purpose_values[purpose] is not None)


def replay_population(bundle: InputBundle, *, game_ids: set[str] | None = None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "games_replayed": 0,
        "frame_games": len(bundle.games),
        "frame_events": bundle.pins["expected_population"]["pbp_events"],
        "events_replayed": 0,
        "team_score": {"eligible": 0, "matched": 0, "quarantined": 0, "unmatched_eligible": []},
        "team_sog": {"eligible": 0, "matched": 0, "quarantined": 0, "unmatched_eligible": [], "quarantined_games": []},
        "team_shot_attempts": Counter(),
        "team_sog_events": Counter(),
        "shot_events_by_period_type": Counter(),
        "ordinary_goals_by_period": {"REG": Counter(), "OT": Counter()},
        "shootout": {"attempts": Counter(), "goals": Counter(), "period_games": 0},
        "penalties": {"calls": 0, "duration_missing_or_quarantined": 0, "timing_quarantined": 0},
        "manpower": {"observations": 0, "transitions": 0, "invalid_or_missing_codes": 0, "empty_net_observations": 0},
        "goalie": {"direct_event_observations": 0, "unverified_or_empty_net": 0,
                   "empty_net_observations": 0, "observed_id_changes": 0,
                   "returns_after_empty_net": 0, "raw_direct_ids_on_shot_family": 0,
                   "accepted_event_attributions": 0},
        "period_regression_events": 0,
        "explicit_delayed_penalty_event_types": 0,
        "deployment": Counter(),
        "player_targets": {purpose: Counter() for purpose in ("training", "evaluation", "grading")},
        "player_target_games": {purpose: Counter() for purpose in ("training", "evaluation", "grading")},
        "player_target_events": {purpose: Counter() for purpose in ("training", "evaluation", "grading")},
        "player_target_exclusions": {purpose: [] for purpose in ("training", "evaluation", "grading")},
        "seasons": defaultdict(lambda: Counter()),
        "cohort_games": {},
    }
    cohort = json.loads((HERE / "regression_cohort.json").read_text(encoding="utf-8"))
    cohort_meta = {row["game_id"]: row for row in cohort["games"]}
    if game_ids is not None and not game_ids.issubset(bundle.games):
        raise InputIntegrityError(f"REPLAY_REQUEST_OUTSIDE_FRAME {sorted(game_ids - set(bundle.games))}")

    for gid, events in iter_game_event_groups(bundle, game_ids=game_ids):
        definition = bundle.games[gid]
        for event in events:
            if event.quality.situation_deployment in {"ACCEPT", "QUARANTINE"}:
                summary["deployment"][f"situation_{event.quality.situation_deployment.lower()}"] += 1
            if event.event_type in SHOT_EVENTS and event.period_type in ORDINARY_PERIOD_TYPES:
                if event.quality.shooter_on_ice in {"ACCEPT", "QUARANTINE"}:
                    summary["deployment"][f"shooter_on_ice_{event.quality.shooter_on_ice.lower()}"] += 1
                if event.quality.goalie_shift_comparison in {"ACCEPT", "QUARANTINE"}:
                    summary["deployment"][f"goalie_shift_{event.quality.goalie_shift_comparison.lower()}"] += 1
        state = replay_game(definition, bundle.provenance[gid], events)
        team = compare_team_targets(state)
        season = str(definition.season)
        per_season = summary["seasons"][season]
        summary["games_replayed"] += 1
        summary["events_replayed"] += state.event_count
        per_season["games"] += 1
        per_season["events"] += state.event_count
        per_season["period_regression_events"] += state.period_regression_events

        if definition.score_disposition == "ACCEPT":
            summary["team_score"]["eligible"] += 1
            per_season["score_eligible"] += 1
            if not team["score_match"]:
                summary["team_score"]["unmatched_eligible"].append(gid)
                per_season["score_unmatched_eligible"] += 1
                raise ReplayIntegrityError(f"ACCEPTED_TEAM_SCORE_MISMATCH {gid}: {team}")
            summary["team_score"]["matched"] += 1
            per_season["score_matched"] += 1
        else:
            summary["team_score"]["quarantined"] += 1
            per_season["score_quarantined"] += 1

        if definition.sog_disposition == "ACCEPT":
            summary["team_sog"]["eligible"] += 1
            per_season["sog_eligible"] += 1
            if not team["sog_match"]:
                summary["team_sog"]["unmatched_eligible"].append(gid)
                per_season["sog_unmatched_eligible"] += 1
                raise ReplayIntegrityError(f"ACCEPTED_TEAM_SOG_MISMATCH {gid}: {team}")
            summary["team_sog"]["matched"] += 1
            per_season["sog_matched"] += 1
        else:
            summary["team_sog"]["quarantined"] += 1
            summary["team_sog"]["quarantined_games"].append(gid)
            per_season["sog_quarantined"] += 1

        for side, value in state.shot_attempts.items():
            summary["team_shot_attempts"][side] += value
            per_season[f"{side}_shot_attempts"] += value
        for side, value in state.shots_on_goal.items():
            summary["team_sog_events"][side] += value
            per_season[f"{side}_sog_events"] += value
        summary["shot_events_by_period_type"].update(state.shot_event_counts)
        for period in ("REG", "OT"):
            for side, value in state.score_by_period.get(period, {}).items():
                summary["ordinary_goals_by_period"][period][side] += value
                per_season[f"{period.lower()}_{side}_goals"] += value
        for side, value in state.shootout_attempts.items():
            summary["shootout"]["attempts"][side] += value
        for side, value in state.shootout_goals.items():
            summary["shootout"]["goals"][side] += value
        if state.shootout_period_observed:
            summary["shootout"]["period_games"] += 1
            per_season["shootout_games"] += 1

        summary["penalties"]["calls"] += len(state.penalty_calls)
        summary["penalties"]["duration_missing_or_quarantined"] += sum(
            p.duration_disposition != "ACCEPT" for p in state.penalty_calls)
        summary["penalties"]["timing_quarantined"] += sum(
            p.timing_disposition != "ACCEPT" for p in state.penalty_calls)
        summary["manpower"]["observations"] += state.source_component_counts["situation_code_valid"]
        summary["manpower"]["transitions"] += len(state.manpower_transitions)
        summary["manpower"]["invalid_or_missing_codes"] += state.source_component_counts[
            "situation_code_unavailable_or_invalid"]
        summary["manpower"]["empty_net_observations"] += sum(
            len(manpower.empty_net_sides) > 0 for _, _, manpower in state.manpower_transitions)
        summary["goalie"]["direct_event_observations"] += sum(
            obs.status == "DIRECT_ID_ACCEPTED" for obs in state.goalie_observations)
        summary["goalie"]["empty_net_observations"] += sum(
            obs.status == "EMPTY_NET_DIRECTLY_INDICATED_BY_SITUATION_CODE"
            for obs in state.goalie_observations)
        summary["goalie"]["unverified_or_empty_net"] += sum(
            obs.status != "DIRECT_ID_ACCEPTED" for obs in state.goalie_observations)
        summary["goalie"]["observed_id_changes"] += len(state.goalie_change_observations)
        summary["goalie"]["returns_after_empty_net"] += state.source_component_counts[
            "goalie_return_after_empty_net"]
        summary["goalie"]["raw_direct_ids_on_shot_family"] += state.source_component_counts[
            "raw_direct_goalie_id_on_shot_family"]
        summary["goalie"]["accepted_event_attributions"] += state.source_component_counts[
            "goalie_event_attribution_accept"]
        summary["period_regression_events"] += state.period_regression_events
        summary["explicit_delayed_penalty_event_types"] += state.source_component_counts[
            "explicit_delayed_penalty_event_type"]

        target_rows_by_purpose: dict[str, list[dict[str, object]]] = {}
        for purpose in ("training", "evaluation", "grading"):
            reconciled = reconcile_player_targets(
                state, bundle.targets_by_game.get(gid, []), purpose=purpose)
            target_rows_by_purpose[purpose] = reconciled
            targets = [target for target in bundle.targets_by_game.get(gid, [])
                       if _target_eligible(target, purpose)]
            for target in targets:
                population_counter = summary["player_targets"][purpose]
                population_counter[f"{target.statistic}_approved"] += 1
                per_season[f"{target.statistic}_{purpose}_approved"] += 1
            for row in reconciled:
                if row["eligible_target"]:
                    population_counter = summary["player_targets"][purpose]
                    population_counter[f"{row['statistic']}_event_eligible"] += 1
                    per_season[f"{row['statistic']}_{purpose}_event_eligible"] += 1
                    summary["player_target_events"][purpose][row["statistic"]] += int(
                        row["replayed_event_count"])
                elif _target_eligible_by_row(row, purpose):
                    reason = (row["audit_reason_code"] or row["reason_code"] or
                              "REPLAY_TARGET_COUNT_MISMATCH")
                    summary["player_target_exclusions"][purpose].append({
                        "game_id": gid,
                        "player_id": row["player_id"],
                        "statistic": row["statistic"],
                        "reason_code": reason,
                        "approved_label_reason_code": row["reason_code"],
                        "audit_reason_code": row["audit_reason_code"],
                        "source_issue_id": row["source_issue_id"],
                        "accepted_value": row["purpose_value"],
                        "replayed_event_count": row["replayed_event_count"],
                        "audit_event_count": row["audit_event_count"],
                    })
            for statistic in {row["statistic"] for row in reconciled if row["eligible_target"]}:
                summary["player_target_games"][purpose][statistic] += 1

        if gid in cohort_meta:
            metric = bundle.game_metrics[gid]
            first_event = events[0]
            summary["cohort_games"][gid] = {
                "season": season,
                "covers": cohort_meta[gid]["covers"],
                "score_disposition": definition.score_disposition,
                "score_match": team["score_match"],
                "sog_disposition": definition.sog_disposition,
                "sog_match": team["sog_match"],
                "ordinary_score": dict(state.ordinary_score),
                "shootout_attempts": dict(state.shootout_attempts),
                "shootout_goals": dict(state.shootout_goals),
                "penalty_calls": len(state.penalty_calls),
                "power_play_state_observations": sum(
                    m.skater_advantage != "even" for _, _, m in state.manpower_transitions),
                "period_regression_events": state.period_regression_events,
                "goalie_id_changes": len(state.goalie_change_observations),
                "shift_interval_dispositions": {
                    "ACCEPT": _metric_int(bundle, gid, "shift_intervals_eligible"),
                    "QUARANTINE": _metric_int(bundle, gid, "shift_intervals_quarantined"),
                    "REJECT": _metric_int(bundle, gid, "shift_intervals_rejected"),
                },
                "metric_duplicate_shift_charts": _metric_int(bundle, gid, "duplicate_shift_charts"),
                "metric_goalie_substitution_changes": _metric_int(
                    bundle, gid, "goalie_substitution_changes_from_pbp_events"),
                "first_event_provenance": {
                    "source_event_id": first_event.source_event_id,
                    "publisher_sort_order": first_event.publisher_sort_order,
                    "period_type": first_event.period_type,
                    "time_in_period": first_event.time_in_period,
                    "event_disposition": first_event.quality.event,
                    "pbp_sha256_raw": first_event.provenance.pbp.sha256_raw,
                    "shift_source_kind": first_event.provenance.shifts.source_kind,
                },
            }
    if game_ids is None and summary["games_replayed"] != len(bundle.games):
        raise InputIntegrityError(f"FULL_FRAME_GAME_REPLAY_COVERAGE {summary['games_replayed']}/{len(bundle.games)}")
    if game_ids is not None and summary["games_replayed"] != len(game_ids):
        raise InputIntegrityError(f"COHORT_REPLAY_COVERAGE {summary['games_replayed']}/{len(game_ids)}")

    summary["team_shot_attempts"] = dict(summary["team_shot_attempts"])
    summary["team_sog_events"] = dict(summary["team_sog_events"])
    summary["shot_events_by_period_type"] = dict(summary["shot_events_by_period_type"])
    summary["ordinary_goals_by_period"] = {
        key: dict(value) for key, value in summary["ordinary_goals_by_period"].items()}
    summary["shootout"] = {
        key: dict(value) if isinstance(value, Counter) else value
        for key, value in summary["shootout"].items()}
    summary["seasons"] = {k: dict(v) for k, v in sorted(summary["seasons"].items())}
    summary["player_targets"] = {
        purpose: dict(counter) for purpose, counter in summary["player_targets"].items()}
    summary["player_target_games"] = {
        purpose: dict(counter) for purpose, counter in summary["player_target_games"].items()}
    summary["player_target_events"] = {
        purpose: dict(counter) for purpose, counter in summary["player_target_events"].items()}
    summary["deployment"] = dict(summary["deployment"])
    return summary


def _target_eligible_by_row(row: dict[str, object], purpose: str) -> bool:
    return row["purpose_value"] is not None


def reconcile_shift_population(bundle: InputBundle) -> dict[str, Any]:
    totals: Counter[str] = Counter()
    per_game: dict[str, Counter[str]] = defaultdict(Counter)
    player_games: dict[tuple[str, str], dict[str, object]] = {}
    malformed_durations = 0
    for interval in iter_shift_intervals(bundle):
        totals[interval.disposition] += 1
        per_game[interval.game_id][interval.disposition] += 1
        key = (interval.game_id, interval.player_id)
        row = player_games.setdefault(key, {
            "dispositions": set(), "player_type": interval.player_type,
            "summed_duration": 0, "official_toi": interval.official_toi_seconds,
            "declared_shift_toi": interval.player_game_shift_toi_seconds,
        })
        if row["player_type"] != interval.player_type:
            raise InputIntegrityError(f"SHIFT_PLAYER_TYPE_CONFLICT {key}")
        if row["official_toi"] != interval.official_toi_seconds:
            raise InputIntegrityError(f"SHIFT_OFFICIAL_TOI_NOT_CONSTANT {key}")
        if row["declared_shift_toi"] != interval.player_game_shift_toi_seconds:
            raise InputIntegrityError(f"SHIFT_PLAYER_GAME_TOI_NOT_CONSTANT {key}")
        row["dispositions"].add(interval.disposition)
        if interval.duration_seconds is not None:
            row["summed_duration"] += interval.duration_seconds
        if (interval.start_seconds is not None and interval.end_seconds is not None and
                interval.duration_seconds is not None and
                interval.end_seconds - interval.start_seconds != interval.duration_seconds):
            malformed_durations += 1
    player_games_by_type: Counter[str] = Counter()
    accepted_player_games_by_type: Counter[str] = Counter()
    toi_by_type: dict[str, Counter[str]] = defaultdict(Counter)
    for record in player_games.values():
        player_type = str(record["player_type"]).lower()
        player_games_by_type[player_type] += 1
        if record["dispositions"] == {"ACCEPT"}:
            accepted_player_games_by_type[player_type] += 1
        official_toi = record["official_toi"]
        if official_toi is not None:
            delta = abs(int(record["summed_duration"]) - int(official_toi))
            toi_by_type[player_type]["compared"] += 1
            if delta <= 30:
                toi_by_type[player_type]["within_30s"] += 1
            else:
                toi_by_type[player_type]["over_30s"] += 1
            if delta > 60:
                toi_by_type[player_type]["over_60s"] += 1
            if record["declared_shift_toi"] is not None and int(record["declared_shift_toi"]) != int(record["summed_duration"]):
                raise InputIntegrityError("SHIFT_SUM_DIFFERS_FROM_RECORDED_PLAYER_GAME_TOI")
    for gid, counts in per_game.items():
        metrics = bundle.game_metrics[gid]
        expected = {
            "ACCEPT": int(metrics["shift_intervals_eligible"]),
            "QUARANTINE": int(metrics["shift_intervals_quarantined"]),
            "REJECT": int(metrics["shift_intervals_rejected"]),
        }
        if dict(counts) != {key: value for key, value in expected.items() if value}:
            raise InputIntegrityError(f"SHIFT_INTERVAL_COUNT_RECONCILIATION {gid}: {dict(counts)} != {expected}")
    for kind, metric_prefix in (("skater", "skater"), ("goalie", "goalie")):
        expected_compared = sum(int(row[f"{metric_prefix}_toi_compared"]) for row in bundle.game_metrics.values())
        expected_30 = sum(int(row[f"{metric_prefix}_toi_within_30s"]) for row in bundle.game_metrics.values())
        actual = toi_by_type[kind]
        if actual["compared"] != expected_compared or actual["within_30s"] != expected_30:
            raise InputIntegrityError(
                f"SHIFT_TOI_RECONCILIATION_MISMATCH {kind}: compared={actual['compared']}/{expected_compared} "
                f"within30={actual['within_30s']}/{expected_30}")
    return {
        "intervals_by_disposition": dict(totals),
        "player_games_by_type": dict(player_games_by_type),
        "accepted_player_games_by_type": dict(accepted_player_games_by_type),
        "toi_reconciliation_by_type": {key: dict(value) for key, value in toi_by_type.items()},
        "shift_duration_interval_mismatches": malformed_durations,
        "games_with_duplicate_charts": sum(int(row["duplicate_shift_charts"]) > 0 for row in bundle.game_metrics.values()),
        "games_with_any_duplicate_intervals": sum(int(row["duplicate_shift_intervals"]) > 0 for row in bundle.game_metrics.values()),
        "games_with_overlapping_shifts": sum(int(row["overlapping_shift_players"]) > 0 for row in bundle.game_metrics.values()),
    }


def _json_default(value):
    if isinstance(value, Counter):
        return dict(value)
    raise TypeError(type(value).__name__)


def render_report(summary: dict[str, Any], shifts: dict[str, Any],
                  body_verification: dict[str, int], issue_count: int,
                  issue_reasons: Counter[str],
                  team_sog_issues: list[dict[str, str]]) -> str:
    cohort_rows = []
    for gid, row in summary["cohort_games"].items():
        cohort_rows.append(
            f"| `{gid}` | {', '.join(row['covers'])} | {row['score_disposition']} / {row['score_match']} | "
            f"{row['sog_disposition']} / {row['sog_match']} | {row['metric_duplicate_shift_charts']} | "
            f"{row['period_regression_events']} | {row['goalie_id_changes']} |")
    season_rows = []
    for season, row in summary["seasons"].items():
        season_rows.append(
            f"| {season} | {row.get('games',0)} | {row.get('events',0):,} | "
            f"{row.get('score_matched',0)}/{row.get('score_eligible',0)} | "
            f"{row.get('sog_matched',0)}/{row.get('sog_eligible',0)} | "
            f"{row.get('sog_quarantined',0)} | "
            f"{row.get('SOG_training_event_eligible',0)}/{row.get('SOG_training_approved',0)} | "
            f"{row.get('GOALS_AGAINST_training_event_eligible',0)}/{row.get('GOALS_AGAINST_training_approved',0)} | "
            f"{row.get('SAVES_training_event_eligible',0)}/{row.get('SAVES_training_approved',0)} | "
            f"{row.get('SHOTS_AGAINST_training_event_eligible',0)}/{row.get('SHOTS_AGAINST_training_approved',0)} |")
    target_rows = []
    for purpose in ("training", "evaluation", "grading"):
        values = summary["player_targets"][purpose]
        for statistic in ("SOG", "GOALS_AGAINST", "SAVES", "SHOTS_AGAINST"):
            target_rows.append(
                f"| {purpose} | {statistic} | {summary['player_target_games'][purpose].get(statistic,0):,} | "
                f"{values.get(statistic+'_approved',0):,} | "
                f"{values.get(statistic+'_event_eligible',0):,} | "
                f"{summary['player_target_events'][purpose].get(statistic,0):,} | "
                f"{len([r for r in summary['player_target_exclusions'][purpose] if r['statistic']==statistic]):,} |")
    target_detail = []
    all_exclusions = [row for purpose in ("training", "evaluation", "grading")
                      for row in summary["player_target_exclusions"][purpose]]
    if all_exclusions:
        target_detail.append("<details><summary>Replay-excluded approved player targets by ID and reason</summary>\n\n")
        target_detail.append("| Game | Player | Statistic | Event issue reason | Label quality reason | Accepted | Replayed | Audit count | Issue detail |\n|---|---:|---|---|---|---:|---:|---:|---|\n")
        seen: set[tuple] = set()
        for row in all_exclusions:
            key = (row["game_id"], row["player_id"], row["statistic"], row["reason_code"])
            if key in seen:
                continue
            seen.add(key)
            target_detail.append(
                f"| `{row['game_id']}` | `{row['player_id']}` | {row['statistic']} | "
                f"`{row['reason_code']}` | `{row['approved_label_reason_code']}` | "
                f"{row['accepted_value']} | {row['replayed_event_count']} | "
                f"{row['audit_event_count']} | {row.get('issue_detail', 'No matching target issue row; see disposition ledger')} |\n")
        target_detail.append("\n</details>\n")
    issue_rows = "\n".join(
        f"| `{reason}` | {count:,} |"
        for reason, count in sorted(issue_reasons.items()))
    shot_rows = []
    for period_type in ("REG", "OT", "SO", "UNKNOWN"):
        values = [summary["shot_events_by_period_type"].get(f"{period_type}:{event_type}", 0)
                  for event_type in ("goal", "shot-on-goal", "missed-shot", "blocked-shot")]
        if any(values):
            shot_rows.append(
                f"| {period_type} | {values[0]:,} | {values[1]:,} | {values[2]:,} | "
                f"{values[3]:,} | {sum(values):,} |")
    shift_toi_rows = []
    for player_type in ("skater", "goalie"):
        counts = shifts["toi_reconciliation_by_type"].get(player_type, {})
        shift_toi_rows.append(
            f"| {player_type} | {counts.get('within_30s',0):,}/{counts.get('compared',0):,} | "
            f"{counts.get('over_30s',0):,} | {counts.get('over_60s',0):,} |")
    team_sog_details = [
        "<details><summary>All official team SOG discrepancy rows (game, side, reason, observed values)</summary>\n\n",
        "| Game | Side | Reason code | Detail |\n|---|---|---|---|\n",
    ]
    team_sog_details.extend(
        f"| `{row['game_id']}` | {row['subject_id']} | `{row['reason_code']}` | {row['detail']} |\n"
        for row in team_sog_issues)
    team_sog_details.append("\n</details>\n")
    sog_quarantined = ", ".join(f"`{gid}`" for gid in summary["team_sog"]["quarantined_games"])
    return f"""# NHL V3 Phase 1 deterministic replay report

**Base:** `33c6b8fad5c36fd7749557c6b56bb21898e33135`

**Input schema:** approved full-frame event schema v1.

**Scope:** research only; no model fitting, probabilities, ROI evaluation, production writes, or historical source edits.

## Replay result

The source-pinned replay processed **{summary['games_replayed']:,}/{summary['frame_games']:,}** games and **{summary['events_replayed']:,}/{summary['frame_events']:,}** PBP events in publisher sort order. Full raw body verification succeeded for **{body_verification.get('pbp',0):,}/4,876** PBP bodies and **{body_verification.get('shifts',0):,}/4,876** shift bodies, including compressed/decompressed hashes, source ID, JSON shape, and payload count.

Accepted team scores: **{summary['team_score']['matched']:,}/{summary['team_score']['eligible']:,} exact**.

Accepted team SOG: **{summary['team_sog']['matched']:,}/{summary['team_sog']['eligible']:,} exact**; **{summary['team_sog']['quarantined']:,}** games remain quarantined by the audited component disposition. IDs: {sog_quarantined}.
Ordinary shot attempts: **{sum(summary['team_shot_attempts'].values()):,}**. Replayed ordinary SOG events: **{sum(summary['team_sog_events'].values()):,}**. Ordinary goals: regulation **{sum(summary['ordinary_goals_by_period']['REG'].values()):,}**, overtime **{sum(summary['ordinary_goals_by_period']['OT'].values()):,}**. Shootout attempts **{sum(summary['shootout']['attempts'].values()):,}** and shootout goals **{sum(summary['shootout']['goals'].values()):,}** remain separate from ordinary counts.

| Period type | Goals | Shot-on-goal events | Missed-shot events | Blocked-shot events | Shot-family rows |
|---|---:|---:|---:|---:|---:|
{chr(10).join(shot_rows)}

| Season | Games | PBP events | Team scores exact / eligible | Team SOG exact / eligible | SOG games quarantined | Player SOG event-eligible / approved | Goalie GA event-eligible / approved | Goalie saves event-eligible / approved | Goalie SA event-eligible / approved |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(season_rows)}

## Target populations

Eligibility uses the approved NHL label reader's purpose-specific values and flags. The replay adds exact accepted event attribution, event-count agreement, and `event_disposition=ACCEPT`. A quarantined or not-applicable label never enters an eligible target count.

| Purpose | Statistic | Games with eligible targets | Approved label rows | Event-eligible player targets | Accepted attributed events | Excluded approved rows |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(target_rows)}

{''.join(target_detail)}

## Chronology, manpower, penalties, goalies, and shifts

- PBP events are consumed in increasing `publisher_sort_order`; source array index is retained for audit. No event is reordered by clock or ID. Period-number regressions remain marked and do not reset or rewrite score state.
- Valid four-digit situation codes retain raw digits and parse to recorded away/home skater counts and goalie-present bits. The replay reports **{summary['manpower']['observations']:,}** valid observations, **{summary['manpower']['transitions']:,}** transitions, and **{summary['manpower']['empty_net_observations']:,}** transitions into an empty-net state.
- Recorded situation/shift comparisons: **{summary['deployment'].get('situation_accept',0):,} ACCEPT / {summary['deployment'].get('situation_quarantine',0):,} QUARANTINE**. Ordinary-shot shooter-on-ice joins: **{summary['deployment'].get('shooter_on_ice_accept',0):,} ACCEPT / {summary['deployment'].get('shooter_on_ice_quarantine',0):,} QUARANTINE**. Direct goalie-to-shift comparisons: **{summary['deployment'].get('goalie_shift_accept',0):,} ACCEPT / {summary['deployment'].get('goalie_shift_quarantine',0):,} QUARANTINE**. These gates do not affect team scoring or event-level goalie identity.
- Penalty calls retained: **{summary['penalties']['calls']:,}**; timing-disposition exclusions: **{summary['penalties']['timing_quarantined']:,}**; duration-disposition exclusions: **{summary['penalties']['duration_missing_or_quarantined']:,}**. Durations stay in source minutes. The source contains **{summary['explicit_delayed_penalty_event_types']:,}** explicitly named delayed-penalty event types. A penalty call is not treated as a service clock; no unobserved delayed-call start, expiration, or penalty-to-manpower link is fabricated.
- Direct `goalieInNetId` values are present on **{summary['goalie']['raw_direct_ids_on_shot_family']:,}** shot-family rows; **{summary['goalie']['accepted_event_attributions']:,}** rows pass the goalie-event attribution disposition. For ordinary on-target events, **{summary['goalie']['direct_event_observations']:,}** direct goalie IDs were accepted and **{summary['goalie']['empty_net_observations']:,}** empty nets were directly indicated by the situation code. Observed goalie ID changes between accepted on-target events: **{summary['goalie']['observed_id_changes']:,}**. Goalie targets use direct PBP event IDs only; shifts never assign saves, SA, or GA.
- Shift intervals by disposition: **{shifts['intervals_by_disposition'].get('ACCEPT',0):,} ACCEPT**, **{shifts['intervals_by_disposition'].get('QUARANTINE',0):,} QUARANTINE**, **{shifts['intervals_by_disposition'].get('REJECT',0):,} REJECT**. Accepted player-games by recorded type: `{shifts['accepted_player_games_by_type']}`. Duplicated charts: **{shifts['games_with_duplicate_charts']}** games; overlapping-shift games: **{shifts['games_with_overlapping_shifts']}**. Shift disposition is a separate component and never changes team scoring.

| Shift type | TOI within 30 seconds / compared | Over 30 seconds | Over 60 seconds |
|---|---:|---:|---:|
{chr(10).join(shift_toi_rows)}

Shift interval duration disagreed with `end_seconds - start_seconds` on **{shifts['shift_duration_interval_mismatches']:,}** rows. Official boxscore TOI remains authoritative.

## Bounded regression cohort

| Game | Case | Score disposition / exact | SOG disposition / exact | Duplicate charts | Period regressions | Observed goalie ID changes |
|---|---|---|---|---:|---:|---:|
{chr(10).join(cohort_rows)}

## Unresolved inherited discrepancies

The exhaustive input issue ledger remains unchanged at `unresolved_issues.csv.gz` (SHA-256 `{{bundle_issue_sha}}`). This replay verified **{issue_count:,}** issue rows across the pinned frame. It is the complete ID-level discrepancy record for every component; the selected team SOG and player-target mismatches are expanded below, while the full immutable ledger remains available at the restore path in the README.

| Reason code | Rows |
|---|---:|
{issue_rows}

The exhaustive ID-level ledger is stored outside Git at `/root/lp-data/nhl-fullframe-event-audit-2026-10-21/derived/hardened-final/unresolved_issues.csv.gz`.

{''.join(team_sog_details)}

The original full-frame report remains [REPORT-FULLFRAME.md](../fullframe-event-audit-2026-10-21/REPORT-FULLFRAME.md); this report does not rewrite it. In particular, the 62 team SOG-mismatch games, player target mismatches, period regressions, and rejected/quarantined shifts remain component-specific exclusions.

## Reproducibility and limitations

- `SOURCE-PINS.json` binds all normalized ledgers, the canonical frame, official team SOG, and the approved label artifact. Input loading fails on a hash, source identity, game/team join, target-copy, or season-coverage mismatch.
- The raw-body pass validated both gzip and decompressed bytes, the NHL game ID and endpoint identity, and payload shape/count for every cached response.
- Deterministic transition and failure-injection tests are in `test_replay_engine.py`; the exact command and result are recorded after the run.
- The replay reconstructs observed events and approved targets. It does not observe player movement, puck possession, continuous puck position, actual delay-penalty start, or continuous deployment between recorded events. Shift charts are recorded deployment intervals, not tracking.
- Prospective simulation accepts only the validated `PregameSnapshot` interface. It receives no historical event stream or postgame target. Phase 2 proposals are in [PHASE2-STOCHASTIC-COMPONENTS.md](PHASE2-STOCHASTIC-COMPONENTS.md); no probability or model is fitted here.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--official", type=Path, default=DEFAULT_OFFICIAL_DIR)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABEL_DIR / "research_label_quality.csv")
    parser.add_argument("--label-summary", type=Path)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--skip-raw-body-verification", action="store_true")
    parser.add_argument("--cohort-only", action="store_true")
    parser.add_argument("--report-out", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    bundle = load_bundle(artifact_dir=args.artifacts, official_dir=args.official,
                         label_path=args.labels, label_summary_path=args.label_summary)
    body_verification = ({"pbp": 0, "shifts": 0} if args.skip_raw_body_verification else
                         verify_all_source_bodies(bundle, args.raw))
    cohort_ids = {row["game_id"] for row in json.loads(
        (HERE / "regression_cohort.json").read_text())["games"]}
    summary = replay_population(bundle, game_ids=cohort_ids if args.cohort_only else None)
    if args.cohort_only:
        shifts = {"intervals_by_disposition": {}, "player_games_by_type": {},
                  "accepted_player_games_by_type": {}, "games_with_duplicate_charts": 0,
                  "games_with_any_duplicate_intervals": 0, "games_with_overlapping_shifts": 0}
        shifts["toi_reconciliation_by_type"] = {}
        shifts["shift_duration_interval_mismatches"] = 0
        issue_count, issue_reasons, target_issues, team_sog_issues = 0, Counter(), {}, []
    else:
        shifts = reconcile_shift_population(bundle)
        issue_count, issue_reasons, target_issues, team_sog_issues = verify_issue_ledger(bundle)
    for purpose in ("training", "evaluation", "grading"):
        for row in summary["player_target_exclusions"][purpose]:
            key = (row["game_id"], row["player_id"], row["statistic"])
            issue = target_issues.get(key)
            if issue is not None:
                row["reason_code"] = issue["reason_code"]
                row["issue_detail"] = issue["detail"]
                row["source_issue_id"] = issue["subject_id"]
            else:
                row["reason_code"] = row["audit_reason_code"] or "REPLAY_TARGET_COUNT_MISMATCH"
                row["issue_detail"] = (
                    "No target_reconciliation row in inherited ledger; event count or disposition "
                    "still failed this purpose-specific replay eligibility gate.")
    summary_json = json.loads(json.dumps(summary, default=_json_default))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(summary_json, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.report_out:
        report = render_report(summary, shifts, body_verification, issue_count, issue_reasons,
                               team_sog_issues)
        report = report.replace("{bundle_issue_sha}", bundle.pins["artifacts"]["unresolved_issues.csv.gz"])
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(report, encoding="utf-8")
    print(json.dumps({
        "games_replayed": summary["games_replayed"],
        "events_replayed": summary["events_replayed"],
        "score_eligible_matched": [summary["team_score"]["matched"], summary["team_score"]["eligible"]],
        "sog_eligible_matched": [summary["team_sog"]["matched"], summary["team_sog"]["eligible"]],
        "body_verification": body_verification,
        "report_out": str(args.report_out) if args.report_out else None,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
