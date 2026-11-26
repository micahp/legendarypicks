"""Derive opportunity-based stats from the archived Madden 64 event hooks."""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "docs/research/madden64-statistical-study"
FULL_DATA = DATA / "additional-25-data/additional-25-full-data.csv"
GAME_STATS = DATA / "additional-25-data/additional-25-game-stats.csv"
OUTPUT_CSV = DATA / "additional-25-data/additional-25-advanced-stats.csv"
OUTPUT_JSON = DATA / "additional-25-advanced-stats.json"

# These labels follow the validation report. Event types 3-8 and 12 remain
# candidate labels: their event/player deltas reconcile, but not every source
# generation path is mapped. Rush and receiving event paths are source-mapped.
EVENT_TYPES = {
    3: "pass_attempts",
    4: "completions",
    5: "net_pass_yards",
    7: "interceptions",
    8: "sacks",
    9: "rush_attempts",
    10: "rush_yards",
    12: "fumbles_recorded",
    13: "receptions",
    14: "receiving_yards",
}
COUNTER_FIELDS = {
    "total_offense": "total_offense_candidate",
    "passing_yards": "passing_yards_candidate",
    "rushing_yards": "rushing_yards_candidate",
    "turnovers": "turnovers_candidate",
    "score": "score_candidate",
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ratio(numerator, denominator):
    return round(numerator / denominator, 6) if denominator else None


def summarize(rows):
    totals = Counter()
    for row in rows:
        for field in (
            "pass_attempts", "completions", "net_pass_yards", "interceptions",
            "sacks", "rush_attempts", "rush_yards", "fumbles_recorded",
            "receiving_yards", "team_turnovers_candidate",
        ):
            totals[field] += row[field]
    attempts = totals["pass_attempts"]
    dropbacks = attempts + totals["sacks"]
    carries = totals["rush_attempts"]
    scrimmage_opportunities = attempts + carries
    all_opportunities = dropbacks + carries
    return {
        "team_games": len(rows),
        "games_entering_overtime_candidate": len({
            row["game_id"] for row in rows if row["entered_overtime_candidate"]
        }),
        "pass_attempts": attempts,
        "completions": totals["completions"],
        "completion_rate": ratio(totals["completions"], attempts),
        "net_pass_yards": totals["net_pass_yards"],
        "net_pass_yards_per_attempt": ratio(totals["net_pass_yards"], attempts),
        "sacks": totals["sacks"],
        "dropbacks": dropbacks,
        "net_pass_yards_per_dropback": ratio(totals["net_pass_yards"], dropbacks),
        "sack_rate_per_dropback": ratio(totals["sacks"], dropbacks),
        "interceptions": totals["interceptions"],
        "interceptions_per_attempt": ratio(totals["interceptions"], attempts),
        "rush_attempts": carries,
        "rush_yards": totals["rush_yards"],
        "rush_yards_per_carry": ratio(totals["rush_yards"], carries),
        "fumbles_recorded": totals["fumbles_recorded"],
        "team_turnovers_candidate": totals["team_turnovers_candidate"],
        "turnovers_minus_interceptions_candidate": (
            totals["team_turnovers_candidate"] - totals["interceptions"]
        ),
        "pass_share_excluding_sacks": ratio(attempts, scrimmage_opportunities),
        "pass_share_including_sacks": ratio(dropbacks, all_opportunities),
        "receiving_yards": totals["receiving_yards"],
    }


def main():
    with GAME_STATS.open(newline="", encoding="utf-8") as stream:
        game_stats = list(csv.DictReader(stream))
    if len(game_stats) != 25 or len({row["game_id"] for row in game_stats}) != 25:
        raise SystemExit("Expected 25 unique archived team-game summaries")

    event_totals = defaultdict(Counter)
    event_rows = defaultdict(Counter)
    sack_yards_by_frame = defaultdict(int)
    sack_frames = set()
    negative_pass_rows = []
    with FULL_DATA.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["kind"] != "event":
                continue
            team = int(row["team"])
            if team not in (0, 1):
                continue
            slot, event_type = map(int, row["index"].split(":"))
            value = int(row["value"])
            key = (row["game_id"], team)
            if event_type in EVENT_TYPES:
                event_totals[key][event_type] += value
                event_rows[key][event_type] += 1
            frame_key = (row["game_id"], team, int(row["frame"]))
            if event_type == 8:
                sack_frames.add(frame_key)
            elif event_type == 5:
                sack_yards_by_frame[frame_key] += value
                if value < 0:
                    negative_pass_rows.append((frame_key, value))

    output_rows = []
    for source in game_stats:
        game_id = source["game_id"]
        quarter_minutes = int(source["quarter_minutes"])
        for team in (0, 1):
            key = (game_id, team)
            values = event_totals[key]
            counts = event_rows[key]
            row = {
                "game_id": game_id,
                "quarter_minutes": quarter_minutes,
                "entered_overtime_candidate": (
                    source["entered_overtime_candidate"].lower() == "true"
                ),
                "team_index": team,
                "candidate_rng_word": int(source["candidate_rng_word"]),
            }
            for event_type, field in EVENT_TYPES.items():
                # Yardage types are sums; opportunity/event types are counts.
                row[field] = (values[event_type] if event_type in (5, 10, 14)
                              else counts[event_type])
            for out_name, source_name in COUNTER_FIELDS.items():
                row[f"team_{out_name}_candidate"] = int(
                    source[f"team{team}_{source_name}"]
                )
            row["completion_rate"] = ratio(row["completions"], row["pass_attempts"])
            row["net_pass_yards_per_attempt"] = ratio(
                row["net_pass_yards"], row["pass_attempts"]
            )
            dropbacks = row["pass_attempts"] + row["sacks"]
            row["dropbacks"] = dropbacks
            row["net_pass_yards_per_dropback"] = ratio(
                row["net_pass_yards"], dropbacks
            )
            row["sack_rate_per_dropback"] = ratio(row["sacks"], dropbacks)
            row["interceptions_per_attempt"] = ratio(
                row["interceptions"], row["pass_attempts"]
            )
            row["rush_yards_per_carry"] = ratio(
                row["rush_yards"], row["rush_attempts"]
            )
            opportunities = row["pass_attempts"] + row["rush_attempts"]
            row["pass_share_excluding_sacks"] = ratio(
                row["pass_attempts"], opportunities
            )
            row["pass_share_including_sacks"] = ratio(
                dropbacks, opportunities + row["sacks"]
            )
            row["team_turnover_minus_interceptions_candidate"] = (
                row["team_turnovers_candidate"] - row["interceptions"]
            )
            output_rows.append(row)

    if len(output_rows) != 50:
        raise SystemExit(f"Expected 50 team-games, got {len(output_rows)}")
    sums = Counter()
    for row in output_rows:
        for field in (
            "pass_attempts", "completions", "net_pass_yards", "interceptions",
            "sacks", "rush_attempts", "rush_yards", "fumbles_recorded",
            "receiving_yards",
        ):
            sums[field] += row[field]
        if row["team_total_offense_candidate"] != (
            row["team_passing_yards_candidate"] + row["team_rushing_yards_candidate"]
        ):
            raise SystemExit(f"Total-offense reconciliation failed for {row['game_id']} team {row['team_index']}")
        if row["net_pass_yards"] != row["team_passing_yards_candidate"]:
            raise SystemExit(f"Pass-yard event/counter mismatch for {row['game_id']} team {row['team_index']}")
        if row["rush_yards"] != row["team_rushing_yards_candidate"]:
            raise SystemExit(f"Rush-yard event/counter mismatch for {row['game_id']} team {row['team_index']}")
        residual = row["team_turnover_minus_interceptions_candidate"]
        if residual < 0 or residual > row["fumbles_recorded"]:
            raise SystemExit(f"Turnover/fumble bound failed for {row['game_id']} team {row['team_index']}")

    expected = {
        "pass_attempts": 1673, "completions": 648, "net_pass_yards": 6682,
        "interceptions": 134, "sacks": 107, "rush_attempts": 609,
        "rush_yards": 557, "fumbles_recorded": 11, "receiving_yards": 7559,
    }
    if dict(sums) != expected:
        raise SystemExit(f"Archived event totals differ from reviewed findings: {dict(sums)}")
    sack_yards = sum(sack_yards_by_frame.get(frame, 0) for frame in sack_frames)
    if len(sack_frames) != 107 or sack_yards != -877:
        raise SystemExit(f"Sack-yard reconciliation failed: {len(sack_frames)} frames, {sack_yards} yards")
    nonsack_negative = [value for frame, value in negative_pass_rows if frame not in sack_frames]
    if len(nonsack_negative) != 49 or sum(nonsack_negative) != -121:
        raise SystemExit("Negative completion-yard reconciliation failed")

    columns = list(output_rows[0])
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(output_rows)

    groups = {}
    for minutes in sorted({row["quarter_minutes"] for row in output_rows}):
        subset = [row for row in output_rows if row["quarter_minutes"] == minutes]
        groups[str(minutes)] = summarize(subset)
    report = {
        "status": "derived_from_archived_hook_events",
        "checkpoint_commit": "922671ac4d62b016c559ea01ed31792653ea5c80",
        "source_files": {
            FULL_DATA.name: sha256(FULL_DATA),
            GAME_STATS.name: sha256(GAME_STATS),
        },
        "games": 25,
        "team_games": 50,
        "definitions": {
            "pass_attempts": "Count of event type 3 rows.",
            "completions": "Count of event type 4 rows.",
            "net_pass_yards": "Signed sum of event type 5; includes sack and negative completion yardage.",
            "interceptions": "Count of event type 7 rows.",
            "sacks": "Count of event type 8 rows; sack frames matched to negative type 5 yardage.",
            "rush_attempts": "Count of event type 9 rows.",
            "rush_yards": "Signed sum of event type 10 rows.",
            "fumbles_recorded": "Count of event type 12 rows; lost fumbles are not identified.",
            "sack_rate_per_dropback": "Sacks / (pass attempts + sacks).",
            "pass_share_excluding_sacks": "Pass attempts / (pass attempts + rush attempts).",
            "pass_share_including_sacks": "(pass attempts + sacks) / (pass attempts + sacks + rush attempts).",
        },
        "event_label_status": "Counts reconcile to archived event/player deltas and the reviewed report. Types 3-8 and 12 remain candidate labels because not every source event-generation path is mapped; types 9-10 have source-mapped rush semantics.",
        "overall": summarize(output_rows),
        "by_quarter_minutes": groups,
        "reconciliation": {
            "team_games_with_total_offense_equal_pass_plus_rush": 50,
            "team_games_with_pass_yard_events_equal_counter": 50,
            "team_games_with_rush_yard_events_equal_counter": 50,
            "sack_frames": len(sack_frames),
            "sack_associated_passing_yards": sack_yards,
            "negative_non_sack_passing_yard_rows": len(nonsack_negative),
            "negative_non_sack_passing_yards": sum(nonsack_negative),
            "team_turnover_minus_interception_residual_sum": sum(
                row["team_turnover_minus_interceptions_candidate"]
                for row in output_rows
            ),
            "lost_fumbles_identified": False,
            "screenshots_independently_reconcile_all_25_final_scores": False,
        },
        "limitations": [
            "All 25 games are the same Seattle-at-Green-Bay CPU exhibition across three quarter settings.",
            "Derived totals are whole-game values; V1 final counters do not split regulation from overtime. Games with a candidate overtime period are flagged.",
            "Run end screenshots show gameplay rather than final box scores; scores and counters are not independently screen-verified for every game.",
            "Recorded fumbles are not classified as lost; turnover residuals are not relabeled as verified lost fumbles.",
            "Archived event hooks do not contain complete pre-snap play-call decisions, so pass selection causes remain unresolved.",
        ],
    }
    OUTPUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"csv": str(OUTPUT_CSV), "json": str(OUTPUT_JSON),
                      "overall": report["overall"],
                      "reconciliation": report["reconciliation"]}, indent=2))


if __name__ == "__main__":
    main()
