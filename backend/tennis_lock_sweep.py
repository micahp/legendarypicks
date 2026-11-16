#!/usr/bin/env python3
"""Freeze tennis projections for matches entering their pre-match hour.

Lock creation used to happen only inside the projections API handler, so a match
was locked only if somebody loaded the page during its 60-minute window. A match
nobody opened was never locked, and an unlocked match can never be graded,
because grading reads the frozen pregame snapshot.

This sweep moves the freeze onto the ingest timer so it does not depend on a page
view. It reuses the same projection path the handler uses, so the frozen numbers
are identical; only the trigger changes.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sqlite3

import scoreboard_store
from tennis_count_distributions import build_history, match_distributions, store_distributions
from tennis_daily_projections import (
    needs_projection_refresh,
    project_day,
    store_candidates,
    stored_candidates,
)
from tennis_bovada_odds import bovada_odds

log = logging.getLogger(__name__)

LOCK_WINDOW = dt.timedelta(hours=1)
TENNIS_LEAGUES = ("atp", "wta")
DEV_DB_NAME = "picks.dev.db"


def _sackmann(con: sqlite3.Connection, league: str, espn_id: str) -> str | None:
    """Canonical Sackmann id for an ESPN athlete, or None when the spine does not know it."""
    if not espn_id:
        return None
    row = con.execute("SELECT id FROM players WHERE league=? AND espn_id=?",
                      (league, espn_id)).fetchone()
    if row is None:
        return None
    mapped = con.execute("SELECT source_player_key FROM player_source_ids "
                         "WHERE source='sackmann' AND league=? AND player_id=?",
                         (league, row["id"])).fetchone()
    return str(mapped[0]) if mapped else None


def due_matches(con: sqlite3.Connection, now: dt.datetime,
                window: dt.timedelta = LOCK_WINDOW) -> dict[tuple[str, str], list[dict]]:
    """Scheduled tennis matches starting within `window`, grouped by (league, model_day)."""
    start = now.astimezone(dt.timezone.utc).isoformat()
    end = (now.astimezone(dt.timezone.utc) + window).isoformat()
    grouped: dict[tuple[str, str], list[dict]] = {}
    rows = con.execute(
        "SELECT league, game_id, start_time, payload FROM scoreboard_snapshots "
        "WHERE league IN (?,?) AND state='pre' AND start_time > ? AND start_time <= ? "
        "ORDER BY start_time, game_id",
        (*TENNIS_LEAGUES, start, end),
    ).fetchall()
    for row in rows:
        league = str(row["league"])
        game = json.loads(row["payload"]) if row["payload"] else {}
        home, away = game.get("home") or {}, game.get("away") or {}
        home_id = str(home.get("athlete_id") or "")
        away_id = str(away.get("athlete_id") or "")
        match = {
            "gameId": str(row["game_id"]), "tour": league,
            "event": game.get("event"), "round": game.get("round"),
            "tournamentId": str(game.get("tournament_id") or ""),
            "startTime": row["start_time"], "status": "scheduled",
            "home": home.get("name") or home.get("abbrev") or "Home",
            "away": away.get("name") or away.get("abbrev") or "Away",
            "homeAthleteId": home_id, "awayAthleteId": away_id,
            "identity": {
                "home": {"espn_id": home_id, "sackmann_player_id": _sackmann(con, league, home_id)},
                "away": {"espn_id": away_id, "sackmann_player_id": _sackmann(con, league, away_id)},
            },
        }
        model_day = str(row["start_time"])[:10]
        grouped.setdefault((league, model_day), []).append(match)
    return grouped


def _bovada_quote(con: sqlite3.Connection, match: dict, now: dt.datetime) -> dict | None:
    """Attach the latest matching pre-lock quote, using ESPN-linked player identities.

    The sweep must freeze the same quote as the API-driven lock path. Without this,
    automated locks save only projections, leaving every settled Record without odds.
    """
    players = {}
    for side in ("home", "away"):
        espn_id = str(match.get(side + "AthleteId") or "")
        row = con.execute(
            "SELECT id FROM players WHERE league=? AND espn_id=?",
            (match["tour"], espn_id),
        ).fetchone() if espn_id else None
        players[side] = row[0] if row else None
    return bovada_odds(
        con, match["gameId"], match["tour"], players["home"], players["away"], now,
    )


def _freeze_distributions(con: sqlite3.Connection, report: dict, histories: dict, league: str,
                          model_day: str, match: dict, locked_at: str) -> None:
    """Freeze the research distributions for a lock that was just created.

    Never raises: the lock already exists, so a failure here is counted and logged, not propagated.
    """
    try:
        if (league, model_day) not in histories:
            histories[(league, model_day)] = build_history(con, league, model_day)
        rows, skipped = match_distributions(histories[(league, model_day)], league, model_day, match)
        if skipped:
            reasons = report["distribution_skip_reasons"]
            reasons[skipped] = reasons.get(skipped, 0) + 1
            report["distribution_skipped"] += 1
            return
        store_distributions(con, league, match["gameId"], locked_at, rows)
        report["distribution_frozen"] += 1
    except Exception as exc:
        report["distribution_failed"] += 1
        log.error("tennis distributions not frozen for %s %s: %r", league, match.get("gameId"), exc)


def new_report() -> dict:
    return {"considered": 0, "locked": 0, "already_locked": 0, "no_projection": 0,
            "quotes_frozen": 0, "quotes_unavailable": 0,
            "distribution_frozen": 0, "distribution_skipped": 0, "distribution_failed": 0,
            "distribution_gated": 0, "distribution_skip_reasons": {}}


def prepare_distributions(con: sqlite3.Connection) -> bool:
    """True when this connection may write research distributions. Creates their table when it may.

    Dev only. The scoreboards timer runs this same code against picks.dev.db and then picks.db,
    so prod gets no distribution table and no rows until Micah approves a prod write.
    """
    main_file = con.execute("PRAGMA database_list").fetchone()[2]
    if os.path.basename(main_file or "") != DEV_DB_NAME:
        return False
    scoreboard_store.ensure_distribution_schema(con)
    return True


def freeze_new_lock(con, report, histories, enabled, league, model_day, match, locked_at) -> None:
    """Freeze distributions for a lock that was just created. Outside dev, count it as gated instead."""
    if not enabled:
        report["distribution_gated"] += 1
        return
    _freeze_distributions(con, report, histories, league, model_day, match, locked_at)


def sweep(con: sqlite3.Connection, now: dt.datetime | None = None,
          window: dt.timedelta = LOCK_WINDOW) -> dict:
    """Lock every tennis match now inside its window. Safe to call every minute."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    report = new_report()
    histories: dict = {}
    distributions = prepare_distributions(con)
    for (league, model_day), matches in due_matches(con, now, window).items():
        stored = stored_candidates(con, league, model_day)
        if stored is None or needs_projection_refresh(stored, matches):
            stored = project_day(con, league, model_day, matches)
            store_candidates(con, league, model_day, stored, now.isoformat())
        for match in matches:
            report["considered"] += 1
            candidate = stored.get(match["gameId"])
            if candidate is None:
                # The match is not projectable (missing player identity or history).
                # Never fabricate a lock from a projection that does not exist.
                report["no_projection"] += 1
                continue
            # Never change an existing lock or attach a later quote to it.
            if con.execute(
                "SELECT 1 FROM tennis_model_locks WHERE league=? AND game_id=?",
                (league, match["gameId"]),
            ).fetchone():
                report["already_locked"] += 1
                continue
            locked_projection = dict(candidate)
            frozen_odds = _bovada_quote(con, match, now)
            # Store the attempted capture even if no matching, fresh odds exist.
            # Legacy locks lack this key and must not be represented as attempted.
            locked_projection["_frozenOdds"] = frozen_odds
            cursor = con.execute(
                "INSERT OR IGNORE INTO tennis_model_locks"
                "(league,game_date,game_id,start_time,locked_at,projection,model_version) "
                "VALUES(?,?,?,?,?,?,?)",
                (league, model_day, match["gameId"], match["startTime"], now.isoformat(),
                 json.dumps(locked_projection), candidate.get("modelVersion")),
            )
            if cursor.rowcount:
                report["locked"] += 1
                report["quotes_frozen" if frozen_odds is not None else "quotes_unavailable"] += 1
                freeze_new_lock(con, report, histories, distributions, league, model_day, match, now.isoformat())
            else:
                report["already_locked"] += 1
    con.commit()
    return report


def main() -> None:
    import os
    db = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    print(sweep(con))


if __name__ == "__main__":
    main()
