"""routers/games/misc.py — root/health/coverage and the audio stream endpoint."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from _core import *
from provenance import publishers_for
from sport_navigation import league_directory_navigation, prop_navigation
import scoreboard_store
import league_readiness
from . import router
from .contexts import _LCUP_RADIO


def _db():
    """Resolve `routers.games._db` at call time (see scoreboard.py `_db`)."""
    from routers.games import _db as _pkg_db
    return _pkg_db()


def _winner_brier(probability, winner_grade):
    """Brier score for the locked winner confidence, or None without a valid result."""
    if winner_grade not in ("correct", "incorrect"):
        return None
    try:
        probability = float(probability)
    except (TypeError, ValueError):
        return None
    if not 0.0 <= probability <= 1.0:
        return None
    outcome = 1.0 if winner_grade == "correct" else 0.0
    return (probability - outcome) ** 2


def _tennis_lock_status(start_time, locked_at, projection, now):
    if locked_at:
        return "locked"
    if projection is not None:
        return "preview"
    if not start_time:
        return "unknown"
    try:
        starts_at = dt.datetime.fromisoformat(str(start_time).replace("Z", "+00:00"))
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return "unknown"
    return "missed" if starts_at.astimezone(dt.timezone.utc) <= now else "not_due"


def _tennis_v2_ledger_records(league: str, game_ids: list[str] | None) -> dict[str, dict]:
    """Read selected V2 forecasts, or all records when requested for model accuracy."""
    if game_ids is not None and not game_ids:
        return {}
    path = os.environ.get("LP_TENNIS_V2_LEDGER_PATH") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "tennis_v2_research.sqlite3",
    )
    if not os.path.isfile(path):
        return {}
    game_filter = ""
    params = [league]
    if game_ids is not None:
        placeholders = ",".join("?" for _ in game_ids)
        game_filter = " AND f.game_id IN ({})".format(placeholders)
        params.extend(game_ids)
    try:
        ledger = sqlite3.connect("file:{}?mode=ro".format(path), uri=True, timeout=5)
        ledger.row_factory = sqlite3.Row
        try:
            tables = {row[0] for row in ledger.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if "tennis_v2_research_forecasts" not in tables:
                return {}
            has_grades = "tennis_v2_research_grades" in tables
            grade_fields = (
                "g.actual_winner,g.actual_total_games" if has_grades
                else "NULL AS actual_winner,NULL AS actual_total_games"
            )
            grade_join = (
                "LEFT JOIN tennis_v2_research_grades g ON g.tour=f.tour AND g.game_id=f.game_id"
                if has_grades else ""
            )
            rows = ledger.execute(
                "SELECT f.game_id,f.locked_at,f.payload,f.payload_sha256,{} "
                "FROM tennis_v2_research_forecasts f {} "
                "WHERE f.tour=?{}".format(grade_fields, grade_join, game_filter),
                params,
            ).fetchall()
            records = {}
            for row in rows:
                payload_text = str(row["payload"])
                actual_sha256 = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
                if actual_sha256 != row["payload_sha256"]:
                    raise HTTPException(
                        status_code=503,
                        detail="Tennis V2 forecast ledger checksum mismatch for game %s" % row["game_id"],
                    )
                try:
                    payload = json.loads(payload_text)
                except (TypeError, ValueError) as exc:
                    raise HTTPException(
                        status_code=503,
                        detail="Tennis V2 forecast ledger contains invalid JSON for game %s" % row["game_id"],
                    ) from exc
                records[str(row["game_id"])] = {
                    "locked_at": row["locked_at"],
                    "payload": payload,
                    "actual_winner": row["actual_winner"],
                    "actual_total_games": row["actual_total_games"],
                }
            return records
        finally:
            ledger.close()
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail="Tennis V2 forecast ledger could not be read",
        ) from exc


def _tennis_page_winner_accuracy(con, league: str) -> list[float]:
    rows = con.execute(
        "SELECT l.projection,g.winner FROM tennis_model_locks l "
        "JOIN tennis_model_grades g ON g.league=l.league AND g.game_id=l.game_id "
        "WHERE l.league=?",
        (league,),
    ).fetchall()
    scores = []
    for row in rows:
        try:
            probability = json.loads(row["projection"]).get("probability")
        except (TypeError, ValueError):
            continue
        score = _winner_brier(probability, row["winner"])
        if score is not None:
            scores.append(score)
    return scores


def _tennis_v2_winner_accuracy(records: dict[str, dict]) -> list[float]:
    scores = []
    for record in records.values():
        forecast = record.get("payload") or {}
        actual_winner = record.get("actual_winner")
        if not actual_winner:
            continue
        probability = ((forecast.get("match_winner_home_probability") or {})
                       .get("elo_informed_v2"))
        try:
            probability = float(probability)
        except (TypeError, ValueError):
            continue
        if not 0.0 <= probability <= 1.0:
            continue
        predicted_winner = (forecast.get("home_player") if probability >= 0.5
                            else forecast.get("away_player"))
        grade = "correct" if actual_winner == predicted_winner else "incorrect"
        score = _winner_brier(max(probability, 1.0 - probability), grade)
        if score is not None:
            scores.append(score)
    return scores


def _apply_tennis_v2_winner(match: dict, record: dict | None) -> bool:
    """Replace only the winner forecast and its grade with the locked V2 record."""
    if not record:
        match["projection"] = None
        match["lockedAt"] = None
        match["preview"] = False
        match["grades"] = None
        return False

    forecast = record["payload"]
    forecast_ids = forecast.get("identity") or {}
    current_identity = match.get("identity") or {}
    home_id = (current_identity.get("home") or {}).get("sackmann_player_id")
    away_id = (current_identity.get("away") or {}).get("sackmann_player_id")
    forecast_home_id = forecast_ids.get("home_sackmann_id")
    forecast_away_id = forecast_ids.get("away_sackmann_id")
    probabilities = forecast.get("match_winner_home_probability") or {}
    probability = probabilities.get("elo_informed_v2")
    try:
        probability = float(probability)
    except (TypeError, ValueError):
        match["projection"] = None
        match["lockedAt"] = None
        match["preview"] = False
        match["grades"] = None
        return False
    if not 0.0 <= probability <= 1.0:
        match["projection"] = None
        match["lockedAt"] = None
        match["preview"] = False
        match["grades"] = None
        return False

    if (home_id, away_id) == (forecast_home_id, forecast_away_id):
        home_probability = probability
    elif (home_id, away_id) == (forecast_away_id, forecast_home_id):
        home_probability = 1.0 - probability
    else:
        match["projection"] = None
        match["lockedAt"] = None
        match["preview"] = False
        match["grades"] = None
        return False

    predicted_home = home_probability >= 0.5
    predicted_winner = match["home"] if predicted_home else match["away"]
    current_projection = match.get("projection") or {}
    match["projection"] = {
        **current_projection,
        "probability": max(home_probability, 1.0 - home_probability),
        "projectedWinner": predicted_winner,
        "modelVersion": forecast.get("model_version"),
    }
    match["lockedAt"] = record.get("locked_at")
    match["preview"] = False
    # V2 uses a separate prospective ledger that does not persist lock-time odds.
    # Never borrow the regular page model's quote for a different forecast lock.
    match["frozenOdds"] = None

    grades = match.get("grades") or {}
    actual_winner = record.get("actual_winner")
    v2_grade = None
    if actual_winner:
        predicted_source_name = forecast.get("home_player") if predicted_home else forecast.get("away_player")
        v2_grade = "correct" if actual_winner == predicted_source_name else "incorrect"
    match["grades"] = {**grades, "winner": v2_grade}
    return True


@router.get("/")
def root():
    return {"service": "Legendary Picks Sports API", "version": "2.0.0",
            "source": "ESPN", "leagues": sorted(espn.LEAGUES)}


# Both paths, and `/api/health` is the one that matters: the Next dev server
# proxies ONLY `/api/*`, so bare `/health` through a tunnel hits the frontend and
# returns its 404 page. A health endpoint you cannot reach from the URL you are
# actually looking at is not one you will ever use -- which is why this took a
# walk through /proc on 2026-08-17 instead of one curl.
@router.get("/api/health")
@router.get("/health")
def health():
    """Which database is this process actually serving, and how stale is it?

    `{"status": "ok"}` was the whole response, and "ok" was true of every server
    on this box at once -- prod, dev, and a worktree serving a throwaway snapshot
    in /tmp. On 2026-08-17 a dev tunnel showed "2 games, 104 props" and looked
    frozen; the cause was that its backend pointed at
    `/tmp/lp-mls-ncaaf-standings-runtime.VgZl9x/picks.db`, a copy taken at 11:16
    on Aug 15 so the worktree could not corrupt the real dev DB. Correct
    isolation, no visible signal: it answered 200 and looked like the app. Finding
    it meant walking /proc for the listening pid's LP_DB_PATH.

    A health check that cannot distinguish those three is not a health check, it
    is a liveness ping wearing the name. So say the two things that actually
    identify a deployment: WHICH file, and HOW FRESH.

    Deliberately cheap -- two MAX() lookups on indexed timestamp columns, because
    this gets polled. Failures degrade to null rather than 500ing: a health
    endpoint that raises when one table is missing tells you less than one that
    answers with the fields it could read.
    """
    info = {"status": "ok", "db_path": DB, "db_mtime": None,
            "newest_prop_captured": None, "newest_game_date": None}
    try:
        con = _db()
    except Exception as exc:
        info["status"] = "degraded"
        info["error"] = "%s: %s" % (type(exc).__name__, exc)
        return info
    try:
        info["db_mtime"] = dt.datetime.fromtimestamp(
            os.path.getmtime(DB), dt.timezone.utc).isoformat()
    except Exception:
        pass
    for key, sql in (("newest_prop_captured", "SELECT MAX(captured_at) FROM props"),
                     ("newest_game_date", "SELECT MAX(date) FROM prop_games")):
        try:
            info[key] = con.execute(sql).fetchone()[0]
        except Exception:
            pass
    return info


@router.get("/api/coverage")
def coverage():
    """The enablement registry: which (league, season) pairs may be offered at all.

    Returns EVERY row, not just the complete ones. A client needs to distinguish
    "this league exists and we cannot vouch for it yet" from "this league does not
    exist" — they are different states and they read differently to a user.

    A (league, season) with no row here is `unverified`, which is the default and is
    never good. See docs/DATA-COVERAGE-CONTRACT.md §4.

    Each row also carries `publishers`: the external sources whose rows actually
    back that league, measured from the data rather than declared. Note that the
    row's own `source` column describes the *verdict* ("reconcile_totals+
    espn_core_api"), not the data — conflating the two is how NHL came to hold
    ESPN-keyed team rows and nhle.com-keyed player rows with nothing saying so.
    More than one publisher is not an error; it is a count of vocabulary
    boundaries this league's joins have to cross.
    """
    with closing(_db()) as con:
        try:
            rows = con.execute(
                "SELECT league, season, status, expected_teams, fetched_teams,"
                " expected_games, fetched_games, paired_games, paired_stat_games,"
                " failure_count, season_start, season_end, completed_at, source,"
                " checked_through"
                " FROM team_stats_coverage ORDER BY league, season"
            ).fetchall()
        except sqlite3.Error:
            # No table is not an error; it means nothing has been verified.
            return []
        pubs = {}
        for r in rows:
            league = r["league"]
            if league not in pubs:
                try:
                    pubs[league] = publishers_for(con, league)
                except sqlite3.Error:
                    pubs[league] = []
    out = []
    for r in rows:
        d = dict(r)
        # Never let an unrecognised status read as permission. Anything outside the
        # three-value vocabulary is treated as unverified rather than passed through.
        # `in_progress` is a season that passes every check but has not ended yet;
        # its row carries `checked_through`, the date its claim actually reaches.
        # It belongs in this list and leaving it out is not a safe default — the
        # guard would rewrite a verified live season to "we cannot vouch for this"
        # and the fix would be invisible end to end.
        if d.get("status") not in ("complete", "in_progress", "partial", "unverified"):
            d["status"] = "unverified"
        d["publishers"] = pubs.get(d["league"], [])
        out.append(d)
    return out


@router.get("/api/readiness/leagues")
def readiness_leagues(as_of: str = None):
    """Current-season product readiness from persisted calendars and data.

    This is deliberately separate from `/api/health` (process liveness) and
    `/api/coverage` (the historical certification registry).  It performs no
    publisher requests.  `as_of` exists so season-boundary behavior can be
    inspected and tested without changing the server clock.
    """
    try:
        day = dt.date.fromisoformat(as_of) if as_of else dt.date.today()
    except ValueError:
        raise HTTPException(400, "as_of must be YYYY-MM-DD")
    with closing(_db()) as con:
        return league_readiness.build_readiness(con, day)


@router.get("/api/navigation/sports")
def sport_navigation():
    """DB-backed competition coverage with sport derived from publisher paths."""
    with closing(_db()) as con:
        return {
            "props": prop_navigation(con),
            "leagues": league_directory_navigation(con),
        }


@router.get("/api/tennis/draws")
def tennis_draws(tour: str = "all"):
    """Persisted major singles draws; this serving route never calls ESPN."""
    tour = str(tour or "all").lower()
    if tour not in ("all", "atp", "wta"):
        raise HTTPException(400, "tour must be all, atp, or wta")
    draws = scoreboard_store.read_tennis_draws(None if tour == "all" else tour)
    return {
        "available": bool(draws),
        "source": "tennis_draw_snapshots",
        "tours": draws,
        "reason": None if draws else "No verified major draw has been published yet.",
    }


@router.get("/api/tennis/rankings")
def tennis_rankings(tour: str = "all", limit: int = Query(50, ge=1, le=150)):
    """Latest persisted ATP/WTA top-150 snapshots; never calls ESPN."""
    tour = str(tour or "all").lower()
    if tour not in ("all", "atp", "wta"):
        raise HTTPException(400, "tour must be all, atp, or wta")
    snapshots = scoreboard_store.read_tennis_rankings(
        None if tour == "all" else tour,
        limit=limit,
    )
    return {
        "available": bool(snapshots),
        "source": "tennis_ranking_snapshots",
        "tours": snapshots,
        "reason": None if snapshots else "No verified ATP or WTA ranking snapshot has been published yet.",
    }


@router.get("/api/tennis/model")
def tennis_model(date: str, tour: str = "all", utc_offset_minutes: int = 0,
                 winner_model: str = "page"):
    """Read a local-day slate and resolve participants through the tennis spine.

    Future matches carry a preview; only forecasts frozen before start are eligible
    for a final grade.
    """
    tour = str(tour or "all").lower()
    if tour not in ("all", "atp", "wta"):
        raise HTTPException(400, "tour must be all, atp, or wta")
    winner_model = str(winner_model or "page").lower()
    if winner_model not in ("page", "elo_informed_v2"):
        raise HTTPException(400, "winner_model must be page or elo_informed_v2")
    try:
        selected_day = dt.date.fromisoformat(date)
    except (TypeError, ValueError):
        raise HTTPException(400, "date must be YYYY-MM-DD")
    if not -840 <= utc_offset_minutes <= 840:
        raise HTTPException(400, "utc_offset_minutes must be between -840 and 840")

    tours = ("atp", "wta") if tour == "all" else (tour,)
    local_midnight = dt.datetime.combine(selected_day, dt.time())
    utc_start = local_midnight + dt.timedelta(minutes=utc_offset_minutes)
    utc_end = utc_start + dt.timedelta(days=1)
    date_from = utc_start.date().isoformat()
    date_through = (utc_end - dt.timedelta(microseconds=1)).date().isoformat()
    out = []
    accuracy_scores = []
    with closing(_db()) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS tennis_model_locks("
            "league TEXT NOT NULL,game_date TEXT NOT NULL,game_id TEXT NOT NULL,start_time TEXT NOT NULL,"
            "locked_at TEXT NOT NULL,projection TEXT NOT NULL,model_version TEXT,PRIMARY KEY(league,game_id))"
        )
        from tennis_bovada_odds import bovada_odds
        from tennis_shadow import ensure_table as ensure_shadow_table, write_shadow_locks
        ensure_shadow_table(con)
        shadow_replays: dict = {}
        now_utc = dt.datetime.now(dt.timezone.utc)
        for league in tours:
            rows = con.execute(
                "SELECT game_id,payload,state,start_time FROM scoreboard_snapshots "
                "WHERE league=? AND game_date BETWEEN ? AND ? ORDER BY start_time,game_id",
                (league, date_from, date_through),
            ).fetchall()
            grades = {
                str(grade["game_id"]): dict(grade)
                for grade in con.execute(
                    "SELECT game_id,winner,total_games_error FROM tennis_model_grades WHERE league=?",
                    (league,),
                ).fetchall()
            }
            match_stats = {
                str(stat["game_id"]): dict(stat)
                for stat in con.execute(
                    "SELECT game_id,home_aces,away_aces,source_url FROM tennis_match_stats_overrides "
                    "WHERE league=? AND game_date BETWEEN ? AND ?",
                    (league, date_from, date_through),
                ).fetchall()
            }
            slate = []
            for row in rows:
                try:
                    game = json.loads(row["payload"])
                except (TypeError, ValueError):
                    continue
                home, away = game.get("home") or {}, game.get("away") or {}
                home_id = str(home.get("athlete_id") or "")
                away_id = str(away.get("athlete_id") or "")
                # ESPN athlete IDs resolve into canonical players.id. Historical
                # model identities are then reached only through player_source_ids.
                spine = {}
                ids = [value for value in (home_id, away_id) if value]
                if ids:
                    placeholders = ",".join("?" for _ in ids)
                    for player in con.execute(
                        f"SELECT id,espn_id,name FROM players WHERE league=? AND espn_id IN ({placeholders})",
                        (league, *ids),
                    ):
                        sackmann = con.execute(
                            "SELECT source_player_key FROM player_source_ids "
                            "WHERE source='sackmann' AND league=? AND player_id=?",
                            (league, player["id"]),
                        ).fetchone()
                        spine[str(player["espn_id"])] = {
                            "espn_id": str(player["espn_id"]),
                            "player_id": int(player["id"]),
                            "sackmann_player_id": str(sackmann[0]) if sackmann else None,
                        }

                status = str(row["state"] or game.get("state") or "unknown").lower()
                hs, aws = home.get("sets") or [], away.get("sets") or []
                total_games = (sum(int(v) for v in hs) + sum(int(v) for v in aws)
                               if status == "post" and hs and len(hs) == len(aws) else None)
                hscore, ascore = home.get("score"), away.get("score")
                winner = (home.get("name") if hscore is not None and ascore is not None and hscore > ascore
                          else away.get("name") if hscore is not None and ascore is not None and ascore > hscore
                          else None)
                # Retirements can have no match-level winner score even when
                # the persisted set score identifies the player advancing.
                if winner is None and status == "post" and "retir" in str(game.get("status") or "").lower():
                    try:
                        home_games = sum(int(value) for value in home.get("sets") or [])
                        away_games = sum(int(value) for value in away.get("sets") or [])
                        if home_games != away_games:
                            winner = home.get("name") if home_games > away_games else away.get("name")
                    except (TypeError, ValueError):
                        pass
                set_breakdown = None
                if status == "post" and hs and len(hs) == len(aws):
                    set_breakdown = {
                        "home": [int(value) for value in hs],
                        "away": [int(value) for value in aws],
                    }
                slate.append({
                    "gameId": str(row["game_id"]), "tour": league,
                    "event": game.get("event"), "round": game.get("round"),
                    "tournamentId": str(game.get("tournament_id") or ""),
                    "startTime": row["start_time"],
                    "status": {"pre": "scheduled", "in": "live", "post": "final"}.get(status, "unknown"),
                    "home": home.get("name") or home.get("abbrev") or "Home",
                    "away": away.get("name") or away.get("abbrev") or "Away",
                    "homeAthleteId": home_id,
                    "awayAthleteId": away_id,
                    "projection": None,
                    "result": {"winner": winner,
                               "homeAces": match_stats.get(str(row["game_id"]), {}).get("home_aces"),
                               "awayAces": match_stats.get(str(row["game_id"]), {}).get("away_aces"),
                               "acesSourceUrl": match_stats.get(str(row["game_id"]), {}).get("source_url"),
                               "totalGames": total_games,
                               "sets": set_breakdown} if status == "post" else None,
                    "identity": {"home": spine.get(home_id), "away": spine.get(away_id)},
                    "odds": bovada_odds(con, row["game_id"], league,
                                        (spine.get(home_id) or {}).get("player_id"),
                                        (spine.get(away_id) or {}).get("player_id"), now_utc),
                })
            from tennis_daily_projections import (
                needs_projection_refresh, project_day, stored_candidates, store_candidates,
            )
            now = dt.datetime.now(dt.timezone.utc)
            candidates = {}
            by_model_day = {}
            for match in slate:
                if match["status"] != "scheduled" or not match["startTime"]:
                    continue
                try:
                    starts_at = dt.datetime.fromisoformat(match["startTime"].replace("Z", "+00:00"))
                    if starts_at.tzinfo is None:
                        starts_at = starts_at.replace(tzinfo=dt.timezone.utc)
                except (TypeError, ValueError):
                    continue
                starts_at_utc = starts_at.astimezone(dt.timezone.utc)
                if (utc_start.replace(tzinfo=dt.timezone.utc) <= starts_at_utc
                        < utc_end.replace(tzinfo=dt.timezone.utc) and starts_at_utc > now):
                    by_model_day.setdefault(starts_at_utc.date().isoformat(), []).append(match)
            for model_day, day_matches in by_model_day.items():
                # Refresh old feature schemas and projections computed before a player was
                # resolved through the tennis spine.
                stored = stored_candidates(con, league, model_day)
                if needs_projection_refresh(stored, day_matches):
                    stored = project_day(con, league, model_day, day_matches)
                    store_candidates(con, league, model_day, stored, now.isoformat())
                candidates.update(stored)
            if winner_model == "elo_informed_v2":
                v2_records = _tennis_v2_ledger_records(league, None)
                accuracy_scores.extend(_tennis_v2_winner_accuracy(v2_records))
            else:
                v2_records = {}
                accuracy_scores.extend(_tennis_page_winner_accuracy(con, league))
            for match in slate:
                candidate = candidates.get(match["gameId"])
                starts_at = None
                try:
                    if match["startTime"]:
                        starts_at = dt.datetime.fromisoformat(match["startTime"].replace("Z", "+00:00"))
                        if starts_at.tzinfo is None:
                            starts_at = starts_at.replace(tzinfo=dt.timezone.utc)
                except (TypeError, ValueError):
                    pass
                # Freeze a forecast during the hour before the published start.
                # A final can only be graded from this pregame snapshot.
                if (candidate is not None and match["status"] == "scheduled" and starts_at is not None
                        and now < starts_at.astimezone(dt.timezone.utc) <= now + dt.timedelta(hours=1)):
                    locked_projection = dict(candidate)
                    # Market data is provenance attached to the lock, not a model feature.
                    # Existing lock rows remain immutable and simply have no frozen quote.
                    locked_projection["_frozenOdds"] = match["odds"]
                    con.execute(
                        "INSERT OR IGNORE INTO tennis_model_locks(league,game_date,game_id,start_time,locked_at,projection,model_version) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (league, starts_at.astimezone(dt.timezone.utc).date().isoformat(), match["gameId"], match["startTime"],
                         now.isoformat(), json.dumps(locked_projection), candidate.get("modelVersion")),
                    )
                # Shadow forecasts are written beside the served lock, in the same window, and never replace it.
                if (match["status"] == "scheduled" and starts_at is not None
                        and now < starts_at.astimezone(dt.timezone.utc) <= now + dt.timedelta(hours=1)):
                    write_shadow_locks(con, league, match, starts_at.astimezone(dt.timezone.utc), now, shadow_replays)
                lock = con.execute(
                    "SELECT projection,locked_at FROM tennis_model_locks WHERE league=? AND game_id=?",
                    (league, match["gameId"]),
                ).fetchone()
                locked_projection = json.loads(lock["projection"]) if lock else None
                frozen_odds = (locked_projection.pop("_frozenOdds", None)
                               if locked_projection is not None else None)
                projection = locked_projection if lock else (
                    candidate if match["status"] == "scheduled" and starts_at is not None and starts_at > now else None
                )
                if projection is not None and "_sackmannPlayerIds" in projection:
                    projection = {
                        key: value for key, value in projection.items()
                        if key != "_sackmannPlayerIds"
                    }
                match["projection"] = projection
                match["lockedAt"] = lock["locked_at"] if lock else None
                match["preview"] = bool(projection and not lock)
                match["frozenOdds"] = frozen_odds
                grade = grades.get(match["gameId"])
                match["grades"] = ({
                    "winner": grade["winner"],
                    "winnerBrier": None,
                    "homeAcesError": None,
                    "awayAcesError": None,
                    "totalGamesError": grade["total_games_error"],
                } if grade else None)
                if winner_model == "elo_informed_v2":
                    _apply_tennis_v2_winner(match, v2_records.get(match["gameId"]))
                if match["grades"] is not None:
                    match["grades"]["winnerBrier"] = _winner_brier(
                        (match.get("projection") or {}).get("probability"),
                        match["grades"].get("winner"),
                    )
                match["lockStatus"] = _tennis_lock_status(
                    match["startTime"], match["lockedAt"], match["projection"], now
                )
                # IDs are needed only while calculating; keep the public match payload tidy.
                match.pop("homeAthleteId", None)
                match.pop("awayAthleteId", None)
                match.pop("tournamentId", None)
                out.append(match)
        con.commit()
    model_reason = None
    if winner_model == "elo_informed_v2" and not any(
        (match.get("projection") or {}).get("projectedWinner") for match in out
    ):
        model_reason = "No locked Elo-informed V2 forecasts are available for this date yet."
    return {
        "available": True,
        "reason": None if out else "No persisted tennis matches are available for this date.",
        "winnerModel": winner_model,
        "winnerModelReason": model_reason,
        "accuracy": {
            "winnerBrier": (sum(accuracy_scores) / len(accuracy_scores)) if accuracy_scores else None,
            "brierN": len(accuracy_scores),
        },
        "source": "scoreboard_snapshots + tennis spine + pre-match Sackmann history",
        "matches": out,
    }


@router.get("/api/soccer/competitions/{league}")
def soccer_competition(league: str):
    """Persisted competition hub data for Soccer; never calls ESPN."""
    league = str(league or "").lower()
    if league not in ("mls", "lcup"):
        raise HTTPException(404, "competition snapshot is not supported")
    snapshot = scoreboard_store.read_soccer_competition(league)
    if snapshot is None:
        return {
            "available": False,
            "league": league,
            "reason": (
                "MLS standings have not been published into this environment yet."
                if league == "mls"
                else "The Leagues Cup bracket has not been published into this environment yet."
            ),
        }
    return {"available": True, **snapshot}


@router.get("/api/stream/{league}")
def stream_league_audio(league: str):
    from fastapi.responses import StreamingResponse
    import subprocess

    url = _LCUP_RADIO.get(league.lower())
    if not url:
        raise HTTPException(404, "no audio stream for this league")
    proc = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-i", url, "-vn",
         "-ac", "1", "-ar", "44100", "-b:a", "96k", "-f", "mp3", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )

    def gen():
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                proc.kill()
            except Exception:
                pass

    return StreamingResponse(gen(), media_type="audio/mpeg",
                             headers={"Cache-Control": "no-store"})
