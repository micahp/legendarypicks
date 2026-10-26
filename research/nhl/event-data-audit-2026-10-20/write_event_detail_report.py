#!/usr/bin/env python3
"""Render the detailed event audit report from hash-pinned summary outputs."""
from __future__ import annotations

import json
import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent


def n(value: int) -> str:
    return f"{value:,}"


def pct(value) -> str:
    return "n/a" if value is None else f"{value:.3f}%"


def main() -> None:
    summary_path = HERE / "event_quality_summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError("Run audit_event_detail.py before writing the report")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    def csv_rows(name):
        with (HERE / name).open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    fields = summary["field_completeness"]
    by_season = summary["quality_by_season"]
    labels = summary["approved_label_reconciliation"]
    sog_rows = csv_rows("player_sog_reconciliation.csv")
    goalie_rows = csv_rows("goalie_outcome_reconciliation.csv")
    event_exceptions = csv_rows("event_field_exceptions.csv")
    shift = summary["event_time_shift_alignment"]
    shots = summary["shot_type_split"]
    out = []
    a = out.append
    a("# NHL event-data coverage: detailed field and target audit")
    a("")
    a("This report supersedes any rounded headline in the initial `REPORT-EVENTS.md`. It uses the same")
    a("deterministic 300-game, five-season sample and the exact source bodies, but adds field-level")
    a("completeness, event-time shift checks, and comparisons against the approved label-quality reader.")
    a("")
    a("Research feasibility only. No model fitting, market/ROI analysis, production changes, or full-frame")
    a("event download was performed. The pinned 4,876-game frame is unchanged; 2022 is a partial season")
    a("from 2022-10-11 through 2022-11-27 (343 games in the official frame), sampled at 60 games like each other season.")
    a("")
    a("## Population, sample, and source integrity")
    a("")
    a(f"The sample is {summary['sample_games']} games, 60 per start season, drawn without replacement with seed `20261021` from the {summary['frame_games']}-game official frame. The sample is not the 4,872-game SBR market subset, the 4,763-game goalie-preregistration complete-case subset, or its 3,509-game out-of-fold evaluation population.")
    a("")
    a(f"All {summary['event_bodies_verified']['verified_body_count']} expected event bodies (300 PBP and 300 shift charts) passed manifest, game-ID, row-count, compressed-byte/hash, and decompressed-byte/hash checks. The approved 84,283,212-byte research-label artifact was hash-verified before reading; only `VERIFIED`/`ADJUDICATED` observations with `eligible_grading=true` were used as label targets. Joins use canonical game IDs and numeric NHL player IDs.")
    a("")
    a("## Shot-event field completeness")
    a("")
    a("Denominator is every GameCenter shot event in the sample, including blocked shots, missed shots, goals, and shootout shot events. Direct shooter ID and goal-scorer attribution are reported separately; a credited scorer is used for the SOG credit on a goal event, not represented as a raw `shootingPlayerId`.")
    a("")
    a("| Field | Present / total | Missing | Coverage | Interpretation |")
    a("|---|---:|---:|---:|---|")
    descriptions = {
        "shooter_id_direct": "Published `shootingPlayerId` field is present and numeric.",
        "shot_player_id_attributed": "Direct shooter ID, or credited goal scorer for goal events.",
        "location_xy": "Both finite coordinates are present.",
        "shot_type": "Published nonempty `shotType` is present.",
        "period": "Valid period number and period type are present.",
        "game_clock": "Valid `MM:SS` game clock is present.",
        "period_and_clock": "Both period and game clock are valid.",
        "situation_code": "Published situation code parses as four-position strength state.",
    }
    for key, description in descriptions.items():
        record = fields[key]
        a(f"| `{key}` | {n(record['present'])}/{n(summary['shot_events'])} | {n(record['missing'])} | {pct(record['pct'])} | {description} |")
    a("")
    a(f"The direct `shootingPlayerId` field is absent on {n(fields['shooter_id_direct']['missing'])} goal events; all {n(fields['shooter_id_goal_scorer_only']['present'])} have a credited numeric `scoringPlayerId`, which supplies the SOG player attribution for that goal. This is recorded as a separate fallback role, not as if the raw shooter field were present.")
    a("")
    a(f"Shot type split: unblocked {n(shots['unblocked']['with_type'])}/{n(shots['unblocked']['events'])}; blocked {n(shots['blocked']['with_type'])}/{n(shots['blocked']['events'])}. The unblocked feed is missing {n(shots['unblocked']['events'] - shots['unblocked']['with_type'])} shot types; blocked-shot rows do not carry a shot type in this sample. No shot type is inferred.")
    a("")
    a("| Season | Games | Shot events | Games missing a tracked field | Direct shooter ID | Credited player ID | x/y | Shot type | Period + clock |")
    a("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in summary["season_field_completeness"]:
        season_result = next(s for s in by_season if s["season"] == row["season"])
        a(f"| {row['season']} | {n(season_result['games_sampled'])} | {n(row['shot_events'])} | {season_result['games_missing_any_tracked_shot_field']} | {pct(row['shooter_id_direct']['pct'])} | {pct(row['shot_player_id_attributed']['pct'])} | {pct(row['location_xy']['pct'])} | {pct(row['shot_type']['pct'])} | {pct(row['period_and_clock']['pct'])} |")
    a("")
    a("## Outcome and event reconciliation")
    a("")
    a("| Approved target/stat | Eligible labels in sample | Event match | Mismatch |")
    a("|---|---:|---:|---:|")
    for stat in ("SOG", "SAVES", "SHOTS_AGAINST", "GOALS_AGAINST"):
        row = labels[stat]
        a(f"| `{stat}` | {n(row['eligible'])} | {n(row['matches'])} | {n(row['mismatches'])} |")
    team = summary["team_event_reconciliation"]
    a("")
    a(f"PBP team goals reconcile against official final scores in {team['games_goal_counts_match_after_shootout_rule']}/{summary['sample_games']} games after excluding shootout goal events and crediting the shootout winner with the official +1. Team SOG reconcile in {team['games_team_sog_match']}/{summary['sample_games']} games; the remaining team-side conflicts are retained, not corrected.")
    a("")
    ident = summary["on_target_identity"]
    a(f"For {n(ident['events_regulation_ot'])} non-shootout on-target events, {n(ident['missing_shooter_id'])} lack a usable credited SOG player ID and {n(ident['missing_goalie_id'])} lack `goalieInNetId`. Of the latter, {n(ident['missing_goalie_id_expected_empty_net'])} agree with a no-goalie situation code; {n(ident['missing_goalie_id_unexplained'])} remains unexplained. Empty-net goals are not assigned to a goalie. Goalies with zero TOI remain `NOT_APPLICABLE`; zero-TOI backups eligible as goalie targets: {summary['zero_toi_backups_eligible_as_goalie_targets']}.")
    a("")
    a("The label comparison used accepted values only when the approved reader returned an eligible grading label. Quarantined and not-applicable labels remain present in the per-player CSVs and are not compared as targets. PBP-to-label mismatches identify event reconstruction conflicts; they do not invalidate the approved official label itself.")
    full_label_summary = json.loads((HERE.parent / "official-outcome-backfill-2026-10-20" / "research_label_summary.json").read_text(encoding="utf-8"))
    a("")
    a(f"The approved full-frame label artifact has {full_label_summary['adjudication']['quarantined_goalie_stat_fields']} quarantined goalie statistic labels from two appearances. None falls in this 300-game sample; the {labels['SAVES']['not_applicable']} `NOT_APPLICABLE` rows per goalie statistic in the sample are zero-TOI/nonappearance goalie slots and are excluded.")
    sog_mismatch_rows = [row for row in sog_rows if row["comparison"] == "MISMATCH"]
    goalie_mismatch_rows = [row for row in goalie_rows if row["comparison"] == "MISMATCH"]
    if sog_mismatch_rows or goalie_mismatch_rows:
        a("")
        a("### Unresolved event-vs-label cases")
        a("")
        a("| Game | Statistic | Player ID | Official accepted | PBP event aggregate |")
        a("|---|---|---:|---:|---:|")
        for row in [*sog_mismatch_rows, *goalie_mismatch_rows]:
            value = row.get("pbp_shooter_id_sog") or row.get("pbp_goalie_events")
            a(f"| `{row['game_id']}` | `{row['statistic']}` | {row['player_id']} | {row['accepted_value']} | {value} |")
        a("")
        a("The two SOG player conflicts are on the same two games as the two team-side PBP SOG conflicts. In each, the PBP aggregate is one above the approved official player/team value; the opposing goalie PBP saves and shots-against are also one above their approved values. The evidence localizes each discrepancy to a PBP-vs-official shot-count disagreement, but does not establish which source is wrong or authorize correcting either source. Original approved values are retained.")
    a("")
    a("## Strength states and event-time shift alignment")
    a("")
    a("| Event/player check | Tested | Match/on ice | Boundary ambiguous | Mismatch/off ice |")
    a("|---|---:|---:|---:|---:|")
    a(f"| Shooter at shot event | {n(shift['shooter_events_tested'])} | {n(shift['shooter_on_ice'])} | {n(shift['shooter_boundary_ambiguous'])} | {n(shift['shooter_off_ice'])} |")
    a(f"| Goalie in net at on-target event | {n(shift['goalie_events_tested'])} | {n(shift['goalie_on_ice'])} | {n(shift['goalie_boundary_ambiguous'])} | {n(shift['goalie_off_ice'])} |")
    a(f"| Situation-code skater/goalie counts vs active shifts | {n(shift['situation_events_compared'])} | {n(shift['situation_matches'])} | {n(shift['situation_boundary_ambiguous'])} | {n(shift['situation_mismatches'])} |")
    a("")
    a("Boundary cases are within one second of a shift start/end and are not forced to match or mismatch. Situation checks deduplicate active player IDs, decode the four-digit goalie/skater counts, and exclude shootout periods. The sample contains these non-shootout state classes:")
    a("")
    a("| Situation | Events | Games |")
    a("|---|---:|---:|")
    for state, row in summary["strength_state_events_excluding_shootouts"].items():
        a(f"| `{state}` | {n(row['events'])} | {n(row['games'])} |")
    a("")
    a("The feed distinguishes 5v5, 4v4, 3v3, and empty-net counts directly. `PP_away_*` and `PP_home_*` identify the advantaged team and both teams' skater counts; the opposing side's penalty-kill state is the complement. This supports event-time 5v5/PP/PK/empty-net reconstruction, subject to the shift comparison mismatches and boundary cases above.")
    substitutions = sum(row["goalie_substitution_teams"] for row in by_season)
    substitution_games = sum(row["games_with_goalie_substitution"] for row in by_season)
    a("")
    a(f"Shift charts record more than one goalie for {substitution_games} sampled games ({substitutions} team-game goalie substitution instances). Event-time goalie IDs are mostly represented by the charts, but off-ice checks and the published shift-TOI conflicts below mean shifts should not be treated as perfectly authoritative event lineups.")
    a("")
    a("## Missing, contradictory, or unusable games by season")
    a("")
    a("Contradictions count distinct sampled games per issue type; the expected shootout winner-score convention is excluded. A game is marked unusable for SOG event reconstruction when PBP is absent, an on-target event lacks a credited player ID, or SOG disagrees with an eligible approved label/team total. Goalie event reconstruction is unusable for an unexplained missing goalie ID or eligible label mismatch. Shift features are unusable when charts are missing or a shift/lineup identity, TOI, duplicate, overlap, or event-time check conflicts. These flags do not exclude a game from the frozen frame or invalidate an independent approved official target.")
    a("")
    a("| Season | Sampled | Missing PBP | Missing shifts | Any contradiction | SOG event reconstruction unusable | Goalie event reconstruction unusable | Shift features unusable |")
    a("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in by_season:
        a(f"| {row['season']} | {n(row['games_sampled'])} | {row['games_missing_pbp']} | {row['games_missing_shift_chart']} | {row['games_with_any_contradiction']} | {row['unusable_for_player_sog_events']} | {row['unusable_for_goalie_event_targets']} | {row['unusable_for_shift_features']} |")
    a("")
    missing_counts = ", ".join(f"`{key}` {n(value)}" for key, value in summary["event_field_exception_counts"]["missing_fields"].items())
    goalie_counts = ", ".join(f"`{key}` {n(value)}" for key, value in summary["event_field_exception_counts"]["on_target_goalie_id_status"].items())
    a(f"The event-field exception ledger contains {n(summary['event_field_exception_counts']['exception_event_rows'])} shot-event rows, each linked by `game_id` and source event ID. Tracked missing-field counts: {missing_counts}; goalie-ID status counts on on-target events: {goalie_counts}. See `event_field_exceptions.csv` for exact event-level evidence, including the single unexplained missing goalie ID and both missing coordinate pairs.")
    unexplained = [row for row in event_exceptions if row["goalie_id_status"] == "UNEXPLAINED"]
    coordinate_gaps = [row for row in event_exceptions if "location_xy" in row["missing_fields"].split(";")]
    if unexplained or coordinate_gaps:
        a("")
        a("| Exception | Game / event | Period / clock | Source detail |")
        a("|---|---|---|---|")
        for row in unexplained:
            a(f"| Goal with missing goalie ID | `{row['game_id']}` / `{row['source_event_id']}` | {row['period_type']} {row['period_number']} / {row['time_in_period']} | situation `{row['situation_code']}` has both goalie flags on; the PBP row has no `goalieInNetId` |")
        for row in coordinate_gaps:
            a(f"| Missing x/y pair | `{row['game_id']}` / `{row['source_event_id']}` | {row['period_type']} {row['period_number']} / {row['time_in_period']} | `{row['event_type']}`; x={row['x_coord'] or 'null'}, y={row['y_coord'] or 'null'}, shotType={row['shot_type'] or 'null'} |")
    a("")
    a("| Issue | Distinct games |")
    a("|---|---:|")
    for issue, count in summary["contradictions"]["issue_game_counts"].items():
        a(f"| `{issue}` | {count} |")
    a("")
    a("## Proposed import decision")
    a("")
    a("**Recommendation: proceed with a staged, research-only full-frame import of both PBP and available shift charts as immutable raw artifacts; do not treat the normalized event set as uniformly complete or model-ready.** The sample retrieved every feed for all 300 selected games and supports the event schema in `PROPOSED-SCHEMA.md`. Full import should preserve null shot types/coordinates and issue flags, and should reject or quarantine duplicate/inconsistent shift charts at the derived layer. Verify the same coverage and label checks season by season during import, then publish a full-frame completeness report before modeling from event-derived features.")
    a("")
    estimate = summary["estimated_full_frame_event_bodies"]
    a(f"At the fetcher's 1.1-second request spacing, {estimate['requests']:,} source requests imply a lower-bound spacing time of {estimate['minimum_request_spacing_minutes_at_1_1s']:.2f} minutes before network time or retries. Linear scaling from the sample estimates {estimate['compressed_bytes_by_linear_sample_scaling'] / 1_000_000:.1f} MB compressed; payload size is a sample-based estimate, not a measured full-frame total. Keep raw bodies in durable external artifact storage, with hashes and manifests in Git.")
    a("")
    a("This recommendation is for event-data acquisition and coverage, not model fitting, ROI testing, deployment, or replacing the separate approved outcomes. SOG and goalie-saves baseline research against the approved labels can proceed independently while event ingestion is built.")
    a("")
    a("## Reproduction")
    a("")
    a("```sh")
    a("cd research/nhl/event-data-audit-2026-10-20")
    a("PY=/root/legendarypicks/backend/venv/bin/python")
    a("$PY audit_event_detail.py")
    a("$PY write_event_detail_report.py")
    a("$PY -m pytest tests -q")
    a("```")
    (HERE / "REPORT-DETAIL.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {HERE / 'REPORT-DETAIL.md'} ({len(out)} lines)")


if __name__ == "__main__":
    main()
