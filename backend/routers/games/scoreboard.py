"""routers/games/scoreboard.py — /api/{league}/games serving path and its helpers."""
import datetime as dt

from fastapi import HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *
from . import router
from .contexts import _attach_cod_detail_ids


def _db():
    """Resolve `routers.games._db` at call time.

    Tests patch the package attribute (`patch.object(games, "_db", fixture)`)
    before calling handlers, so the DB door must be read through the package
    namespace when a handler runs, not bound at import time.
    """
    from routers.games import _db as _pkg_db
    return _pkg_db()


def kick_game_stories(*args, **kwargs):
    """Resolve `routers.games.kick_game_stories` at call time (see `_db`)."""
    from routers.games import kick_game_stories as _pkg_kgs
    return _pkg_kgs(*args, **kwargs)



# How stale our own last read may be before the serving path stops trusting it.
# The schedule timer runs every 10 minutes and the live poller every minute, so
# anything past this means a timer is not running -- and a dead timer must
# degrade to calling the publisher, not quietly serve a half-hour-old score.
# Staleness that nobody can see is worse than a slow page: a frozen board looks
# exactly like a correct one.
_SNAPSHOT_MAX_AGE = 15 * 60


def _scoreboard_snapshot(league: str, game_date: str):
    """Our stored slate for this day, or None to fall through to the publisher.

    None means one of two things, and both of them are honest reasons to ask
    upstream: we have never fetched this (league, date), or what we hold is
    older than `_SNAPSHOT_MAX_AGE`. An empty list is different -- it is the
    publisher having told us there are no games -- and it is served as such.
    """
    try:
        import scoreboard_store
        stored = scoreboard_store.read(league, game_date)
    except Exception as exc:
        print(f"[scores] snapshot unreadable league={league} date={game_date}: "
              f"{type(exc).__name__}: {exc}")
        return None
    if stored is None:
        return None
    age = stored.get("age_seconds")
    if age is None:
        return None
    if age > _SNAPSHOT_MAX_AGE:
        states = {str(game.get("state") or "").lower()
                  for game in stored["games"]}
        # Never serve a stale live score. Scheduled and completed games are
        # durable publisher facts, though, and must not disappear merely
        # because the next timer tick or shared lock is late.
        safe_stale = bool(stored["games"]) and "in" not in states
        if not safe_stale and not _nothing_newer_to_have(league, game_date):
            return None
    return stored["games"], age


def _capture_completed_day(league: str, game_date: str, games) -> None:
    """Persist a finished day the ingest never got to, so it is asked once.

    This is the only write the serving path makes, and it is what turns the
    "never ask about a finished day" rule from a promise into a fact: the next
    viewer reads SQLite. A failure here is logged and swallowed -- the response
    is already correct, and a board must not 500 because a cache write did.
    """
    try:
        import scoreboard_store
        scoreboard_store.save(league, game_date, games, source="espn")
    except Exception as exc:
        print(f"[scores] could not store completed day league={league} "
              f"date={game_date}: {type(exc).__name__}: {exc}")


def _nothing_newer_to_have(league: str, game_date: str) -> bool:
    """Is this snapshot old because a timer died, or because it is finished?

    The age ceiling exists to catch a dead timer. It must not also retire the
    days the ingest is deliberately not refreshing -- an out-of-season league,
    a day where every game is final, a slate the publisher said was empty. Those
    go hours or months without a write BY DESIGN, and falling through to ESPN
    for them would put back exactly the per-request upstream call this replaced,
    on the leagues that need it least.
    """
    try:
        import league_activity
        import scoreboard_store
        if league_activity.plays_on(league, game_date) is False:
            return True
        wanted, _ = scoreboard_store.needs_refresh(league, game_date)
        return not wanted
    except Exception:
        # Unknown is not "fine". Fall through and ask the publisher.
        return False


def _games_from_db(league: str, game_date: str):
    """Return completed publisher results in the scoreboard's shared shape.

    ``team_game_results.game_date`` is day-precision data.  Keep it that way:
    inventing ``T00:00:00Z`` would move the result onto the prior viewer-local
    day throughout the Americas.  The browser recognizes a date-only value and
    keeps it in the backend bucket that was requested.

    A game is usable only when the published result holds exactly one home row
    and one away row with reciprocal scores.  A partial or contradictory pair
    is not a scoreboard result and is reported rather than rendered.
    """
    try:
        with closing(_db()) as con:
            rows = con.execute(
                "SELECT game_id, game_date, team, opponent, home_away,"
                " score_for, score_against, status"
                " FROM team_game_results WHERE league=? AND game_date=?"
                " AND status='completed'"
                " ORDER BY game_id, home_away, team",
                (league.lower(), game_date),
            ).fetchall()
    except sqlite3.Error as exc:
        print(
            f"[scores] DB fallback unavailable league={league.lower()} "
            f"date={game_date} error={type(exc).__name__}: {exc}"
        )
        return []

    grouped = {}
    for row in rows:
        grouped.setdefault(str(row["game_id"]), []).append(row)

    games = []
    rejected = []
    for game_id, pair in grouped.items():
        homes = [row for row in pair if row["home_away"] == "home"]
        aways = [row for row in pair if row["home_away"] == "away"]
        if len(homes) != 1 or len(aways) != 1:
            rejected.append(game_id)
            continue
        home, away = homes[0], aways[0]
        if (
            home["score_for"] is None
            or away["score_for"] is None
            or home["score_against"] != away["score_for"]
            or away["score_against"] != home["score_for"]
        ):
            rejected.append(game_id)
            continue

        games.append({
            "game_id": game_id,
            "date": str(home["game_date"]),
            "date_precision": "day",
            "state": "post",
            "completed": True,
            "status": home["status"],
            "home": {"abbrev": home["team"], "score": home["score_for"]},
            "away": {"abbrev": away["team"], "score": away["score_for"]},
        })

    if rejected:
        print(
            f"[scores] DB fallback rejected {len(rejected)} unpaired or "
            f"contradictory games league={league.lower()} date={game_date}: "
            f"{','.join(rejected[:10])}"
        )
    return games


@router.get("/api/{league}/games")
def get_games(league: str, date: Optional[str] = Query(None, description="YYYY-MM-DD (default today)")):
    if league.lower() == "cod":
        # Call of Duty League — breakingpoint.gg (persists completed matches)
        # Falls back to cdl_client if breakingpoint is unreachable
        try:
            import breakingpoint_client
            matches = breakingpoint_client.get_cod_matches(date_str=date)
            if matches:
                # EWC bracket rows: reconcile against the indexed PandaScore codmw EWC window
                # (once per refresh) so raw "TBD" participants never reach the scoreboard. Non-EWC
                # CDL rows pass through unchanged. See routers/esports/cod_ewc.py.
                from routers.esports.cod_ewc import reconcile_cod_matches
                matches = reconcile_cod_matches(matches)
                return _attach_cod_detail_ids(matches)
        except Exception as e:
            print(f"[sports_service] breakingpoint failed ({e}), falling back to cdl_client")
        import cdl_client
        return _attach_cod_detail_ids(cdl_client.get_matches(date_str=date))
    lg = league.lower()
    data_source = "espn"
    requested_date = date or dt.date.today().isoformat()
    try:
        is_completed_day = date is not None and dt.date.fromisoformat(date) < dt.date.today()
    except ValueError:
        is_completed_day = False

    games = _games_from_db(lg, requested_date) if is_completed_day else None
    snapshot_age = None
    if games:
        data_source = "team_game_results"
    else:
        # Rung 1 is now OUR OWN last read of the publisher, not the publisher.
        # `ingest_scoreboards.py` refreshes the slate on a timer and re-reads
        # only what is in flight, so the page costs a SQLite read and the
        # upstream spend stops scaling with how many people are on the site.
        # Measured 2026-08-18: a cold board was 22 ESPN requests, and the
        # serving process answers its own per-host ceiling with a 60 second
        # sleep, so the board stalled itself every few loads.
        snapshot = _scoreboard_snapshot(lg, requested_date)
        if snapshot is not None:
            games, snapshot_age = snapshot
            data_source = "scoreboard_snapshots"
    if is_completed_day and (games is None or data_source == "espn"):
        # A DAY THAT IS OVER IS NEVER WORTH A SECOND REQUEST. Its result cannot
        # change, so once we hold it we hold it forever and every later view is
        # a SQLite read. But "never ask" and "never captured" are not the same
        # thing, and conflating them is what blanked the board: measured
        # 2026-08-18, `team_game_results` holds NFL only, so every other league
        # had no finished-day rung at all and 08-15 through 08-17 served zero
        # games. So a gap is filled once, from the publisher, and written to the
        # store on the way out. The cost is one request per (league, day) for
        # the whole life of that day, not one per viewer.
        games = games or []
        if not games:
            try:
                games = espn.games(league, date)
                data_source = "espn"
                _capture_completed_day(lg, requested_date, games)
            except ValueError as e:
                raise HTTPException(404, str(e))
            except Exception as exc:
                print(f"[scores] completed day uncapturable league={lg} "
                      f"date={requested_date}: {type(exc).__name__}: {exc}")
                games = []
                data_source = "unavailable"
    elif games is None or (not games and data_source == "espn"):
        try:
            games = espn.games(league, date)
        except ValueError as e:
            raise HTTPException(404, str(e))
        except Exception as exc:
            games = _games_from_db(lg, requested_date)
            data_source = "team_game_results" if games else "unavailable"
            if not games:
                # Third rung. We persist FINISHED games, so on the day itself
                # the DB has nothing and the board goes blank — which is exactly
                # when ESPN's per-host request COUNT runs out. Bovada is a
                # different host with the same slate, and its per-event endpoint
                # carries score and clock. It never invents one: a game it
                # cannot vouch for arrives with score None and renders as a dash.
                try:
                    import scoreboard_fallback
                    games = scoreboard_fallback.bovada_games(lg, requested_date)
                    if games:
                        data_source = "bovada"
                except Exception as fallback_exc:
                    print(f"[scores] bovada fallback failed league={lg}: "
                          f"{type(fallback_exc).__name__}: {fallback_exc}")
                    games = []
            print(
                f"[scores] publisher unavailable league={lg} date={requested_date} "
                f"error={type(exc).__name__}: {exc}; "
                f"fallback_games={len(games)} source={data_source}"
            )

    # ── finished-game final score: prefer our captured final ───────────────
    # The schedule above is ESPN-first because live and upcoming games are not
    # persisted.  For a post-state game, however, prefer OUR captured final
    # (scoring_plays, then team_game_results) over the scoreboard tick. These
    # helpers are DB-only; they make no additional ESPN request.
    if data_source == "espn":
        for g in games:
            if g.get("state") != "post":
                continue
            final = _final_score_from_db(lg, g["game_id"])
            if final:
                if g.get("home"):
                    g["home"]["score"] = final["home"]
                if g.get("away"):
                    g["away"]["score"] = final["away"]
    # "Write the preview whenever we find out about the game." That used to mean
    # this handler, because the page load was the fetch. It is not any more: the
    # ingest is where we find out, so `ingest_scoreboards.py` kicks the stories
    # and this only covers the path where the handler did call the publisher
    # itself. Leaving it on the snapshot path as well would put the generation
    # back into the request that the snapshot exists to keep cheap.
    if data_source == "espn" and lg in ("nba", "nhl", "mlb", "nfl"):
        kick_game_stories(lg, games)
    max_age = 15 if data_source == "unavailable" else 30
    headers = {
        "Cache-Control": f"public, max-age={max_age}",
        "X-LP-Data-Source": data_source,
    }
    if snapshot_age is not None:
        # How old the publisher's answer is, not how old the response is. A
        # score with no age is a claim about now that we cannot support.
        headers["X-LP-Data-Age"] = str(snapshot_age)
    return JSONResponse(content=games, headers=headers)
