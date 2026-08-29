"""routers/games/standings.py — strength/standings endpoints and helpers."""
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from _core import *
from . import router


def _db():
    """Resolve `routers.games._db` at call time (see scoreboard.py `_db`)."""
    from routers.games import _db as _pkg_db
    return _pkg_db()


def _pkg_seasons_we_hold(league):
    """Resolve `routers.games.seasons_we_hold` at call time.

    Tests patch the package attribute (`patch.object(games, "seasons_we_hold",
    return_value=...)`) before calling `_offer_only_seasons_we_hold`, so the
    call must read through the package namespace, not the module-local binding.
    """
    from routers.games import seasons_we_hold as _pkg_swh
    return _pkg_swh(league)



# The tables that make a season worth offering. A standings year the rest of
# the app cannot follow up on — no players, no logs, no team aggregates — is a
# table attached to nothing.
_SEASON_EVIDENCE_TABLES = ("player_stats", "player_game_logs", "team_game_results")


def seasons_we_hold(league: str):
    """Seasons this league actually has data for in OUR tables.

    ESPN will serve 24-25 years of standings for every league. Measured
    2026-08-17 we hold one to three seasons each, so the picker was offering two
    decades of tables that connect to nothing else on the site — pick 2003 and
    the Stats tab, the game logs and the props all have nothing to say.

    A missing table is not an empty answer: it means we cannot tell what we hold,
    so it is skipped rather than counted as zero.
    """
    held = set()
    lg = (league or "").lower()
    try:
        with closing(_db()) as con:
            names = {row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            for table in _SEASON_EVIDENCE_TABLES:
                if table not in names:
                    continue
                try:
                    held.update(
                        row[0] for row in con.execute(
                            f"SELECT DISTINCT season FROM {table}"
                            " WHERE league=? AND season IS NOT NULL",
                            (lg,),
                        ) if isinstance(row[0], int)
                    )
                except sqlite3.Error:
                    continue
    except sqlite3.Error as exc:
        print(f"[standings] cannot read held seasons league={lg}: {type(exc).__name__}: {exc}")
        return set()
    return held


def _offer_only_seasons_we_hold(payload, league: str):
    """Narrow a standings envelope's `available_seasons` to years we hold.

    The season being SERVED is always offered even when we hold nothing for it —
    it is what is on screen, and dropping it would leave the pill naming a year
    that is not in its own option list. Everything else has to earn its place by
    having data behind it.
    """
    if not isinstance(payload, dict):
        return payload
    offered = payload.get("available_seasons")
    if not isinstance(offered, list) or not offered:
        return payload
    held = _pkg_seasons_we_hold(league)
    served = payload.get("season")
    # Keep the publisher's newest season even while an older year is selected.
    # Otherwise selecting the last season we hold removes the current year from
    # the response and traps the picker on the historical table.
    current = max((year for year in offered if isinstance(year, int)), default=None)
    kept = [
        year for year in offered
        if year in held or year == served or year == current
    ]
    if served is not None and served not in kept:
        kept.append(served)
    payload["available_seasons"] = sorted(set(kept), reverse=True)
    return payload


def _strength_from_db(league: str):
    """Latest ESPN-published strength snapshot, without deriving missing fields."""
    try:
        with closing(_db()) as con:
            rows = con.execute(
                "SELECT captured_at, abbrev, win_pct, differential, wins, losses"
                " FROM strength_snap WHERE league=? AND captured_at=("
                " SELECT MAX(captured_at) FROM strength_snap WHERE league=?"
                ") ORDER BY win_pct DESC, abbrev",
                (league.lower(), league.lower()),
            ).fetchall()
    except sqlite3.Error as exc:
        print(
            f"[strength] DB fallback unavailable league={league.lower()} "
            f"error={type(exc).__name__}: {exc}"
        )
        return []

    return [
        {
            "abbrev": row["abbrev"],
            "name": None,
            "wins": row["wins"],
            "losses": row["losses"],
            "win_pct": row["win_pct"],
            "differential": row["differential"],
            "streak": None,
            "last10": None,
            "games_played": None,
            "captured_at": row["captured_at"],
            "source": "strength_snap",
        }
        for row in rows
        if row["abbrev"] and row["win_pct"] is not None
    ]


@router.get("/api/{league}/strength")
def get_strength(league: str):
    """Teams ranked by quality (win%, differential, streak, last-10) — the selection prior."""
    try:
        rows = espn.team_strength(league)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as exc:
        rows = _strength_from_db(league)
        data_source = "strength_snap" if rows else "unavailable"
        print(
            f"[strength] publisher unavailable league={league.lower()} "
            f"error={type(exc).__name__}: {exc}; fallback_rows={len(rows)} "
            f"source={data_source}"
        )
        return JSONResponse(
            content=rows,
            headers={
                "Cache-Control": "public, max-age=30",
                "X-LP-Data-Source": data_source,
            },
        )
    _snapshot_strength(league.lower(), rows)
    return JSONResponse(
        content=rows,
        headers={
            "Cache-Control": "public, max-age=300",
            "X-LP-Data-Source": "espn",
        },
    )


@router.get("/api/{league}/standings")
def get_standings(league: str, season: int = None):
    """Group/division standings. For World Cup: group tables during the group
    stage; the canonical knockout bracket/results once the season phase leaves
    'Group' (progression gate via espn.wc_is_knockout — never serve stale groups
    once knockouts have begun)."""
    lg = league.lower()
    if lg == "ncaaf":
        # Conference-grouped tables - CFB's /standings payload has no
        # rank/gamesPlayed/losses keys; the record lives in `overall` and
        # entries arrive pre-ordered by conference standing. See
        # espn_client.ncaaf_conference_standings.
        try:
            return _offer_only_seasons_we_hold(
                espn.ncaaf_conference_standings(season=season), lg
            )
        except ValueError as e:
            raise HTTPException(404, str(e))
        except HTTPException:
            raise
        except Exception:
            # An unreachable publisher rendered as a 500 stacktrace here. There
            # is no conference-standings snapshot to fall back to, so this stays
            # fail-closed — but it says why, the way the MLS branch does, rather
            # than surfacing "Internal Server Error" to the page.
            raise HTTPException(503, "NCAAF standings unavailable: publisher unreachable")
    if lg == "mls":
        # Eastern/Western tables read from the publisher, carrying the season
        # they belong to. This replaced a DB rollup on 2026-08-17: the rollup's
        # arithmetic was exact (verified against ESPN's published 2025 table,
        # 30/30 teams, zero disagreements) but it served `MAX(season)` of what
        # our tables hold, and they only ever hold a COMPLETED season — so in
        # mid-August it served the 2025 final table, unlabelled.
        #
        # Same doctrine as the World Cup branch below: a standings surface may
        # not serve a table from a season that is over while a season is being
        # played. Upstream failure is a 503 with a reason, never a fall-through
        # to last year (fail-loudly: the stale table is the plausible output
        # that hides the defect).
        try:
            return _offer_only_seasons_we_hold(
                espn.mls_conference_standings(season=season), lg
            )
        except ValueError as e:
            raise HTTPException(503, f"MLS standings unavailable: {e}")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "MLS standings unavailable: publisher unreachable")
    if lg != "wc":
        # The envelope, not the bare row list: a standings table with nothing
        # naming its season is the defect this fixes. /api/{league}/strength
        # keeps the list shape — it is the selection prior, has its own DB
        # fallback, and several callers index it directly.
        try:
            return _offer_only_seasons_we_hold(
                espn.team_strength_standings(lg, season=season), lg
            )
        except ValueError as e:
            raise HTTPException(404, str(e))
        except Exception as exc:
            # This page used to read /strength, which degrades to the last
            # published snapshot when the publisher is unreachable. ESPN 403s
            # this box routinely, so moving the page here without carrying the
            # fallback across turned a degraded table into a 500.
            #
            # A snapshot cannot answer "which season is this", so it is served
            # with season=None and no selectable years: the table renders
            # without a pill rather than under a year we are guessing. And a
            # snapshot is never served for an EXPLICITLY requested season — it
            # is not that season, and quietly substituting it is the stale-table
            # failure this route already refuses for MLS.
            if season is not None:
                raise HTTPException(
                    503, f"{lg} standings for {season} unavailable: publisher unreachable"
                )
            rows = _strength_from_db(lg)
            print(
                f"[standings] publisher unavailable league={lg} "
                f"error={type(exc).__name__}: {exc}; fallback_rows={len(rows)}"
            )
            if not rows:
                raise HTTPException(503, f"{lg} standings unavailable: publisher unreachable")
            return JSONResponse(
                content={"league": lg, "season": None, "season_label": None,
                         "available_seasons": [], "teams": rows},
                headers={"Cache-Control": "public, max-age=30",
                         "X-LP-Data-Source": "strength_snap"},
            )
    # WC: group tables are ONLY valid during the Group phase. Once knockouts
    # have begun, serve the canonical bracket ONLY — never stale group tables.
    # The no-stale-group fallback: if the bracket is empty/unavailable while
    # knockouts are live, return 503 rather than silently serving yesterday's
    # Group standings (the swallowed-exception fall-through that regressed here).
    # Any upstream failure on the knockout path (phase lookup or bracket fetch)
    # becomes 503 too — never an uncaught 500, never a stale-group fall-through.
    try:
        knockout = espn.wc_is_knockout()
    except Exception:
        # Phase lookup failed — we cannot confirm groups are still valid, so do
        # NOT fall through to group_standings (that would serve stale tables).
        raise HTTPException(503, "World Cup phase lookup unavailable")
    if knockout:
        try:
            bracket = espn.wc_knockout_standings()
        except HTTPException:
            raise  # preserve an already-shaped HTTP error from the client layer
        except Exception:
            raise HTTPException(503, "World Cup knockout bracket unavailable")
        if bracket.get("rounds"):
            return bracket
        raise HTTPException(503, "World Cup knockout bracket is unavailable")
    # Group phase — serve group tables
    try:
        return espn.group_standings(league)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/api/{league}/strength/{team}")
def get_team_strength(league: str, team: str):
    try:
        m = espn.team_strength_map(league)
    except ValueError as e:
        raise HTTPException(404, str(e))
    row = m.get(team.upper())
    if not row:
        raise HTTPException(404, f"team {team!r} not found in {league}")
    return row
