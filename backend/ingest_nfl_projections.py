#!/usr/bin/env python3
"""ingest_nfl_projections.py — load 2026 ESPN projections into nfl_player_projections.

Deterministic, fail-closed. Reads the PINNED ESPN snapshot
(backend/data/espn_2026_snapshot_page1.json) — never a live fetch — extracts the
2026 season projection entry (seasonId=2026, scoringPeriodId=0, statSourceId=1,
statSplitTypeId=0), maps measured ESPN stat IDs to named fields, computes the
Legendary Picks PPR projection (backend/ppr_scoring.py), and writes atomically.

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
        position = pid_to_pos.get(pid) or "QB"
        if not sm or position not in ("QB", "RB", "WR", "TE", "PK", "DEF"):
            null_proj += 1
            # Honest null row: no 2026 projection, or a position the room does
            # not draft (IDP/P). Store NULLs — never zeros.
            rows.append(_row(pid, entity, position, None, None, checksum))
            continue
        with_proj += 1
        ppr = project_ppr(position, sm)
        rows.append(_row(pid, entity, position, sm, ppr, checksum))

    print(
        f"matched={matched} unmatched={unmatched} "
        f"with_projection={with_proj} null_projection={null_proj}"
    )
    if with_proj + null_proj == 0:
        raise RuntimeError("no rows to write — aborting (fail-closed)")

    # ── Single atomic transaction ──
    try:
        con.execute("BEGIN IMMEDIATE")
        con.executemany(
            """INSERT OR REPLACE INTO nfl_player_projections
               (player_id, espn_id, season, scoring_period_id, stat_source_id,
                stat_split_type_id, raw_projection_json, projected_games,
                pass_att, pass_cmp, pass_yds, pass_td, interceptions,
                rush_att, rush_yds, rush_td,
                receptions, targets, rec_yds, rec_td,
                fumbles, fumbles_lost,
                fg_att, fg_made, xp_att, xp_made,
                def_td, def_int, def_sack, def_fumble_rec,
                def_points_allowed, def_yds_allowed,
                lp_ppr_projected_points, fetched_at, payload_checksum)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),?)""",
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


def _row(pid, entity, position, sm, ppr, checksum):
    sm = normalize_stats(sm)
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
        checksum,
    )


def main():
    ingest()


if __name__ == "__main__":
    main()
