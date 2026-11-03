#!/usr/bin/env python3
"""Read-only Phase 1 inventory and observable play-signature audit.

This script reads the dev SQLite database through SQLite's read-only URI and
query_only mode. Signature tuples preserve raw labels and explicit missing
source joins. They describe observed fields; they do not identify play designs
or concepts.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


HISTORY = range(2022, 2026)
SEASONS = range(2022, 2027)
PLAYCALL_TABLES = {
    "nfl_pbp": ("game_id", "play_id"),
    "nfl_hist_participation": ("nflverse_game_id", "play_id"),
    "nfl_hist_ftn_charting": ("nflverse_game_id", "nflverse_play_id"),
}
RELEVANT_FIELDS = {
    "event": ("play_type", "pass_attempt", "rush_attempt", "qb_dropback", "qb_scramble", "sack", "two_point_attempt"),
    "presentation": (
        "participation_joined", "offense_formation", "offense_personnel", "shotgun", "no_huddle",
        "ftn_joined", "is_motion", "is_play_action", "is_no_huddle",
    ),
    "action_descriptor": ("run_gap", "run_location", "pass_location"),
    "broad_charting_tags": ("is_screen_pass", "is_rpo", "is_trick_play", "is_qb_sneak"),
}
SIGNATURE_CONTEXT = ("starting_hash", "qb_location", "n_offense_backfield", "n_defense_box",
                     "n_blitzers", "n_pass_rushers", "air_yards")
OL_TOKEN = re.compile(r"(?:^|,\s*)(\d+)\s+(C|G|T)(?=,|$)")
SPECIAL_TEAMS_TOKEN = re.compile(r"(?:^|,\s*)(\d+)\s+(K|LS|P)(?=,|$)")


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


def table_columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in con.execute(f'PRAGMA table_info("{table}")')]


def require_columns(con: sqlite3.Connection, table: str, required: set[str]) -> None:
    missing = sorted(required - set(table_columns(con, table)))
    if missing:
        raise RuntimeError(f"{table} is missing required columns: {missing}")


def key_quality(con: sqlite3.Connection, table: str, game_col: str, play_col: str) -> dict:
    result = {}
    for season in SEASONS:
        row = con.execute(
            f'''SELECT COUNT(*) AS rows,
                       COALESCE(SUM("{game_col}" IS NULL OR "{play_col}" IS NULL), 0) AS null_keys,
                       (SELECT COUNT(*) FROM (
                           SELECT "{game_col}", "{play_col}" FROM "{table}" WHERE season=?
                           GROUP BY "{game_col}", "{play_col}" HAVING COUNT(*)>1
                       )) AS duplicate_key_groups
                FROM "{table}" WHERE season=?''',
            (season, season),
        ).fetchone()
        result[str(season)] = dict(row)
    return result


def table_coverage(con: sqlite3.Connection, table: str, game_col: str | None, week_col: str | None) -> dict:
    result = {}
    for season in SEASONS:
        expressions = ['COUNT(*) AS rows']
        if game_col:
            expressions.append(f'COUNT(DISTINCT "{game_col}") AS games')
        if week_col:
            expressions.extend([
                f'MIN("{week_col}") AS min_week',
                f'MAX("{week_col}") AS max_week',
                f'COUNT(DISTINCT "{week_col}") AS weeks',
            ])
        row = con.execute(
            f'SELECT {", ".join(expressions)} '
            f'FROM "{table}" WHERE season=?',
            (season,),
        ).fetchone()
        result[str(season)] = dict(row)
    return result


def source_field_inventory(con: sqlite3.Connection) -> dict:
    patterns = {
        "formation": ("formation",),
        "personnel": ("personnel",),
        "run_gap": ("run_gap",),
        "pass_depth": ("pass_length", "pass_depth", "air_yards"),
        "pass_location": ("pass_location",),
        "route": ("route",),
        "motion": ("motion",),
    }
    matches = {key: [] for key in patterns}
    matches["concept_or_play_name"] = []
    tables = [
        row[0]
        for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    ]
    for table in tables:
        for column in table_columns(con, table):
            lowered = column.lower()
            for family, needles in patterns.items():
                if any(needle in lowered for needle in needles):
                    matches[family].append({"table": table, "column": column})
            if re.search(r"(^|_)(concept|playcall|play_name|formal_playcall)(_|$)", lowered):
                matches["concept_or_play_name"].append({"table": table, "column": column})
    return matches


def category_counts(con: sqlite3.Connection, table: str, column: str, seasons: range) -> dict:
    result = {}
    for season in seasons:
        values = [
            {"value": row[0], "rows": row[1]}
            for row in con.execute(
                f'SELECT "{column}", COUNT(*) FROM "{table}" WHERE season=? '
                f'GROUP BY "{column}" ORDER BY COUNT(*) DESC, "{column}"',
                (season,),
            )
        ]
        result[str(season)] = values
    return result


def play_type_counts(con: sqlite3.Connection) -> dict:
    return {
        str(season): [
            {"value": row[0], "rows": row[1]}
            for row in con.execute(
                "SELECT play_type, COUNT(*) FROM nfl_pbp WHERE season=? "
                "GROUP BY play_type ORDER BY play_type",
                (season,),
            )
        ]
        for season in SEASONS
    }


def season_field_coverage(con: sqlite3.Connection) -> dict:
    query = '''
        SELECT p.season,
               COUNT(*) AS pbp_rows,
               SUM(p.play_type IN ('run','pass')) AS scrimmage_rows,
               SUM(p.play_type='run') AS run_rows,
               SUM(p.play_type='pass') AS pass_rows,
               SUM(p.play_type='run' AND p.run_gap IS NOT NULL) AS run_gap_rows,
               SUM(p.play_type='run' AND p.run_location IS NOT NULL) AS run_location_rows,
               SUM(p.play_type='pass' AND p.pass_location IS NOT NULL) AS pass_location_rows,
               SUM(p.play_type='pass' AND p.air_yards IS NOT NULL) AS air_yards_rows,
               SUM(p.play_type IN ('run','pass') AND p.shotgun IS NOT NULL) AS shotgun_rows,
               SUM(p.play_type IN ('run','pass') AND p.no_huddle IS NOT NULL) AS pbp_no_huddle_rows,
               SUM(p.play_type IN ('run','pass') AND i.nflverse_game_id IS NOT NULL) AS participation_join_rows,
               SUM(p.play_type IN ('run','pass') AND i.offense_formation IS NOT NULL) AS formation_rows,
               SUM(p.play_type IN ('run','pass') AND i.offense_personnel IS NOT NULL) AS personnel_rows,
               SUM(p.play_type IN ('run','pass') AND c.nflverse_game_id IS NOT NULL) AS ftn_join_rows,
               SUM(p.play_type IN ('run','pass') AND c.is_motion IS NOT NULL) AS motion_rows,
               SUM(p.play_type IN ('run','pass') AND c.is_play_action IS NOT NULL) AS play_action_rows,
               SUM(p.play_type IN ('run','pass') AND c.is_no_huddle IS NOT NULL) AS ftn_no_huddle_rows,
               SUM(p.play_type IN ('run','pass') AND c.is_screen_pass IS NOT NULL) AS screen_pass_rows,
               SUM(p.play_type IN ('run','pass') AND c.is_rpo IS NOT NULL) AS rpo_rows,
               SUM(p.play_type IN ('run','pass') AND c.is_trick_play IS NOT NULL) AS trick_play_rows,
               SUM(p.play_type IN ('run','pass') AND c.is_qb_sneak IS NOT NULL) AS qb_sneak_rows,
               SUM(p.play_type IN ('run','pass') AND c.starting_hash IS NOT NULL) AS starting_hash_rows,
               SUM(p.play_type IN ('run','pass') AND c.qb_location IS NOT NULL) AS qb_location_rows,
               SUM(p.play_type IN ('run','pass') AND c.n_offense_backfield IS NOT NULL) AS offense_backfield_rows,
               SUM(p.play_type IN ('run','pass') AND c.n_defense_box IS NOT NULL) AS defense_box_rows,
               SUM(p.play_type IN ('run','pass') AND c.n_blitzers IS NOT NULL) AS blitzers_rows,
               SUM(p.play_type IN ('run','pass') AND c.n_pass_rushers IS NOT NULL) AS pass_rushers_rows
        FROM nfl_pbp p
        LEFT JOIN nfl_hist_participation i
          ON p.game_id=i.nflverse_game_id AND p.play_id=i.play_id
        LEFT JOIN nfl_hist_ftn_charting c
          ON p.game_id=c.nflverse_game_id AND p.play_id=c.nflverse_play_id
        WHERE p.season BETWEEN 2022 AND 2026
        GROUP BY p.season ORDER BY p.season
    '''
    return {str(row["season"]): dict(row) for row in con.execute(query)}


def join_coverage(con: sqlite3.Connection) -> dict:
    result = {}
    source_configs = {
        "participation": ("nfl_hist_participation", "nflverse_game_id", "play_id"),
        "ftn_charting": ("nfl_hist_ftn_charting", "nflverse_game_id", "nflverse_play_id"),
    }
    for season in HISTORY:
        season_result = {}
        for label, (table, game_col, play_col) in source_configs.items():
            row = con.execute(
                f'''SELECT COUNT(*) AS pbp_rows,
                           COALESCE(SUM(s."{game_col}" IS NOT NULL),0) AS matched_rows,
                           COALESCE(SUM(s."{game_col}" IS NULL),0) AS unmatched_rows,
                           COALESCE(SUM(p.play_type IN ('run','pass')),0) AS scrimmage_rows,
                           COALESCE(SUM(p.play_type IN ('run','pass') AND s."{game_col}" IS NOT NULL),0) AS matched_scrimmage_rows,
                           COALESCE(SUM(p.play_type IN ('run','pass') AND s."{game_col}" IS NULL),0) AS unmatched_scrimmage_rows
                    FROM nfl_pbp p LEFT JOIN "{table}" s
                      ON p.game_id=s."{game_col}" AND p.play_id=s."{play_col}"
                    WHERE p.season=?''',
                (season,),
            ).fetchone()
            unmatched_by_type = [
                {"play_type": row[0], "rows": row[1]}
                for row in con.execute(
                    f'''SELECT p.play_type,COUNT(*) FROM nfl_pbp p LEFT JOIN "{table}" s
                          ON p.game_id=s."{game_col}" AND p.play_id=s."{play_col}"
                        WHERE p.season=? AND s."{game_col}" IS NULL
                        GROUP BY p.play_type ORDER BY p.play_type''',
                    (season,),
                )
            ]
            season_result[label] = {**dict(row), "unmatched_by_pbp_play_type": unmatched_by_type}
        result[str(season)] = season_result
    return result


def schedule_game_types(con: sqlite3.Connection) -> dict:
    result = defaultdict(dict)
    for row in con.execute(
        '''WITH observed AS (
               SELECT DISTINCT season,game_id FROM nfl_pbp WHERE season BETWEEN 2022 AND 2026
           )
           SELECT o.season,s.game_type,COUNT(DISTINCT o.game_id) AS games
           FROM observed o LEFT JOIN nfl_schedule s USING(season,game_id)
           GROUP BY o.season,s.game_type ORDER BY o.season,s.game_type'''
    ):
        game_type = row["game_type"] if row["game_type"] is not None else "<unmatched>"
        result[str(row["season"])][game_type] = row["games"]
    return dict(result)


def source_game_types(con: sqlite3.Connection, table: str, game_col: str) -> dict:
    result = defaultdict(dict)
    for row in con.execute(
        f'''WITH observed AS (
                SELECT DISTINCT season,"{game_col}" AS game_id FROM "{table}"
                WHERE season BETWEEN 2022 AND 2026
            )
            SELECT o.season,s.game_type,COUNT(DISTINCT o.game_id) AS games
            FROM observed o LEFT JOIN nfl_schedule s USING(season,game_id)
            GROUP BY o.season,s.game_type ORDER BY o.season,s.game_type'''
    ):
        game_type = row["game_type"] if row["game_type"] is not None else "<unmatched>"
        result[str(row["season"])][game_type] = row["games"]
    return dict(result)


def weekly_coverage(con: sqlite3.Connection) -> dict:
    result = {"nfl_pbp": {}, "nfl_snap_counts": {}}
    for row in con.execute(
        "SELECT season,week,COUNT(*) rows,COUNT(DISTINCT game_id) games "
        "FROM nfl_pbp WHERE season BETWEEN 2022 AND 2026 GROUP BY season,week ORDER BY season,week"
    ):
        result["nfl_pbp"].setdefault(str(row["season"]), []).append(dict(row))
    for row in con.execute(
        "SELECT season,week,COUNT(*) player_rows,COUNT(DISTINCT team) teams,COUNT(DISTINCT player_id) players "
        "FROM nfl_snap_counts WHERE season BETWEEN 2022 AND 2026 GROUP BY season,week ORDER BY season,week"
    ):
        result["nfl_snap_counts"].setdefault(str(row["season"]), []).append(dict(row))
    return result


def personnel_profile(con: sqlite3.Connection) -> dict:
    result = {}
    for season in HISTORY:
        all_values = [row[0] for row in con.execute(
            "SELECT offense_personnel FROM nfl_hist_participation WHERE season=?", (season,)
        )]
        scrimmage_values = [row[0] for row in con.execute(
            '''SELECT i.offense_personnel FROM nfl_pbp p
               JOIN nfl_hist_participation i
                 ON p.game_id=i.nflverse_game_id AND p.play_id=i.play_id
               WHERE p.season=? AND p.play_type IN ('run','pass')''',
            (season,),
        )]

        def profile(values: list[str | None]) -> dict:
            labels = Counter(value for value in values if value is not None)
            explicit_ol6 = sum(bool(value and re.search(r"(?:^|,\s*)6 OL(?:,|$)", value)) for value in values)
            parsed_ol_rows = 0
            parsed_ol6_rows = 0
            st_token_rows = 0
            for value in values:
                if value is None:
                    continue
                ol_counts = [int(number) for number, _ in OL_TOKEN.findall(value)]
                if ol_counts:
                    parsed_ol_rows += 1
                    if sum(ol_counts) >= 6:
                        parsed_ol6_rows += 1
                if SPECIAL_TEAMS_TOKEN.search(value):
                    st_token_rows += 1
            return {
                "rows": len(values),
                "null_rows": sum(value is None for value in values),
                "distinct_nonnull_labels": len(labels),
                "top_raw_labels": [{"value": label, "rows": count} for label, count in labels.most_common(5)],
                "explicit_6_ol_label_rows": explicit_ol6,
                "rows_with_parsed_c_g_t_tokens": parsed_ol_rows,
                "rows_with_parsed_six_or_more_c_g_t": parsed_ol6_rows,
                "rows_with_k_ls_or_p_tokens": st_token_rows,
            }

        result[str(season)] = {
            "all_participation_rows": profile(all_values),
            "matched_pbp_run_pass_rows": profile(scrimmage_values),
            "ol6_method": "raw '6 OL' token and/or sum of raw C/G/T count tokens; raw source string remains authoritative",
        }
    return result


def signature_tuple(row: sqlite3.Row) -> tuple:
    """Build a layered observed-field signature; this is not a play-design ID."""
    return tuple(
        (name, tuple(row[field] for field in fields))
        for name, fields in RELEVANT_FIELDS.items()
    )


def signature_counts(con: sqlite3.Connection) -> dict:
    query = '''
        SELECT p.season,p.posteam,p.play_type,p.pass_attempt,p.rush_attempt,p.qb_dropback,
               p.qb_scramble,p.sack,p.two_point_attempt,
               (i.nflverse_game_id IS NOT NULL) AS participation_joined,
               i.offense_formation,i.offense_personnel,p.shotgun,p.no_huddle,
               (c.nflverse_game_id IS NOT NULL) AS ftn_joined,
               c.is_motion,c.is_play_action,c.is_no_huddle,
               p.run_gap,p.run_location,p.pass_location,
               c.is_screen_pass,c.is_rpo,c.is_trick_play,c.is_qb_sneak
        FROM nfl_pbp p
        LEFT JOIN nfl_hist_participation i
          ON p.game_id=i.nflverse_game_id AND p.play_id=i.play_id
        LEFT JOIN nfl_hist_ftn_charting c
          ON p.game_id=c.nflverse_game_id AND p.play_id=c.nflverse_play_id
        WHERE p.season BETWEEN 2022 AND 2026
    '''
    sets = defaultdict(lambda: {
        population: {**{name: set() for name in RELEVANT_FIELDS},
                    "combined_observed_tuple": set(), "team_observed_tuple": set()}
        for population in ("all_pbp_rows", "run_pass_scrimmage")
    })
    rows_by_population = Counter()
    for row in con.execute(query):
        season = str(row["season"])
        parts = signature_tuple(row)
        populations = ["all_pbp_rows"]
        if row["play_type"] in ("run", "pass"):
            populations.append("run_pass_scrimmage")
        for population in populations:
            rows_by_population[(season, population)] += 1
            levels = sets[season][population]
            for name, values in parts:
                levels[name].add(values)
            levels["combined_observed_tuple"].add(parts)
            levels["team_observed_tuple"].add((row["posteam"], parts))
    return {
        season: {
            population: {
                "pbp_rows": rows_by_population[(season, population)],
                "unique_tuples_including_unknowns": {name: len(values) for name, values in levels.items()},
                "equality_claim": "same stored-field tuple only; not an exact play-design or concept match",
            }
            for population, levels in populations.items()
        }
        for season, populations in sorted(sets.items())
    }


def manifest_provenance(con: sqlite3.Connection) -> list[dict]:
    return [
        dict(row)
        for row in con.execute(
            '''SELECT source,season,file,sha256,file_rows,stored_rows,attribution,loaded_at
               FROM nfl_hist_loads
               WHERE source IN ('participation','ftn_charting','snap_counts')
                 AND season BETWEEN 2022 AND 2026
               ORDER BY source,season'''
        )
    ]


def file_state(path: Path) -> dict:
    files = []
    for candidate in (path, Path(str(path) + "-wal")):
        if candidate.exists():
            stat = candidate.stat()
            files.append({
                "path": str(candidate.resolve()),
                "bytes": stat.st_size,
                "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            })
    return {"files": files}


def collect(path: Path) -> dict:
    con = open_readonly(path)
    try:
        require_columns(con, "nfl_pbp", {"season", "week", "game_id", "play_id", "play_type", "run_gap",
                                          "run_location", "pass_location", "air_yards", "shotgun", "no_huddle"})
        require_columns(con, "nfl_hist_participation", {"season", "nflverse_game_id", "play_id",
                                                          "offense_formation", "offense_personnel"})
        require_columns(con, "nfl_hist_ftn_charting", {"season", "nflverse_game_id", "nflverse_play_id",
                                                        "is_motion", "is_play_action", "is_no_huddle",
                                                        "is_screen_pass", "is_rpo", "is_trick_play", "is_qb_sneak",
                                                        "starting_hash", "qb_location", "n_offense_backfield",
                                                        "n_defense_box", "n_blitzers", "n_pass_rushers"})
        require_columns(con, "nfl_schedule", {"season", "game_id", "game_type"})
        require_columns(con, "nfl_snap_counts", {"season", "week", "player_id", "team", "off_snaps", "st_snaps"})

        play_types = play_type_counts(con)
        pbp_summary = table_coverage(con, "nfl_pbp", "game_id", "week")
        participation_summary = table_coverage(con, "nfl_hist_participation", "nflverse_game_id", None)
        ftn_summary = table_coverage(con, "nfl_hist_ftn_charting", "nflverse_game_id", "week")
        snap_summary = table_coverage(con, "nfl_snap_counts", None, "week")

        key_audit = {
            table: key_quality(con, table, *key)
            for table, key in PLAYCALL_TABLES.items()
        }
        field_coverage = season_field_coverage(con)
        join_audit = join_coverage(con)

        schedule = schedule_game_types(con)
        snap_type_rows = category_counts(con, "nfl_hist_snap_counts", "game_type", HISTORY)
        signature_profile = signature_counts(con)
        source_fields = source_field_inventory(con)

        provenance = manifest_provenance(con)
        manifest_pbp_rows = con.execute(
            "SELECT COUNT(*) FROM nfl_hist_loads WHERE lower(source) IN ('pbp','play_by_play','nfl_pbp')"
        ).fetchone()[0]
        provenance_summary = {
            "load_manifest": provenance,
            "nfl_pbp_load_manifest_rows": manifest_pbp_rows,
            "nfl_pbp_provenance_note": "The table has no matching per-season entry in nfl_hist_loads; its in-repo producer is backend/ingest_nfl_pbp_logs.py.",
        }

        return {
            "run_at_utc": datetime.now(timezone.utc).isoformat(),
            "database": {"path": str(path.resolve()), **file_state(path),
                         "schema_version": con.execute("PRAGMA schema_version").fetchone()[0],
                         "data_version": con.execute("PRAGMA data_version").fetchone()[0],
                         "read_only": True, "query_only": True},
            "scope": {"historical_seasons": list(HISTORY), "current_observation_season": 2026,
                      "join_key_rule": "Exact source key join on game ID and native play ID; no fuzzy match.",
                      "play_signature_warning": "A repeated observed-field signature is not evidence of an identical play design or concept."},
            "schema": {
                "columns": {table: table_columns(con, table) for table in PLAYCALL_TABLES},
                "relevant_fields_by_family": source_fields,
                "field_interpretation_notes": {
                    "air_yards": "Numeric pass outcome/trajectory field; not a route tree or named concept.",
                    "nfl_hist_depth_charts.formation": "Roster/depth-chart field, not per-play offensive formation.",
                    "offense_personnel": "Preserve exact raw strings; observed value encoding differs by season.",
                    "nulls": "Keep null values distinct from rows with no matched source record.",
                },
            },
            "coverage": {
                "nfl_pbp": pbp_summary,
                "nfl_hist_participation": participation_summary,
                "nfl_hist_ftn_charting": ftn_summary,
                "nfl_snap_counts": snap_summary,
                "nfl_hist_snap_counts_game_type_values": snap_type_rows,
                "pbp_game_types_via_nfl_schedule": schedule,
                "participation_game_types_via_nfl_schedule": source_game_types(
                    con, "nfl_hist_participation", "nflverse_game_id"
                ),
                "ftn_game_types_via_nfl_schedule": source_game_types(
                    con, "nfl_hist_ftn_charting", "nflverse_game_id"
                ),
                "weekly_pbp_and_current_snap_counts": weekly_coverage(con),
                "2026_direct_table_rows": {
                    table: con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE season=2026').fetchone()[0]
                    for table in ("nfl_pbp", "nfl_hist_participation", "nfl_hist_ftn_charting", "nfl_snap_counts")
                },
            },
            "field_coverage_on_run_pass_rows": field_coverage,
            "play_type_rows_by_season": play_types,
            "raw_categories": {
                "offense_formation_2022_2025": category_counts(con, "nfl_hist_participation", "offense_formation", HISTORY),
                "run_gap_2022_2026": category_counts(con, "nfl_pbp", "run_gap", SEASONS),
                "run_location_2022_2026": category_counts(con, "nfl_pbp", "run_location", SEASONS),
                "pass_location_2022_2026": category_counts(con, "nfl_pbp", "pass_location", SEASONS),
            },
            "personnel_profile": personnel_profile(con),
            "key_quality": key_audit,
            "exact_join_coverage": join_audit,
            "source_provenance": provenance_summary,
            "hierarchical_signature_counts": signature_profile,
            "signature_schema": {
                "event": {"fields": list(RELEVANT_FIELDS["event"]), "provenance": "nfl_pbp", "confidence": "high for recorded event label; not design identity"},
                "presentation": {"fields": list(RELEVANT_FIELDS["presentation"]), "provenance": "nfl_hist_participation, nfl_pbp, nfl_hist_ftn_charting", "confidence": "high for present literal labels; joined coverage is source- and season-specific"},
                "action_descriptor": {"fields": list(RELEVANT_FIELDS["action_descriptor"]), "provenance": "nfl_pbp", "confidence": "high for recorded values; coarse execution descriptors, not an exact design"},
                "broad_charting_tags": {"fields": list(RELEVANT_FIELDS["broad_charting_tags"]), "provenance": "nfl_hist_ftn_charting", "confidence": "high for present literal tags; broad charting categories, not exact play designs"},
                "context_excluded_from_signature_equality": {"fields": list(SIGNATURE_CONTEXT), "provenance": "nfl_hist_ftn_charting and nfl_pbp", "confidence": "recorded context/outcome fields; retained as attributes, not stable design identity"},
                "concept": {"value": None, "status": "unresolved_without_route_or_design_annotation", "confidence": "none"},
                "record_identity": {"fields": ["game_id", "play_id"], "confidence": "high for a unique source execution record"},
                "same_tuple_interpretation": "Same tuple means same observed values and source-join state only.",
            },
        }
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="SQLite dev DB path; opened read-only")
    parser.add_argument("--out", type=Path, help="write the JSON report to this path instead of stdout")
    args = parser.parse_args()
    result = collect(args.db)
    rendered = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
