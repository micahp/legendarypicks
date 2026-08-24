"""routers/games/misc.py — root/health/coverage and the audio stream endpoint."""
import os

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from _core import *
from provenance import publishers_for
from sport_navigation import league_directory_navigation, prop_navigation
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


@router.get("/api/navigation/sports")
def sport_navigation():
    """DB-backed competition coverage with sport derived from publisher paths."""
    with closing(_db()) as con:
        return {
            "props": prop_navigation(con),
            "leagues": league_directory_navigation(con),
        }


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
