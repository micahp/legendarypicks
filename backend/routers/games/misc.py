"""routers/games/misc.py — root/health/coverage and the audio stream endpoint."""
import datetime as dt
import json
import os

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
def tennis_model(date: str, tour: str = "all", utc_offset_minutes: int = 0):
    """Read a local-day slate and resolve participants through the tennis spine.

    Future matches carry a preview; only forecasts frozen before start are eligible
    for a final grade.
    """
    tour = str(tour or "all").lower()
    if tour not in ("all", "atp", "wta"):
        raise HTTPException(400, "tour must be all, atp, or wta")
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
    with closing(_db()) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS tennis_model_locks("
            "league TEXT NOT NULL,game_date TEXT NOT NULL,game_id TEXT NOT NULL,start_time TEXT NOT NULL,"
            "locked_at TEXT NOT NULL,projection TEXT NOT NULL,model_version TEXT,PRIMARY KEY(league,game_id))"
        )
        from tennis_bovada_odds import bovada_odds
        now_utc = dt.datetime.now(dt.timezone.utc)
        for league in tours:
            rows = con.execute(
                "SELECT game_id,payload,state,start_time FROM scoreboard_snapshots "
                "WHERE league=? AND game_date BETWEEN ? AND ? ORDER BY start_time,game_id",
                (league, date_from, date_through),
            ).fetchall()
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
                    "result": {"winner": winner, "homeAces": None, "awayAces": None,
                               "totalGames": total_games,
                               "sets": set_breakdown} if status == "post" else None,
                    "identity": {"home": spine.get(home_id), "away": spine.get(away_id)},
                    "odds": bovada_odds(con, row["game_id"], league,
                                        (spine.get(home_id) or {}).get("player_id"),
                                        (spine.get(away_id) or {}).get("player_id"), now_utc),
                })
            from tennis_daily_projections import project_day
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
                candidates.update(project_day(con, league, model_day, day_matches))
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
                    con.execute(
                        "INSERT OR IGNORE INTO tennis_model_locks(league,game_date,game_id,start_time,locked_at,projection,model_version) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (league, starts_at.astimezone(dt.timezone.utc).date().isoformat(), match["gameId"], match["startTime"],
                         now.isoformat(), json.dumps(candidate), candidate.get("modelVersion")),
                    )
                lock = con.execute(
                    "SELECT projection,locked_at FROM tennis_model_locks WHERE league=? AND game_id=?",
                    (league, match["gameId"]),
                ).fetchone()
                projection = json.loads(lock["projection"]) if lock else (
                    candidate if match["status"] == "scheduled" and starts_at is not None and starts_at > now else None
                )
                match["projection"] = projection
                match["lockedAt"] = lock["locked_at"] if lock else None
                match["preview"] = bool(projection and not lock)
                result = match["result"]
                match["grades"] = ({
                    "winner": ("correct" if projection.get("projectedWinner") == result.get("winner") else "incorrect")
                    if projection and projection.get("projectedWinner") and result and result.get("winner") else None,
                    "homeAcesError": None,
                    "awayAcesError": None,
                    "totalGamesError": abs(projection["totalGames"] - result["totalGames"])
                    if projection and projection.get("totalGames") is not None and result and result.get("totalGames") is not None else None,
                } if projection else None)
                # IDs are needed only while calculating; keep the public match payload tidy.
                match.pop("homeAthleteId", None)
                match.pop("awayAthleteId", None)
                match.pop("tournamentId", None)
                out.append(match)
        con.commit()
    return {
        "available": True,
        "reason": None if out else "No persisted tennis matches are available for this date.",
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
