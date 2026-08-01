#!/usr/bin/env python3
"""ingest_nfl_projections.py — load 2026 ESPN projections into nfl_player_projections.

Fail-closed. Reads the PINNED ESPN fantasy snapshot
(backend/data/espn_2026_snapshot_page1.json) — never a live projection fetch — extracts the
2026 season projection entry (seasonId=2026, scoringPeriodId=0, statSourceId=1,
statSplitTypeId=0), the ESPN-authored season outlook, and ESPN's published 2025
actual season line (statSourceId=0). It also prefetches ESPN's complete published
quarterback season-stat page to collect explicitly labeled Total QBR and
Adjusted QBR; that response is validated and checksummed before any write. It
maps measured projection stat IDs to named fields, computes the Legendary Picks PPR projection
(backend/ppr_scoring.py), and writes atomically.

Contract (see docs/GOAL-v0.6.13.md):
- REG-projection-source : every row references the pinned snapshot (payload_checksum)
- REG-projection-coverage: >=283 pool projections, 32/32 D/ST mandatory
- REG-projection-null  : players without a projection store NULL, never 0
- Fail-closed          : parse + validate EVERYTHING before BEGIN; one short
                         transaction; rollback on any mismatch; previous good
                         snapshot survives a bad refresh (INSERT OR REPLACE
                         happens only after full validation).
- The only DB touched is LP_DB_PATH (the disposable clone for Phase 3).

Usage: LP_DB_PATH=<clone.db> venv/bin/python ingest_nfl_projections.py
"""
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
import sys
import urllib.request

from ppr_scoring import STAT_IDS, normalize_stats, project_ppr

SNAPSHOT = os.environ.get(
    "ESPN_SNAPSHOT",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "espn_2026_snapshot_page1.json"),
)
PROTEAMS_URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026"
                "?view=proTeamSchedules_wl")
SEASON = 2026
SCORING_PERIOD_ID = 0
STAT_SOURCE_ID = 1
STAT_SPLIT_TYPE_ID = 0
ACTUAL_SEASON = SEASON - 1
ACTUAL_STAT_SOURCE_ID = 0
QBR_URL = (
    "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/"
    "statistics/byathlete?region=us&lang=en&contentorigin=espn&page=1&limit=100"
    f"&season={ACTUAL_SEASON}&seasontype=2"
)
_EXPECTED_DEF_COUNT = 32

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)


def _load_snapshot() -> tuple[list, str]:
    if not os.path.isfile(SNAPSHOT):
        raise RuntimeError(f"pinned snapshot missing: {SNAPSHOT}")
    with open(SNAPSHOT, "rb") as f:
        raw = f.read()
    checksum = hashlib.sha256(raw).hexdigest()
    return json.loads(raw.decode("utf-8")), checksum


def _projection_stats(entity: dict) -> dict | None:
    """Return the 2026 season projection stat map, or None."""
    for s in entity.get("stats") or []:
        if (
            s.get("seasonId") == SEASON
            and s.get("scoringPeriodId") == SCORING_PERIOD_ID
            and s.get("statSourceId") == STAT_SOURCE_ID
            and s.get("statSplitTypeId") == STAT_SPLIT_TYPE_ID
        ):
            return s.get("stats") or {}
    return None


def _actual_stats(entity: dict) -> dict | None:
    """Return ESPN's published prior regular-season total, or None."""
    for s in entity.get("stats") or []:
        if (
            s.get("seasonId") == ACTUAL_SEASON
            and s.get("scoringPeriodId") == SCORING_PERIOD_ID
            and s.get("statSourceId") == ACTUAL_STAT_SOURCE_ID
            and s.get("statSplitTypeId") == STAT_SPLIT_TYPE_ID
        ):
            return s.get("stats") or None
    return None


def _season_outlook(entity: dict) -> str | None:
    outlook = entity.get("seasonOutlook")
    if not isinstance(outlook, str):
        return None
    outlook = outlook.strip()
    return outlook or None


def _ensure_profile_columns(con: sqlite3.Connection) -> None:
    """Add nullable ESPN profile fields to a pre-feature projection table."""
    columns = {r["name"] for r in con.execute("PRAGMA table_info(nfl_player_projections)")}
    additions = {
        "season_outlook": "TEXT",
        "outlook_source": "TEXT",
        "actual_season": "INTEGER",
        "raw_actual_json": "TEXT",
        "actual_qbr": "REAL",
        "actual_passer_rating": "REAL",
        "actual_adj_qbr": "REAL",
        "qbr_source": "TEXT",
        "qbr_payload_checksum": "TEXT",
    }
    for name, sql_type in additions.items():
        if name not in columns:
            con.execute(
                f"ALTER TABLE nfl_player_projections ADD COLUMN {name} {sql_type}"
            )


def _qbr_values(payload: dict) -> dict[str, dict[str, float | None]]:
    """Return ESPN athlete IDs mapped to explicitly named QBR fields.

    The response publishes two columns labeled QBR. We deliberately index by
    its machine names (QBR and adjQBR), never by the duplicate display label,
    and never substitute QBRating (passer rating).
    """
    passing_schema = next(
        (category for category in payload.get("categories") or []
         if category.get("name") == "passing"),
        None,
    )
    if not passing_schema:
        raise RuntimeError("ESPN season-stat response has no passing schema")
    names = passing_schema.get("names") or []
    try:
        qbr_index = names.index("QBR")
        passer_rating_index = names.index("QBRating")
        adj_qbr_index = names.index("adjQBR")
    except ValueError as exc:
        raise RuntimeError("ESPN season-stat response has no named QBR columns") from exc

    pagination = payload.get("pagination") or {}
    if pagination.get("pages") != 1:
        raise RuntimeError(
            f"ESPN QBR preflight expected one page, got {pagination.get('pages')!r}"
        )
    athletes = payload.get("athletes") or []
    if pagination.get("count") != len(athletes) or not athletes:
        raise RuntimeError(
            "ESPN QBR preflight count does not match the complete athlete page"
        )

    result: dict[str, dict[str, float | None]] = {}
    for athlete_row in athletes:
        athlete_id = str((athlete_row.get("athlete") or {}).get("id") or "")
        passing = next(
            (category for category in athlete_row.get("categories") or []
             if category.get("name") == "passing"),
            None,
        )
        if not athlete_id or not passing:
            continue
        values = passing.get("values") or []
        if len(values) <= max(qbr_index, passer_rating_index, adj_qbr_index):
            raise RuntimeError(f"ESPN QBR row {athlete_id} is shorter than its schema")
        result[athlete_id] = {
            "qbr": values[qbr_index],
            "passer_rating": values[passer_rating_index],
            "adj_qbr": values[adj_qbr_index],
        }
    if not result:
        raise RuntimeError("ESPN QBR preflight yielded zero named athlete rows")
    return result


def _fetch_qbr_values() -> tuple[dict[str, dict[str, float | None]], str]:
    with urllib.request.urlopen(QBR_URL, timeout=60) as response:
        raw = response.read()
    payload = json.loads(raw.decode("utf-8"))
    return _qbr_values(payload), hashlib.sha256(raw).hexdigest()


def _build_pro_team_map() -> dict[int, str]:
    with urllib.request.urlopen(PROTEAMS_URL, timeout=60) as r:
        pro_data = json.loads(r.read().decode("utf-8"))
    pro_team_map: dict[int, str] = {}
    for t in pro_data.get("settings", {}).get("proTeams", []):
        tid = t.get("id")
        abbr = t.get("abbrev", "")
        if tid and abbr and tid != 0:
            pro_team_map[int(tid)] = abbr.upper()
    if not pro_team_map:
        raise RuntimeError("proTeams endpoint returned zero teams")
    return pro_team_map


def _position_of(entity: dict) -> str:
    return {
        1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "PK", 16: "DEF",
    }.get(entity.get("defaultPositionId"), "QB")


def ingest():
    entities, checksum = _load_snapshot()
    print(f"snapshot: {len(entities)} entities, sha256 {checksum[:12]}…")
    qbr_by_espn_id, qbr_checksum = _fetch_qbr_values()
    print(
        f"ESPN {ACTUAL_SEASON} Total QBR: {len(qbr_by_espn_id)} athletes, "
        f"sha256 {qbr_checksum[:12]}…"
    )

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # ── identity maps (read-only) ──
    eid_to_pid = {}
    for r in con.execute(
        "SELECT id, espn_id FROM players WHERE league='nfl' AND espn_id IS NOT NULL AND espn_id != 0"
    ):
        eid_to_pid[str(r["espn_id"])] = r["id"]
    print(f"NFL players with espn_id: {len(eid_to_pid)}")

    # Position from the DB player row — the source of truth for the formula.
    # ESPN defaultPositionId has no clean mapping for IDP (LB/CB/S/DE/DT) or
    # P, and those positions are NOT draftable in the room — they must store
    # NULL, never a QB-formula 0.0.
    pid_to_pos = {
        r["id"]: r["position"]
        for r in con.execute("SELECT id, position FROM players WHERE league='nfl'")
    }

    def_to_pid = {
        r["team"]: r["id"]
        for r in con.execute(
            "SELECT id, team FROM players WHERE league='nfl' AND position='DEF' AND active=1"
        )
    }
    pro_team_map = _build_pro_team_map()

    # ── D/ST resolution plan (fail-closed: exactly 32) ──
    dst_resolutions: dict[int, dict] = {}  # player_id -> entity
    seen_teams: set[str] = set()
    for entity in entities:
        if entity.get("defaultPositionId") != 16:
            continue
        pro_team_id = entity.get("proTeamId")
        if not pro_team_id:
            continue
        abbrev = pro_team_map.get(pro_team_id)
        if not abbrev:
            continue
        pid = def_to_pid.get(abbrev)
        if not pid or abbrev in seen_teams:
            continue
        if _projection_stats(entity) is None:
            continue
        seen_teams.add(abbrev)
        dst_resolutions[pid] = entity
    expected_pids = set(def_to_pid.values())
    if len(expected_pids) != _EXPECTED_DEF_COUNT:
        raise RuntimeError(
            f"D/ST preflight: def_to_pid has {len(expected_pids)}, expected {_EXPECTED_DEF_COUNT}"
        )
    if set(dst_resolutions) != expected_pids:
        missing = sorted(expected_pids - set(dst_resolutions))
        raise RuntimeError(
            f"D/ST resolution failed: {len(dst_resolutions)}/{_EXPECTED_DEF_COUNT} "
            f"resolved with projections. Missing: {missing[:6]}"
        )
    print(f"D/ST resolution: {len(dst_resolutions)}/{_EXPECTED_DEF_COUNT} with projections")

    # ── Build ALL rows in memory first (no writes until validated) ──
    rows: list[tuple] = []
    matched = 0
    unmatched = 0
    with_proj = 0
    null_proj = 0
    with_outlook = 0
    with_actual = 0
    for entity in entities:
        eid = str(entity.get("id", ""))
        pid = eid_to_pid.get(eid)
        if pid is None:
            unmatched += 1
            continue
        matched += 1

        if pid in dst_resolutions:
            entity = dst_resolutions[pid]  # canonical D/ST entity
        sm = _projection_stats(entity)
        if _season_outlook(entity) is not None:
            with_outlook += 1
        if _actual_stats(entity) is not None:
            with_actual += 1
        position = pid_to_pos.get(pid) or "QB"
        if not sm or position not in ("QB", "RB", "WR", "TE", "PK", "DEF"):
            null_proj += 1
            # Honest null row: no 2026 projection, or a position the room does
            # not draft (IDP/P). Store NULLs — never zeros.
            rows.append(_row(
                pid, entity, position, None, None, checksum,
                qbr_by_espn_id.get(eid), qbr_checksum,
            ))
            continue
        with_proj += 1
        ppr = project_ppr(position, sm)
        rows.append(_row(
            pid, entity, position, sm, ppr, checksum,
            qbr_by_espn_id.get(eid), qbr_checksum,
        ))

    print(
        f"matched={matched} unmatched={unmatched} "
        f"with_projection={with_proj} null_projection={null_proj} "
        f"with_outlook={with_outlook} with_{ACTUAL_SEASON}_actual={with_actual}"
    )
    if with_proj + null_proj == 0:
        raise RuntimeError("no rows to write — aborting (fail-closed)")

    # ── Single atomic transaction ──
    try:
        con.execute("BEGIN IMMEDIATE")
        _ensure_profile_columns(con)
        write_columns = (
            "player_id", "espn_id", "season", "scoring_period_id",
            "stat_source_id", "stat_split_type_id", "raw_projection_json",
            "projected_games", "pass_att", "pass_cmp", "pass_yds", "pass_td",
            "interceptions", "rush_att", "rush_yds", "rush_td", "receptions",
            "targets", "rec_yds", "rec_td", "fumbles", "fumbles_lost",
            "fg_att", "fg_made", "xp_att", "xp_made", "def_td", "def_int",
            "def_sack", "def_fumble_rec", "def_points_allowed",
            "def_yds_allowed", "lp_ppr_projected_points", "season_outlook",
            "outlook_source", "actual_season", "raw_actual_json",
            "actual_qbr", "actual_passer_rating", "actual_adj_qbr", "qbr_source",
            "qbr_payload_checksum",
            "payload_checksum",
        )
        placeholders = ",".join("?" for _ in write_columns)
        con.executemany(
            f"INSERT OR REPLACE INTO nfl_player_projections "
            f"({','.join(write_columns)}) VALUES ({placeholders})",
            rows,
        )
        con.execute("COMMIT")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        con.close()
        raise

    written = con.execute(
        "SELECT COUNT(*), COUNT(lp_ppr_projected_points) FROM nfl_player_projections WHERE season=?",
        (SEASON,),
    ).fetchone()
    print(f"committed: {written[0]} rows ({written[1]} with PPR projection)")
    con.close()


def _row(pid, entity, position, sm, ppr, checksum, qbr_values=None, qbr_checksum=None):
    sm = normalize_stats(sm)
    actual = normalize_stats(_actual_stats(entity))
    outlook = _season_outlook(entity)
    ids = STAT_IDS
    g = lambda k: sm.get(ids[k]) if sm else None
    return (
        pid,
        int(entity.get("id", 0)),
        SEASON,
        SCORING_PERIOD_ID,
        STAT_SOURCE_ID,
        STAT_SPLIT_TYPE_ID,
        json.dumps(sm, sort_keys=True) if sm else "{}",
        g("games"),
        g("pass_att"), g("pass_cmp"), g("pass_yds"), g("pass_td"), g("interceptions"),
        g("rush_att"), g("rush_yds"), g("rush_td"),
        g("receptions"), g("targets"), g("rec_yds"), g("rec_td"),
        g("fumbles"), g("fumbles_lost"),
        g("fg_att"), g("fg_made"), g("xp_att"), g("xp_made"),
        g("def_td"), g("def_int"), g("def_sack"), g("def_fumble_rec"),
        g("def_points_allowed"), g("def_yds_allowed"),
        ppr,
        outlook,
        "espn" if outlook else None,
        ACTUAL_SEASON if actual else None,
        json.dumps(actual, sort_keys=True) if actual else None,
        qbr_values.get("qbr") if qbr_values else None,
        qbr_values.get("passer_rating") if qbr_values else None,
        qbr_values.get("adj_qbr") if qbr_values else None,
        "espn" if qbr_values else None,
        qbr_checksum if qbr_values else None,
        checksum,
    )


def main():
    ingest()


if __name__ == "__main__":
    main()
