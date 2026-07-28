#!/usr/bin/env python3
from __future__ import annotations
"""
ingest_nfl_adp.py — fetch real ESPN fantasy ADP for the 2026 draft season.

Source: ESPN's public fantasy API (same unauthenticated family as roster_sync).
Join: players.espn_id = feed.id (already populated by roster_sync.py for NFL).
D/ST: ESPN keys them with negative ids (-16000 - proTeamId); resolved via the
  published proTeams map (abbrev → team), joined to players by team + position='DEF'.
  Fail-closed: proTeams fetch must succeed; all 32 active DEF teams must resolve before
  any write; partial resolution aborts with exit 1.
Writes one row per (player_id, season) into nfl_adp — refreshable snapshot.

Usage: python3 ingest_nfl_adp.py
"""
import json
import os
import sqlite3
import sys
import urllib.request

URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/players"
       "?scoringPeriodId=0&view=kona_player_info")
PROTEAMS_URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026"
                "?view=proTeamSchedules_wl")
HEADERS = {
    "x-fantasy-filter": json.dumps({
        "players": {
            "limit": 3000,
            "sortDraftRanks": {"sortPriority": 1, "sortAsc": True, "value": "STANDARD"},
        }
    }),
}
SEASON = 2026
_EXPECTED_DEF_COUNT = 32

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)


def _fetch_page(offset: int) -> list:
    """Fetch one page of players from ESPN's ADP API."""
    hdrs = dict(HEADERS)
    hdrs["x-fantasy-filter"] = json.dumps({
        "players": {
            "limit": 3000,
            "offset": offset,
            "sortDraftRanks": {"sortPriority": 1, "sortAsc": True, "value": "STANDARD"},
        }
    })
    req = urllib.request.Request(URL, headers=hdrs)
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode("utf-8")
    return json.loads(body)


def _build_pro_team_map() -> dict[int, str]:
    """Fetch the published proTeams endpoint.  Fails closed — raises on error."""
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
    print(f"proTeams loaded: {len(pro_team_map)} teams")
    return pro_team_map


def _build_dst_resolutions(
    all_entities: list,
    pro_team_map: dict[int, str],
    def_to_pid: dict[str, int],
) -> list[tuple[int, int, dict]]:
    """Scan all fetched entities for D/ST.  Return [(player_id, espn_id, entity), ...].

    Must resolve exactly _EXPECTED_DEF_COUNT unique player_ids, else raises.
    Nothing is written — pure computation.
    """
    seen_pids: set[int] = set()
    resolutions: list[tuple[int, int, dict]] = []
    unmatched: list[str] = []

    for entity in all_entities:
        if entity.get("defaultPositionId") != 16:
            continue
        pro_team_id = entity.get("proTeamId")
        if not pro_team_id:
            continue
        abbrev = pro_team_map.get(pro_team_id)
        if not abbrev:
            unmatched.append(
                f"{entity.get('fullName','?')} proTeamId={pro_team_id} not in map"
            )
            continue
        pid = def_to_pid.get(abbrev)
        if not pid:
            unmatched.append(
                f"{entity.get('fullName','?')} abbrev={abbrev} not in players"
            )
            continue
        espn_id = -16000 - pro_team_id
        if pid in seen_pids:
            continue  # duplicate D/ST entity
        # Reject entities whose published ADP is null — all 32 must have real ADP
        ownership = entity.get("ownership", {}) or {}
        if ownership.get("averageDraftPosition") is None:
            unmatched.append(
                f"{entity.get('fullName','?')} abbrev={abbrev} has null ADP"
            )
            continue
        seen_pids.add(pid)
        resolutions.append((pid, espn_id, entity))

    # Must resolve ALL active DEF player_ids exactly — no more, no fewer.
    # A partial match (e.g. 32 of 33) is a failure even if count=32.
    expected_pids = set(def_to_pid.values())
    if len(expected_pids) != _EXPECTED_DEF_COUNT:
        raise RuntimeError(
            f"D/ST preflight: def_to_pid has {len(expected_pids)} entries, "
            f"expected {_EXPECTED_DEF_COUNT}"
        )
    if seen_pids != expected_pids:
        missing = sorted(expected_pids - seen_pids)
        extra = sorted(seen_pids - expected_pids)
        report = (
            f"D/ST resolution failed: resolved {len(seen_pids)} unique player_ids, "
            f"expected exactly {_EXPECTED_DEF_COUNT}."
        )
        if missing:
            report += f"  Missing: {missing[:5]}..."
        if extra:
            report += f"  Extra: {extra[:5]}"
        raise RuntimeError(report)

    return resolutions


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # Build espn_id → player_id lookup from players table (NFL only, with espn_id)
    eid_to_pid = {}
    for r in con.execute(
        "SELECT id, espn_id FROM players WHERE league='nfl' AND espn_id IS NOT NULL AND espn_id != 0"
    ):
        eid_to_pid[str(r["espn_id"])] = r["id"]
    print(f"NFL players with espn_id: {len(eid_to_pid)}")

    # ── D/ST pre-flight: fetch proTeams map (fail-closed) ──
    pro_team_map = _build_pro_team_map()

    # ── Build team_abbrev → player_id lookup for active DEF players ──
    def_to_pid: dict[str, int] = {}
    for r in con.execute(
        "SELECT id, team FROM players WHERE league='nfl' AND position='DEF' AND active=1"
    ):
        def_to_pid[r["team"]] = r["id"]
    print(f"DEF players by team: {len(def_to_pid)}")

    # Create table
    con.execute(
        """CREATE TABLE IF NOT EXISTS nfl_adp (
            player_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            espn_player_id INTEGER NOT NULL,
            adp REAL,
            percent_owned REAL,
            percent_started REAL,
            espn_ppr_rank INTEGER,
            espn_standard_rank INTEGER,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (player_id, season)
        )"""
    )
    con.commit()

    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    total_fetched = 0
    total_matched = 0
    total_unmatched = 0
    non_null_adp = 0
    unmatched_samples = []
    offset = 0
    page_num = 1
    seen_espn_ids = set()
    all_entities: list = []  # accumulate for D/ST pass

    while True:
        print(f"  Fetching page {page_num} (offset {offset})...")
        page = _fetch_page(offset)
        if not page:
            break
        total_fetched += len(page)

        page_ids = {str(p.get("id", "")) for p in page}
        if page_ids and page_ids <= seen_espn_ids:
            print("    no new espn ids vs previous page(s) — pagination isn't advancing, stopping")
            break
        seen_espn_ids |= page_ids

        for p in page:
            eid = str(p.get("id", ""))
            pid = eid_to_pid.get(eid)
            if pid is None:
                total_unmatched += 1
                if len(unmatched_samples) < 5:
                    unmatched_samples.append(f"{p.get('fullName','?')} (espn_id={eid})")
                continue

            ownership = p.get("ownership", {}) or {}
            adp = ownership.get("averageDraftPosition")
            pct_owned = ownership.get("percentOwned")
            pct_started = ownership.get("percentStarted")

            ranks = p.get("draftRanksByRankType", {}) or {}
            ppr = ranks.get("PPR", {}) or {}
            std = ranks.get("STANDARD", {}) or {}
            ppr_rank = ppr.get("rank")
            std_rank = std.get("rank")

            if adp is not None:
                non_null_adp += 1

            con.execute(
                """INSERT OR REPLACE INTO nfl_adp
                   (player_id, season, espn_player_id, adp, percent_owned,
                    percent_started, espn_ppr_rank, espn_standard_rank, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (pid, SEASON, int(eid), adp, pct_owned, pct_started,
                 ppr_rank, std_rank, now),
            )
            total_matched += 1

        all_entities.extend(page)
        con.commit()
        print(f"    page {page_num}: {len(page)} fetched, {total_matched} matched so far")

        if len(page) < 3000:
            break
        offset += 3000
        page_num += 1

    # ── D/ST pass: build resolution plan, validate, THEN write ──
    dst_resolutions = _build_dst_resolutions(all_entities, pro_team_map, def_to_pid)
    print(f"D/ST resolution plan: {len(dst_resolutions)} of {_EXPECTED_DEF_COUNT}")

    for pid, espn_id, entity in dst_resolutions:
        # Backfill players.espn_id (NULL, zero, or empty-string)
        con.execute(
            "UPDATE players SET espn_id=? WHERE id=? AND (espn_id IS NULL OR espn_id = '' OR espn_id = 0)",
            (espn_id, pid),
        )

        ownership = entity.get("ownership", {}) or {}
        adp = ownership.get("averageDraftPosition")
        pct_owned = ownership.get("percentOwned")
        pct_started = ownership.get("percentStarted")

        ranks = entity.get("draftRanksByRankType", {}) or {}
        ppr = ranks.get("PPR", {}) or {}
        std = ranks.get("STANDARD", {}) or {}
        ppr_rank = ppr.get("rank")
        std_rank = std.get("rank")

        con.execute(
            """INSERT OR REPLACE INTO nfl_adp
               (player_id, season, espn_player_id, adp, percent_owned,
                percent_started, espn_ppr_rank, espn_standard_rank, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, SEASON, espn_id, adp, pct_owned, pct_started,
             ppr_rank, std_rank, now),
        )
        if adp is not None:
            non_null_adp += 1

    con.commit()
    dst_matched = len(dst_resolutions)
    print(f"D/ST committed: {dst_matched} of {_EXPECTED_DEF_COUNT}")

    # Verify
    row = con.execute(
        "SELECT COUNT(*) as n, COUNT(adp) as with_adp FROM nfl_adp WHERE season=?",
        (SEASON,),
    ).fetchone()
    print(f"\nIngested: {row['n']} rows ({row['with_adp']} with non-null ADP)")
    print(f"Matched (by espn_id): {total_matched}")
    print(f"Unmatched (no matching espn_id): {total_unmatched}")
    if unmatched_samples:
        print(f"  Sample unmatched: {unmatched_samples}")

    # Show top 10 by ADP
    top = con.execute(
        """SELECT na.adp, na.percent_owned, p.name, p.team, p.position
           FROM nfl_adp na JOIN players p ON p.id=na.player_id
           WHERE na.season=? AND na.adp IS NOT NULL
           ORDER BY na.adp ASC LIMIT 10""",
        (SEASON,),
    ).fetchall()
    print("\nTop 10 by ADP:")
    for t in top:
        print(f"  {t['adp']:7.1f}  {t['name']:25s} {t['position']:3s} {t['team']:4s}  owned {t['percent_owned']:.1f}%")

    con.close()


if __name__ == "__main__":
    main()
