from __future__ import annotations

"""NFL mock draft — pool endpoint + draft CRUD for single-player mock drafts vs. ADP bots.

SPEC-slice-D-mock-draft.md:
  - Pool: GET /api/nfl/mock-draft/pool?season=2026 — ~300 ranked players (QB/RB/WR/TE/PK).
  - Draft CRUD: create, append picks, resume, list — keyed by X-Device-Id.
  - Own _DB from LP_DB_PATH (no _core.py dependency).
"""

import json
import os
import sqlite3
import time
import uuid
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
#  Module-level DB path — mirrors ufc_picks.py / nfl_draft_notes.py
# ---------------------------------------------------------------------------

_DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "picks.db"
)

_CONTRACT = "nfl-mock-draft-v1"
_CURRENT_SEASON = 2026
_ADP_SENTINEL = 169.0
_REG_SEASON_TEAM_GAMES = 17
_POSTSEASON_FIRST_WEEK = 19
_THIN_SAMPLE_GAMES = 4
_POOL_CAP = 300

# Draftable positions: skill positions, kickers, and team defenses.
_DRAFT_POSITIONS = ("QB", "RB", "WR", "TE", "PK", "DEF")


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _conn():
    connection = sqlite3.connect(_DB)
    connection.row_factory = sqlite3.Row
    return connection


def _init_db():
    """Create the mock-draft tables defensively.

    A table-init failure must not prevent the sports API from starting
    (same pattern as ``ufc_picks.py``).
    """
    try:
        connection = _conn()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS nfl_mock_drafts (
                    id          TEXT PRIMARY KEY,
                    device_id   TEXT    NOT NULL,
                    user_id     INTEGER,
                    season      INTEGER NOT NULL,
                    seat        INTEGER NOT NULL,
                    teams       INTEGER NOT NULL DEFAULT 12,
                    rounds      INTEGER NOT NULL DEFAULT 15,
                    seed        INTEGER NOT NULL,
                    status      TEXT    NOT NULL,
                    created_at  INTEGER NOT NULL,
                    updated_at  INTEGER NOT NULL,
                    completed_at INTEGER
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS nfl_mock_draft_picks (
                    draft_id   TEXT    NOT NULL,
                    pick_no    INTEGER NOT NULL,
                    team_no    INTEGER NOT NULL,
                    player_id  INTEGER NOT NULL,
                    auto       INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (draft_id, pick_no)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_mock_drafts_device "
                "ON nfl_mock_drafts(device_id, season)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_mock_draft_picks_draft "
                "ON nfl_mock_draft_picks(draft_id)"
            )
            connection.commit()
        finally:
            connection.close()
    except Exception:
        # A table-init failure must not prevent the sports API from starting.
        pass


_init_db()

router = APIRouter()


def _json(payload, status: int = 200) -> JSONResponse:
    return JSONResponse(content=payload, status_code=status)


def _device_id(x_device_id: Optional[str]) -> Optional[str]:
    """Copy of ``ufc_picks.py:84`` — trim, empty means None."""
    if not x_device_id:
        return None
    device_id = x_device_id.strip()
    return device_id or None


def _compute_round_and_pick(pick_count: int, teams: int) -> tuple[int, int]:
    """Given total picks made and number of teams, return (current_round, current_pick).

    Round is 1-indexed, pick is 1-indexed within the round (snake draft).
    If 0 picks have been made, returns (1, 1).
    If all picks are made, returns (rounds, teams) — the draft is complete.
    """
    if pick_count == 0:
        return 1, 1
    # Round number: which round does the NEXT pick belong to?
    current_round = (pick_count // teams) + 1
    # Pick within round: remainder gives position
    remainder = pick_count % teams
    if remainder == 0:
        # Just finished a round — next pick is first of next round
        current_pick = teams
    else:
        current_pick = remainder
    return current_round, current_pick


# ---------------------------------------------------------------------------
#  Pool endpoint  (§0 and §1 of SPEC-slice-D-mock-draft.md)
# ---------------------------------------------------------------------------


@router.get("/api/nfl/mock-draft/pool")
def pool(season: int = Query(...)):
    """Return the ~300-player ranked pool for mock drafts.

    X-Device-Id is NOT required for this endpoint — it is read-only public data.
    """
    if season != _CURRENT_SEASON:
        return _json({"error": f"season must be {_CURRENT_SEASON}"}, status=400)

    connection = _conn()
    try:
        # ------------------------------------------------------------------
        # Availability aggregates — read from the most recent completed
        # season (what the player actually did), not from the draft season
        # (which hasn't been played yet).
        # ------------------------------------------------------------------
        _log_season_row = connection.execute(
            "SELECT MAX(season) FROM player_game_logs WHERE league='nfl'"
        ).fetchone()
        _log_season = (_log_season_row[0] if _log_season_row and _log_season_row[0]
                       else _CURRENT_SEASON - 1)

        # Per-player aggregates: games_played, weeks_played, and primary_team
        # (the team he logged the most games for that season — handles mid-season
        # trades and team-code mismatches between the players table and the logs,
        # exactly as nfl_offseason.py:571-605 does).  Ties are broken by
        # preferring the team with the highest logged week (the one he finished on).
        agg_rows = connection.execute(
            """SELECT player_id, COUNT(*) AS games_played,
                      GROUP_CONCAT(CAST(game_no AS INTEGER)) AS weeks_csv,
                      team
               FROM player_game_logs
               WHERE league='nfl' AND season=? AND player_id IS NOT NULL
                 AND CAST(game_no AS INTEGER) < ?
               GROUP BY player_id, team""",
            (_log_season, _POSTSEASON_FIRST_WEEK),
        ).fetchall()

        _per_player: dict[int, dict] = {}
        for row in agg_rows:
            pid = row["player_id"]
            team = row["team"]
            games = row["games_played"]
            weeks = [int(w) for w in (row["weeks_csv"] or "").split(",") if w]
            if pid not in _per_player:
                _per_player[pid] = {
                    "games_played": 0, "weeks": set(),
                    "team_counts": {}, "team_max_week": {},
                }
            rec = _per_player[pid]
            rec["games_played"] += games
            rec["weeks"].update(weeks)
            rec["team_counts"][team] = rec["team_counts"].get(team, 0) + games
            max_w = max(weeks) if weeks else 0
            rec["team_max_week"][team] = max(rec["team_max_week"].get(team, 0), max_w)

        aggregates: dict[int, int] = {}
        weeks_played_map: dict[int, list[int]] = {}
        primary_team_map: dict[int, str] = {}
        for pid, rec in _per_player.items():
            aggregates[pid] = rec["games_played"]
            weeks_played_map[pid] = sorted(rec["weeks"])
            # Primary team = most games; ties go to the later-week team.
            primary_team_map[pid] = max(
                rec["team_counts"],
                key=lambda t: (rec["team_counts"][t], rec["team_max_week"].get(t, 0)),
            )

        # ------------------------------------------------------------------
        # Team weeks — which weeks each team actually played (bye-aware).
        # Keyed by log-season team abbreviation, NOT by players.team, because
        # those differ (LAR/LA, WSH/WAS, AZ/ARI).
        # ------------------------------------------------------------------
        _team_weeks_raw: dict[str, set[int]] = defaultdict(set)
        for tw_row in connection.execute(
            """SELECT team, CAST(game_no AS INTEGER) AS week
               FROM player_game_logs
               WHERE league='nfl' AND season=? AND team IS NOT NULL
                 AND CAST(game_no AS INTEGER) < ?
               GROUP BY team, game_no""",
            (_log_season, _POSTSEASON_FIRST_WEEK),
        ):
            try:
                _team_weeks_raw[tw_row["team"]].add(tw_row["week"])
            except (TypeError, ValueError):
                continue
        team_weeks_map: dict[str, list[int]] = {
            team: sorted(weeks) for team, weeks in _team_weeks_raw.items()
        }

        # ------------------------------------------------------------------
        # Query the pool: draftable positions, active players, from nfl_adp.
        # D/ST are selected separately (all 32) to guarantee they are never
        # displaced by the global 300-cap; non-DEF fill the remaining slots.
        # Both sets are then merged and sorted by the same ADP/ownership
        # ordering — no synthetic ADP, no fixed slot, no dst_rank.
        # ------------------------------------------------------------------
        _NON_DEF_POSITIONS = ("QB", "RB", "WR", "TE", "PK")
        _placeholders = ",".join("?" for _ in _NON_DEF_POSITIONS)

        # ── DEF: all 32, guaranteed a slot ──
        def_rows = connection.execute(
            """SELECT p.id AS player_id, p.name, p.position, p.team,
                      na.adp, na.percent_owned
               FROM players p
               JOIN nfl_adp na ON na.player_id = p.id AND na.season = ?
               WHERE p.league = 'nfl' AND p.active = 1
                 AND p.position = 'DEF'
                 AND (na.adp < ? OR na.percent_owned > 0)""",
            (season, _ADP_SENTINEL),
        ).fetchall()

        # ── Non-DEF: top N to fill pool cap ──
        _non_def_cap = _POOL_CAP - len(def_rows)
        non_def_rows: list = []
        if _non_def_cap > 0:
            non_def_rows = connection.execute(
                f"""SELECT p.id AS player_id, p.name, p.position, p.team,
                           na.adp, na.percent_owned
                    FROM players p
                    JOIN nfl_adp na ON na.player_id = p.id AND na.season = ?
                    WHERE p.league = 'nfl' AND p.active = 1
                      AND p.position IN ({_placeholders})
                      AND (na.adp < ? OR na.percent_owned > 0)
                    ORDER BY
                      CASE WHEN na.adp < ? THEN 0 ELSE 1 END,
                      CASE WHEN na.adp < ? THEN na.adp ELSE 999999.0 END ASC,
                      na.percent_owned DESC,
                      p.name ASC
                    LIMIT ?""",
                (season, *_NON_DEF_POSITIONS,
                 _ADP_SENTINEL, _ADP_SENTINEL, _ADP_SENTINEL, _non_def_cap),
            ).fetchall()

        # Merge both sets
        rows = list(def_rows) + list(non_def_rows)
        # Sort by same ordering: tier (adp<169 first), then adp ASC within tier 0,
        # then percent_owned DESC, then name ASC
        rows.sort(key=lambda r: (
            0 if (r["adp"] or 999999) < _ADP_SENTINEL else 1,
            (r["adp"] or 999999) if (r["adp"] or 999999) < _ADP_SENTINEL else 999999,
            -(r["percent_owned"] or 0),
            r["name"],
        ))

        # ── D/ST availability from nfl_dst_stats ──
        dst_avail: dict[int, dict] = {}
        try:
            for dr in connection.execute(
                """SELECT p.id AS player_id, p.team,
                          GROUP_CONCAT(d.week) AS weeks_csv
                   FROM players p
                   JOIN nfl_dst_stats d ON d.player_id = p.id
                   WHERE p.league = 'nfl' AND p.active = 1
                     AND p.position = 'DEF' AND d.season = ?
                   GROUP BY p.id""",
                (_log_season,),
            ):
                pid = dr["player_id"]
                weeks = [int(w) for w in (dr["weeks_csv"] or "").split(",") if w]
                gp = len(weeks)
                tw = team_weeks_map.get(dr["team"], [])
                tg = len(tw) if tw else _REG_SEASON_TEAM_GAMES
                dst_avail[pid] = {
                    "games_played": gp,
                    "games_missed": max(0, tg - gp) if gp > 0 else None,
                    "weeks_played": weeks,
                    "team_weeks": tw,
                }
        except sqlite3.OperationalError:
            pass

        players = []
        for row in rows:
            pid = row["player_id"]
            pos = row["position"]

            if pos == "DEF":
                avail = dst_avail.get(pid, {})
                gp = avail.get("games_played", 0)
                gm = avail.get("games_missed")
                wp = avail.get("weeks_played", [])
                tw = avail.get("team_weeks", [])
                if gp >= _THIN_SAMPLE_GAMES:
                    sample = "full"
                elif gp > 0:
                    sample = "thin"
                else:
                    sample = "none"
            else:
                gp = aggregates.get(pid, 0)
                if pid not in aggregates:
                    sample = "none"
                    gm = None
                elif gp < _THIN_SAMPLE_GAMES:
                    sample = "thin"
                    gm = _REG_SEASON_TEAM_GAMES - gp
                else:
                    sample = "full"
                    gm = _REG_SEASON_TEAM_GAMES - gp
                wp = weeks_played_map.get(pid, [])
                tw = team_weeks_map.get(primary_team_map.get(pid, ""), [])

            players.append({
                "player_id": pid,
                "name": row["name"],
                "position": pos,
                "team": row["team"],
                "adp": row["adp"],
                "percent_owned": row["percent_owned"],
                "sample": sample,
                "games_played": gp,
                "games_missed": gm,
                "weeks_played": wp,
                "team_weeks": tw,
            })

        return _json(
            {
                "contract": _CONTRACT,
                "season": season,
                "count": len(players),
                "players": players,
            }
        )
    finally:
        connection.close()


# ---------------------------------------------------------------------------
#  Draft CRUD
# ---------------------------------------------------------------------------


@router.post("/api/nfl/mock-draft")
async def create_draft(request: Request, x_device_id: Optional[str] = Header(None)):
    """Create a new mock draft.  Returns the draft id.

    Body: {season, seat, seed}.  X-Device-Id required.
    """
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "X-Device-Id header required"}, status=400)

    try:
        data = await request.json()
    except Exception:
        return _json({"error": "invalid JSON body"}, status=400)
    if not isinstance(data, dict):
        return _json({"error": "body must be a JSON object"}, status=400)

    season = data.get("season")
    seat = data.get("seat")
    seed = data.get("seed")

    if not isinstance(season, int) or season != _CURRENT_SEASON:
        return _json({"error": f"season must be {_CURRENT_SEASON}"}, status=400)
    if not isinstance(seat, int) or seat < 1 or seat > 12:
        return _json({"error": "seat must be 1..12"}, status=400)
    if not isinstance(seed, int):
        return _json({"error": "seed must be an integer"}, status=400)

    now = int(time.time() * 1000)
    draft_id = str(uuid.uuid4())

    connection = _conn()
    try:
        connection.execute(
            """INSERT INTO nfl_mock_drafts
               (id, device_id, season, seat, teams, rounds, seed, status,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, 12, 15, ?, 'active', ?, ?)""",
            (draft_id, device_id, season, seat, seed, now, now),
        )
        connection.commit()
    finally:
        connection.close()

    return _json({"id": draft_id})


@router.post("/api/nfl/mock-draft/{draft_id}/picks")
async def append_picks(
    draft_id: str, request: Request, x_device_id: Optional[str] = Header(None)
):
    """Append picks to a draft.  Idempotent on (draft_id, pick_no).

    Body: {picks: [{pick_no, team_no, player_id, auto?}, ...]}.
    X-Device-Id must match the draft's device_id, else 404.
    """
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "X-Device-Id header required"}, status=400)

    try:
        data = await request.json()
    except Exception:
        return _json({"error": "invalid JSON body"}, status=400)
    if not isinstance(data, dict):
        return _json({"error": "body must be a JSON object"}, status=400)

    picks = data.get("picks")
    if not isinstance(picks, list) or not picks:
        return _json({"error": "picks must be a non-empty array"}, status=400)

    now = int(time.time() * 1000)

    connection = _conn()
    try:
        draft = connection.execute(
            "SELECT device_id, status FROM nfl_mock_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()

        if draft is None:
            return _json({"error": "not found"}, status=404)
        if draft["device_id"] != device_id:
            return _json({"error": "not found"}, status=404)
        if draft["status"] != "active":
            return _json({"error": "draft is not active"}, status=409)

        inserted = 0
        for pick in picks:
            if not isinstance(pick, dict):
                continue
            pick_no = pick.get("pick_no")
            team_no = pick.get("team_no")
            player_id = pick.get("player_id")
            auto = int(pick.get("auto", 0) or 0)

            if not isinstance(pick_no, int) or pick_no < 1 or pick_no > 180:
                continue
            if not isinstance(team_no, int) or team_no < 1 or team_no > 12:
                continue
            if not isinstance(player_id, int):
                continue

            before = connection.total_changes
            connection.execute(
                """INSERT OR IGNORE INTO nfl_mock_draft_picks
                   (draft_id, pick_no, team_no, player_id, auto, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (draft_id, pick_no, team_no, player_id, auto, now),
            )
            if connection.total_changes > before:
                inserted += 1

        # Update the draft's updated_at timestamp.
        connection.execute(
            "UPDATE nfl_mock_drafts SET updated_at = ? WHERE id = ?",
            (now, draft_id),
        )
        connection.commit()
    finally:
        connection.close()

    return _json({"inserted": inserted})


@router.get("/api/nfl/mock-draft/{draft_id}")
def get_draft(draft_id: str, x_device_id: Optional[str] = Header(None)):
    """Resume a draft — returns draft metadata + all picks + computed round/pick.

    X-Device-Id must match the draft's device_id, else 404
    (same reasoning as picks: a device should not be able to probe draft ids).
    """
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "X-Device-Id header required"}, status=400)

    connection = _conn()
    try:
        draft = connection.execute(
            "SELECT * FROM nfl_mock_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()

        if draft is None:
            return _json({"error": "not found"}, status=404)
        if draft["device_id"] != device_id:
            return _json({"error": "not found"}, status=404)

        picks_rows = connection.execute(
            "SELECT * FROM nfl_mock_draft_picks WHERE draft_id = ? ORDER BY pick_no",
            (draft_id,),
        ).fetchall()

        picks = [
            {
                "pick_no": row["pick_no"],
                "team_no": row["team_no"],
                "player_id": row["player_id"],
                "auto": bool(row["auto"]),
                "created_at": row["created_at"],
            }
            for row in picks_rows
        ]

        # Compute current round and current pick from the pick count.
        total_picks = len(picks)
        current_round, current_pick = _compute_round_and_pick(
            total_picks, draft["teams"]
        )

        return _json(
            {
                "id": draft["id"],
                "season": draft["season"],
                "seat": draft["seat"],
                "teams": draft["teams"],
                "rounds": draft["rounds"],
                "seed": draft["seed"],
                "status": draft["status"],
                "created_at": draft["created_at"],
                "updated_at": draft["updated_at"],
                "completed_at": draft["completed_at"],
                "picks": picks,
                "total_picks": total_picks,
                "current_round": current_round,
                "current_pick": current_pick,
            }
        )
    finally:
        connection.close()


@router.get("/api/nfl/mock-drafts")
def list_drafts(x_device_id: Optional[str] = Header(None)):
    """List all mock drafts for this device (resume/history list).

    X-Device-Id required.
    """
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "X-Device-Id header required"}, status=400)

    connection = _conn()
    try:
        rows = connection.execute(
            """SELECT id, season, seat, teams, rounds, seed, status,
                      created_at, updated_at, completed_at
               FROM nfl_mock_drafts
               WHERE device_id = ?
               ORDER BY updated_at DESC""",
            (device_id,),
        ).fetchall()

        drafts = [
            {
                "id": row["id"],
                "season": row["season"],
                "seat": row["seat"],
                "teams": row["teams"],
                "rounds": row["rounds"],
                "seed": row["seed"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "completed_at": row["completed_at"],
            }
            for row in rows
        ]

        return _json({"drafts": drafts})
    finally:
        connection.close()


# ---------------------------------------------------------------------------
#  Player detail endpoint — per-player info + QB lookup
# ---------------------------------------------------------------------------


@router.get("/api/nfl/draft/player/{player_id}")
def player_detail(player_id: int):
    """Return player detail for the mock draft overlay.

    Includes: name, team, position, ADP, percent owned, season stats,
    game strip (weeks played vs team weeks), and for WR/RB/TE the QB on
    their team.
    """
    connection = _conn()
    try:
        # 1. Player lookup
        player = connection.execute(
            "SELECT id, name, team, position, active FROM players WHERE id=? AND league='nfl'",
            (player_id,),
        ).fetchone()

        if player is None:
            return _json({"error": "Player not found"}, status=404)

        name = player["name"]
        team = player["team"]
        position = player["position"]
        active = bool(player["active"])

        # 2. ADP / percent owned from nfl_adp
        adp = None
        percent_owned = None
        adp_row = connection.execute(
            "SELECT adp, percent_owned FROM nfl_adp WHERE player_id=? AND season=?",
            (player_id, _CURRENT_SEASON),
        ).fetchone()
        if adp_row:
            adp = adp_row["adp"]
            percent_owned = adp_row["percent_owned"]

        # 3. Season stats from player_game_logs
        _log_season_row = connection.execute(
            "SELECT MAX(season) FROM player_game_logs WHERE league='nfl'"
        ).fetchone()
        _log_season = (_log_season_row[0] if _log_season_row and _log_season_row[0]
                       else _CURRENT_SEASON - 1)

        log_rows = connection.execute(
            """SELECT game_no, stats, team
               FROM player_game_logs
               WHERE player_id=? AND league='nfl' AND season=?
                 AND CAST(game_no AS INTEGER) < ?
               ORDER BY CAST(game_no AS INTEGER)""",
            (player_id, _log_season, _POSTSEASON_FIRST_WEEK),
        ).fetchall()

        games_played = len(log_rows)
        weeks_played: list[int] = []
        ppr_total = 0.0
        snap_pct_sum = 0.0
        snap_pct_count = 0
        target_share_sum = 0.0
        target_share_count = 0
        xfp_sum = 0.0
        xfp_count = 0

        for row in log_rows:
            try:
                week = int(row["game_no"])
                weeks_played.append(week)
            except (TypeError, ValueError):
                pass
            try:
                stats = json.loads(row["stats"])
                ppr = stats.get("fpts_ppr")
                if ppr is not None:
                    ppr_total += float(ppr)
                sp = stats.get("off_pct")
                if sp is not None:
                    snap_pct_sum += float(sp)
                    snap_pct_count += 1
                ts = stats.get("target_share")
                if ts is not None:
                    target_share_sum += float(ts)
                    target_share_count += 1
                xf = stats.get("xfpts_ppr")
                if xf is not None:
                    xfp_sum += float(xf)
                    xfp_count += 1
            except Exception:
                pass

        # 3b. Merge snap-count presence
        snap_columns = connection.execute("PRAGMA table_info(nfl_snap_counts)").fetchall()
        if snap_columns:
            for sr in connection.execute(
                """SELECT week FROM nfl_snap_counts
                   WHERE player_id=? AND season=? AND CAST(week AS INTEGER) < ?""",
                (player_id, _log_season, _POSTSEASON_FIRST_WEEK),
            ):
                try:
                    w = int(sr["week"])
                    if w not in weeks_played:
                        weeks_played.append(w)
                        games_played = max(games_played, len(weeks_played))
                except (TypeError, ValueError):
                    continue

        weeks_played.sort()

        # ── D/ST availability from nfl_dst_stats (B17 — player_game_logs has no DEF rows) ──
        if position == "DEF":
            dst_columns = connection.execute("PRAGMA table_info(nfl_dst_stats)").fetchall()
            if dst_columns:
                dst_row = connection.execute(
                    """SELECT GROUP_CONCAT(week) AS weeks_csv
                       FROM nfl_dst_stats
                       WHERE season=? AND player_id=?""",
                    (_log_season, player_id),
                ).fetchone()
                if dst_row and dst_row["weeks_csv"]:
                    def_weeks = [int(w) for w in (dst_row["weeks_csv"] or "").split(",") if w]
                    weeks_played = sorted(def_weeks)
                    games_played = len(weeks_played)

        # Sample classification
        if games_played == 0:
            sample = "none"
        elif games_played < _THIN_SAMPLE_GAMES:
            sample = "thin"
        else:
            sample = "full"

        # Team weeks from schedule
        team_weeks: list[int] = []
        sched_columns = connection.execute("PRAGMA table_info(nfl_schedule)").fetchall()
        if sched_columns and team:
            tw_set: set[int] = set()
            for tw_row in connection.execute(
                """SELECT week FROM nfl_schedule
                   WHERE season=? AND week < ? AND (home_team=? OR away_team=?)""",
                (_log_season, _POSTSEASON_FIRST_WEEK, team, team),
            ):
                try:
                    tw_set.add(int(tw_row["week"]))
                except (TypeError, ValueError):
                    continue
            team_weeks = sorted(tw_set)

        # PPR calculations
        ppr_per_game_played = round(ppr_total / games_played, 1) if ppr_total and games_played else None
        ppr_per_team_game = round(ppr_total / _REG_SEASON_TEAM_GAMES, 1) if ppr_total else None
        snap_pct = round(snap_pct_sum / snap_pct_count * 100, 0) if snap_pct_count else None
        target_share = round(target_share_sum / target_share_count * 100, 1) if target_share_count else None
        xfp_per_game = round(xfp_sum / xfp_count, 1) if xfp_count else None

        # 4. QB lookup — for WR/RB/TE, rank team QBs by games played, return top QB
        qb = None
        if position in ("WR", "RB", "TE") and team:
            qb_rows = connection.execute(
                """SELECT p.id, p.name, p.team
                   FROM players p
                   WHERE p.league='nfl' AND p.active=1
                     AND p.position='QB' AND p.team=?
                   ORDER BY p.id ASC""",
                (team,),
            ).fetchall()

            best_qb = None
            best_games = -1
            for qb_row in qb_rows:
                qb_agg = connection.execute(
                    """SELECT COUNT(*) AS g
                       FROM player_game_logs
                       WHERE player_id=? AND league='nfl' AND season=?
                         AND game_type='REG'""",
                    (qb_row["id"], _log_season),
                ).fetchone()
                games = qb_agg["g"] if qb_agg else 0
                if games > best_games:
                    best_games = games
                    best_qb = {
                        "player_id": qb_row["id"],
                        "name": qb_row["name"],
                        "team": qb_row["team"],
                        "games_played": games,
                    }

            if best_qb is not None and best_games > 0:
                qb = best_qb

        # 5. PK bucket computation — same formula as _pk_aggregates in nfl_offseason.py
        pk_pts_total = None
        pk_pts_per_game = None
        if position == "PK":
            pk_row = connection.execute(
                f"""SELECT
                        COUNT(*)                                   AS games_played,
                        SUM(
                          COALESCE(CAST(json_extract(stats,'$.fg_made_0_19') AS REAL),0) * 3 +
                          COALESCE(CAST(json_extract(stats,'$.fg_made_20_29') AS REAL),0) * 3 +
                          COALESCE(CAST(json_extract(stats,'$.fg_made_30_39') AS REAL),0) * 3 +
                          COALESCE(CAST(json_extract(stats,'$.fg_made_40_49') AS REAL),0) * 4 +
                          COALESCE(CAST(json_extract(stats,'$.fg_made_50_59') AS REAL),0) * 5 +
                          COALESCE(CAST(json_extract(stats,'$.fg_made_60_') AS REAL),0) * 5 +
                          COALESCE(CAST(json_extract(stats,'$.pat_made') AS REAL),0) * 1 -
                          COALESCE(CAST(json_extract(stats,'$.fg_missed') AS REAL),0) * 1
                        )                                            AS pk_pts_total
                 FROM player_game_logs
                 WHERE league='nfl' AND season=?
                   AND player_id=?
                   AND CAST(game_no AS INTEGER) < ?""",
                (_log_season, player_id, _POSTSEASON_FIRST_WEEK),
            ).fetchone()
            if pk_row and pk_row["pk_pts_total"] is not None:
                pk_pts_total = round(pk_row["pk_pts_total"], 1)
                gp = pk_row["games_played"] or 0
                pk_pts_per_game = round(pk_pts_total / gp, 1) if pk_pts_total and gp else None

        # 6. DST stats from nfl_dst_stats — same pattern as _dst_aggregates
        dst_pts_total = None
        dst_pts_per_game = None
        if position == "DEF":
            dst_columns = connection.execute("PRAGMA table_info(nfl_dst_stats)").fetchall()
            if dst_columns:
                dst_row = connection.execute(
                    """SELECT COUNT(*) AS games_played,
                              SUM(fantasy_pts) AS dst_total,
                              AVG(fantasy_pts) AS dst_avg
                       FROM nfl_dst_stats
                       WHERE season=? AND player_id=?""",
                    (_log_season, player_id),
                ).fetchone()
                if dst_row and dst_row["dst_total"] is not None:
                    dst_pts_total = round(dst_row["dst_total"], 1)
                    if dst_row["dst_avg"] is not None:
                        dst_pts_per_game = round(dst_row["dst_avg"], 1)

        # 7. games_missed — mirroring the draft board pattern
        team_games = len(team_weeks) if team_weeks else _REG_SEASON_TEAM_GAMES
        games_missed = max(0, team_games - games_played)

        # 8. PK/DEF null-override for skill-position fields
        if position in ("PK", "DEF"):
            ppr_per_game_played = None
            snap_pct = None
            target_share = None

        return _json({
            "player_id": player_id,
            "name": name,
            "team": team,
            "position": position,
            "active": active,
            "adp": adp,
            "percent_owned": percent_owned,
            "sample": sample,
            "games_played": games_played,
            "games_missed": games_missed,
            "team_games": team_games,
            "weeks_played": weeks_played,
            "team_weeks": team_weeks,
            "ppr_per_game_played": ppr_per_game_played,
            "ppr_per_team_game": ppr_per_team_game,
            "snap_pct": snap_pct,
            "target_share": target_share,
            "xfp_per_game": xfp_per_game,
            "pk_pts_total": pk_pts_total,
            "pk_pts_per_game": pk_pts_per_game,
            "dst_pts_total": dst_pts_total,
            "dst_pts_per_game": dst_pts_per_game,
            "qb": qb,
        })
    finally:
        connection.close()
