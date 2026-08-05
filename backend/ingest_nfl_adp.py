#!/usr/bin/env python3
from __future__ import annotations
"""
ingest_nfl_adp.py — fetch real ESPN fantasy ADP for the 2026 draft season.

Source: ESPN's public fantasy API (same unauthenticated family as roster_sync).
Join: players.espn_id = feed.id (already populated by roster_sync.py for NFL).
D/ST: ESPN keys them with negative ids (-16000 - proTeamId); resolved via the
  published proTeams map (abbrev → team), joined to players by team + position='DEF',
  with espn_id backfilled so the join becomes permanent. Fail-closed: the proTeams
  fetch must succeed and all 32 active DEF teams must resolve with a published PPR
  rank before any write; partial resolution aborts with exit 1.

v0.7.0 (T1+T2): fetches the FULL ESPN player universe in one call (limit 20000,
no ownership filter) — 11,515 players including free agents (percentOwned=0).
Stores every entity in nfl_adp (new adp_ppr column = published PPR rank, plus the
ESPN position label), inserting a players row for any ESPN entity not yet in the
players spine (resolve by espn_id, never a names-only dup). The stored position is
ESPN's FFL vocabulary (QB/RB/WR/TE/PK/P/DT/DE/LB/CB/S/HC/TQB/DEF), which is the
pool's contract — the players table keeps the roster vocabulary for the board.
Free agents keep NULL adp/ranks — honest absence, never a fabricated number.

Writes one row per (player_id, season) into nfl_adp — a refreshable snapshot: the
whole season is deleted and re-inserted in one transaction, so stale rows from a
previous universe cannot linger.

Usage: python3 ingest_nfl_adp.py
"""
import json
import os
import sqlite3
import urllib.request

URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/players"
       "?scoringPeriodId=0&view=kona_player_info")
PROTEAMS_URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026"
                "?view=proTeamSchedules_wl")
HEADERS = {
    "x-fantasy-filter": json.dumps({
        "players": {
            "limit": 20000,
        }
    }),
}
SEASON = 2026
_EXPECTED_DEF_COUNT = 32
# The full ESPN FFL universe measured 2026-07-31 was 11,515 entities. Below this
# floor the response is truncated (the API silently pages) and writing a partial
# snapshot would be worse than writing nothing — fail closed.
_MIN_UNIVERSE = 10000

# ESPN defaultPositionId → the vocabulary this repo stores (players.position).
# Positions ESPN publishes but this repo never drafted (P, DT, DE, LB, CB, S) are
# stored verbatim — the pool serves the full universe; the draft UI filters.
# -1/0/17/18 have no published position in this payload (unsigned free agents /
# edge cases) — NULL is the honest absence, not a fabricated label.
_ESPN_POSITION = {
    1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "PK",
    7: "P", 9: "DT", 10: "DE", 11: "LB", 12: "CB", 13: "S",
    14: "HC", 15: "TQB", 16: "DEF",
}

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)

# `players` holds humans and fantasy constructs side by side. ESPN never
# confuses them -- constructs exist only in the fantasy API and it signs their
# ids negative -- so record the category the publisher already drew, at the
# boundary, instead of leaving every reader to infer it from a position label.
# See migrate_player_entity_type.py for what inferring it cost.
_ENTITY_BY_POSITION = {"DEF": "team_defense", "TQB": "team_qb", "HC": "coach"}


def _entity_type(position, espn_id) -> str:
    try:
        negative = espn_id is not None and int(espn_id) < 0
    except (TypeError, ValueError):
        negative = False
    if not negative:
        return "player"
    return _ENTITY_BY_POSITION.get((position or "").strip().upper(), "unknown")


def _fetch_all() -> list:
    """Fetch the full player universe in one call (limit 20000, no ownership filter)."""
    req = urllib.request.Request(URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read().decode("utf-8")
    data = json.loads(body)
    if len(data) < _MIN_UNIVERSE:
        raise RuntimeError(
            f"player feed returned {len(data)} entities (< {_MIN_UNIVERSE}): "
            f"response looks truncated — aborting, nothing written"
        )
    return data


def _build_pro_team_map() -> dict[int, str]:
    """Fetch the published proTeams endpoint.  Fails closed — raises on error."""
    with urllib.request.urlopen(PROTEAMS_URL, timeout=120) as r:
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
    eid_to_pid: dict[str, int],
    con: sqlite3.Connection,
    now: str,
) -> list[tuple[int, int, dict]]:
    """Resolve every D/ST entity to a players row.  Return [(player_id, espn_id, entity), ...].

    Resolution order: (1) players.espn_id == -16000 - proTeamId (already backfilled),
    (2) players.team == published abbrev AND position='DEF', (3) insert a new DEF
    players row keyed on the negative espn_id. Never a names-only duplicate.

    Must resolve exactly _EXPECTED_DEF_COUNT unique player_ids and every one must
    carry a published PPR rank (the adp_ppr gate), else raises. Nothing is written
    to nfl_adp here — pure resolution + player-spine backfill/insert.
    """
    seen_pids: set[int] = set()
    resolutions: list[tuple[int, int, dict]] = []
    unmatched: list[str] = []

    for entity in all_entities:
        if entity.get("defaultPositionId") != 16:
            continue
        pro_team_id = entity.get("proTeamId")
        if not pro_team_id:
            unmatched.append(
                f"{entity.get('fullName','?')} has no proTeamId"
            )
            continue
        espn_id = -16000 - pro_team_id
        abbrev = pro_team_map.get(pro_team_id)
        if not abbrev:
            unmatched.append(
                f"{entity.get('fullName','?')} proTeamId={pro_team_id} not in map"
            )
            continue
        pid = eid_to_pid.get(str(espn_id)) or def_to_pid.get(abbrev)
        if pid is None:
            # Not in the spine at all — resolve by inserting a DEF row keyed on
            # the negative espn_id (identity spine: insert with the source id,
            # never a names-only row, never a dup).
            cur = con.execute(
                """INSERT INTO players(name, league, team, position, espn_id, active, updated_at)
                   VALUES(?, 'nfl', ?, 'DEF', ?, 1, ?)""",
                (entity.get("fullName", f"{abbrev} D/ST"), abbrev, str(espn_id), now),
            )
            pid = int(cur.lastrowid)
            eid_to_pid[str(espn_id)] = pid
            def_to_pid[abbrev] = pid
            print(f"    D/ST inserted new players row: {abbrev} -> id {pid}")
        elif eid_to_pid.get(str(espn_id)) is None:
            # Player matched by team but has no espn_id — backfill the negative
            # id so the join is permanent (this is the job15 contract).
            con.execute(
                "UPDATE players SET espn_id=? WHERE id=? "
                "AND (espn_id IS NULL OR espn_id = '' OR espn_id = 0)",
                (str(espn_id), pid),
            )
            eid_to_pid[str(espn_id)] = pid
        if pid in seen_pids:
            continue  # duplicate D/ST entity

        ownership = entity.get("ownership", {}) or {}
        ranks = entity.get("draftRanksByRankType", {}) or {}
        ppr_rank = (ranks.get("PPR", {}) or {}).get("rank")
        # Fail-closed, both gates: published ADP AND published PPR rank must exist
        # for every D/ST. A null is missing data, not a value to derive.
        if ownership.get("averageDraftPosition") is None or ppr_rank is None:
            unmatched.append(
                f"{entity.get('fullName','?')} abbrev={abbrev} "
                f"adp={ownership.get('averageDraftPosition')} ppr_rank={ppr_rank}"
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


def _ensure_new_columns(con: sqlite3.Connection) -> None:
    """Add the v0.7.0 columns (adp_ppr, position) to a pre-v0.7.0 nfl_adp table."""
    columns = {r["name"] for r in con.execute("PRAGMA table_info(nfl_adp)")}
    if "adp_ppr" not in columns:
        con.execute("ALTER TABLE nfl_adp ADD COLUMN adp_ppr INTEGER")
    if "position" not in columns:
        con.execute("ALTER TABLE nfl_adp ADD COLUMN position TEXT")


def ingest():
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

    # ── Build team_abbrev → player_id lookup for team defences ──
    # Selected by `entity_type`, and deliberately WITHOUT `active=1`. A D/ST is
    # a fantasy construct, not a roster member, so `active` says nothing about
    # whether it should be published -- and reading it here is what broke this
    # ingest on 2026-08-04: `roster_sync` deactivated all 32, this map came
    # back empty, and the fail-closed D/ST preflight then aborted every run,
    # taking `injury_status` and `last_news_date` for 6,486 players with it.
    def_to_pid: dict[str, int] = {}
    _cols = {row[1] for row in con.execute("PRAGMA table_info(players)")}
    _def_where = ("entity_type='team_defense'" if "entity_type" in _cols
                  else "position='DEF'")
    for r in con.execute(
        f"SELECT id, team FROM players WHERE league='nfl' AND {_def_where}"
    ):
        def_to_pid[r["team"]] = r["id"]
    print(f"DEF players by team: {len(def_to_pid)}")

    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    # ── Fetch the full universe ──
    all_entities = _fetch_all()
    print(f"Fetched {len(all_entities)} entities (limit 20000, no ownership filter)")

    dst_ids = {p.get("id") for p in all_entities if p.get("defaultPositionId") == 16}
    print(f"D/ST entities in feed: {len(dst_ids)}")

    # ── Single transaction: resolve D/ST (fail-closed) → snapshot replace ──
    try:
        con.execute("BEGIN IMMEDIATE")
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
                adp_ppr INTEGER,
                position TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (player_id, season)
            )"""
        )
        _ensure_new_columns(con)

        # D/ST pass: resolve all 32 BEFORE any nfl_adp write (fail-closed). Its
        # spine inserts/backfills run in this same transaction — a failure rolls
        # back everything, including the spine changes.
        dst_resolutions = _build_dst_resolutions(
            all_entities, pro_team_map, def_to_pid, eid_to_pid, con, now
        )
        print(f"D/ST resolution plan: {len(dst_resolutions)} of {_EXPECTED_DEF_COUNT}")

        # ── Main pass: resolve/insert every non-D/ST entity and stage its row ──
        total_matched = 0
        inserted_players = 0
        rows: list[tuple] = []
        pos_counts: dict[str, int] = {}
        # Injury columns are optional (a concurrent feature's migration may not
        # have landed on this DB) — guard once, no-op on DBs without them.
        _has_injury_cols = {"injury_status", "last_news_date"} <= {
            r["name"] for r in con.execute("PRAGMA table_info(players)")
        }
        for p in all_entities:
            if p.get("defaultPositionId") == 16:
                continue  # owned by the D/ST pass
            eid = str(p.get("id", ""))
            pid = eid_to_pid.get(eid)
            if pid is None:
                # Resolve-or-INSERT, never DUP: the entity is in ESPN's published
                # universe but has no espn_id row in the spine. If a name-only row
                # already exists (a prop scraper created it without a source id),
                # COMPLETE it — backfill the espn_id rather than insert a second
                # row for the same human. players has UNIQUE(espn_id, league); a
                # later roster_sync backfill would otherwise collide on the next
                # run and roll back the whole snapshot. Only an exact name+team
                # match is merged; anything else is a fresh insert keyed on espn_id.
                name = p.get("fullName", "?")
                position = _ESPN_POSITION.get(p.get("defaultPositionId"))
                team = pro_team_map.get(p.get("proTeamId")) if p.get("proTeamId") else None
                name_only = None
                if team:
                    name_only = con.execute(
                        "SELECT id FROM players WHERE league='nfl' "
                        "AND espn_id IS NULL AND name=? AND team=? LIMIT 1",
                        (name, team),
                    ).fetchone()
                if name_only is not None:
                    pid = name_only["id"]
                    con.execute(
                        "UPDATE players SET espn_id=?, position=COALESCE(?, position), "
                        "active=?, updated_at=? WHERE id=?",
                        (eid, position, 1 if p.get("active") else 0, now, pid),
                    )
                else:
                    cur = con.execute(
                        """INSERT INTO players(name, league, team, position, espn_id,
                                               active, updated_at)
                           VALUES(?, 'nfl', ?, ?, ?, ?, ?)""",
                        (
                            name,
                            team,
                            position,
                            eid,
                            1 if p.get("active") else 0,
                            now,
                        ),
                    )
                    pid = int(cur.lastrowid)
                    inserted_players += 1
                eid_to_pid[eid] = pid
            total_matched += 1

            # ---- Injury data ingestion (published-first, honest nulls) ----
            # Runs only where the injury columns exist; absent columns must not
            # take the whole snapshot down with an OperationalError.
            injured = p.get("injured")
            injury_status = p.get("injuryStatus")
            last_news_date = p.get("lastNewsDate")
            if _has_injury_cols and (injured is not None or injury_status is not None
                                     or last_news_date is not None):
                con.execute(
                    "UPDATE players SET injury_status=?, last_news_date=?, updated_at=? WHERE id=?",
                    (
                        injury_status if injury_status else None,
                        str(last_news_date) if last_news_date is not None else None,
                        now,
                        pid,
                    ),
                )

            position = _ESPN_POSITION.get(p.get("defaultPositionId"))
            pos_counts[position] = pos_counts.get(position, 0) + 1

            ownership = p.get("ownership", {}) or {}
            ranks = p.get("draftRanksByRankType", {}) or {}
            ppr = ranks.get("PPR", {}) or {}
            std = ranks.get("STANDARD", {}) or {}
            rows.append((
                pid,
                SEASON,
                int(p.get("id")),
                ownership.get("averageDraftPosition"),
                ownership.get("percentOwned"),
                ownership.get("percentStarted"),
                ppr.get("rank"),
                std.get("rank"),
                ppr.get("rank"),  # adp_ppr — published PPR rank, same source
                position,
                now,
            ))

        # Refreshable snapshot: drop the season's stale rows, then insert the
        # current universe. Same transaction, so a failure rolls back to the
        # previous good snapshot.
        con.execute("DELETE FROM nfl_adp WHERE season = ?", (SEASON,))
        con.executemany(
            """INSERT OR REPLACE INTO nfl_adp
               (player_id, season, espn_player_id, adp, percent_owned,
                percent_started, espn_ppr_rank, espn_standard_rank, adp_ppr,
                position, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        for pid, espn_id, entity in dst_resolutions:
            ownership = entity.get("ownership", {}) or {}
            ranks = entity.get("draftRanksByRankType", {}) or {}
            ppr = ranks.get("PPR", {}) or {}
            std = ranks.get("STANDARD", {}) or {}
            con.execute(
                """INSERT OR REPLACE INTO nfl_adp
                   (player_id, season, espn_player_id, adp, percent_owned,
                    percent_started, espn_ppr_rank, espn_standard_rank, adp_ppr,
                    position, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    pid,
                    SEASON,
                    espn_id,
                    ownership.get("averageDraftPosition"),
                    ownership.get("percentOwned"),
                    ownership.get("percentStarted"),
                    ppr.get("rank"),
                    std.get("rank"),
                    ppr.get("rank"),
                    "DEF",
                    now,
                ),
            )
        con.execute("COMMIT")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        con.close()
        raise

    dst_matched = len(dst_resolutions)
    print(f"D/ST committed: {dst_matched} of {_EXPECTED_DEF_COUNT}")

    # Verify
    row = con.execute(
        "SELECT COUNT(*) as n, COUNT(adp) as with_adp, COUNT(adp_ppr) as with_ppr "
        "FROM nfl_adp WHERE season=?",
        (SEASON,),
    ).fetchone()
    print(f"\nIngested: {row['n']} rows ({row['with_adp']} with non-null ADP, "
          f"{row['with_ppr']} with non-null adp_ppr)")
    print(f"Matched (by espn_id or inserted): {total_matched}")
    print(f"Players inserted into spine: {inserted_players}")
    print(f"Unmatched (no players row): 0")
    print("Position breakdown (stored LP vocabulary):")
    for pos in sorted(pos_counts, key=lambda x: (x is None, x or "")):
        print(f"  {pos or 'NULL'}: {pos_counts[pos]}")

    # D/ST gate: 32/32 with adp_ppr populated
    dst_rows = con.execute(
        """SELECT p.team, na.adp, na.adp_ppr FROM nfl_adp na
           JOIN players p ON p.id = na.player_id
           WHERE na.season = ? AND p.position = 'DEF' AND na.adp_ppr IS NULL""",
        (SEASON,),
    ).fetchall()
    if dst_rows:
        teams = [r["team"] for r in dst_rows]
        raise RuntimeError(
            f"D/ST gate FAILED: {len(dst_rows)} DEF rows missing adp_ppr: {teams}"
        )
    print(f"D/ST gate: 32/32 with adp_ppr populated")

    # Show top 10 by ADP and the D/ST PPR ranks for the report
    top = con.execute(
        """SELECT na.adp, na.adp_ppr, na.percent_owned, p.name, p.team, p.position
           FROM nfl_adp na JOIN players p ON p.id=na.player_id
           WHERE na.season=? AND na.adp IS NOT NULL
           ORDER BY na.adp ASC LIMIT 10""",
        (SEASON,),
    ).fetchall()
    print("\nTop 10 by ADP:")
    for t in top:
        print(f"  {t['adp']:7.1f}  {t['name']:25s} {t['position']:3s} {t['team']:4s}  owned {t['percent_owned']:.1f}%")

    den = con.execute(
        """SELECT na.adp_ppr FROM nfl_adp na JOIN players p ON p.id=na.player_id
           WHERE na.season=? AND p.team='DEN' AND p.position='DEF'""",
        (SEASON,),
    ).fetchone()
    sea = con.execute(
        """SELECT na.adp_ppr FROM nfl_adp na JOIN players p ON p.id=na.player_id
           WHERE na.season=? AND p.team='SEA' AND p.position='DEF'""",
        (SEASON,),
    ).fetchone()
    print(f"\nD/ST published PPR ranks: DEN={den['adp_ppr'] if den else '?'} "
          f"SEA={sea['adp_ppr'] if sea else '?'}")

    con.close()


def main():
    ingest()


if __name__ == "__main__":
    main()
