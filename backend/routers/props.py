"""routers/props.py — props endpoints. Handlers only; shared code lives in _core."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *
from prop_game_merge import fold_prop_game

router = APIRouter()


# What "still on the board" means, in ONE place because the slate has two query paths (summary and
# fully-nested) and they must not drift apart.
#
# It used to be `pg.date >= date('now')`, and that is two different rulers in one board: `pg.date`
# is a UTC calendar date, but the client groups and labels every game by its LOCAL date derived
# from start_time. A match at 2026-08-17T00:30Z is stored under Aug 17 and rendered as "Sun,
# Aug 16, 7:30 PM" -- so on 2026-08-17 the first thing on the board was a header for YESTERDAY
# holding four games that had already finished (both Sunday-night MLS fixtures, Tiafoe/Sonego,
# Svitolina/Valentova). The board looked frozen in time.
#
# So filter on the instant, not the calendar date. The 3-hour grace keeps a game that is currently
# being played on the board and drops it once it is over; a pregame props board that still lists a
# finished game is offering a bet nobody can take.
#
# COALESCE matters: 17 of the 75 upcoming MLS rows carry no start_time at all (2026-08-17), and a
# bare start_time comparison would silently delete them from the board. Those fall back to the end
# of their stored date, so a row with no time survives the whole day it is dated for.
# Named, because ORDERING needs the same ruler as filtering. 2026-08-19: the filter above
# was fixed to use the instant and the ORDER BY was left on `pg.date`, so once two rows
# disagreed about which calendar day a 21:30 ET kickoff belongs to, a 9:30pm game sorted
# ahead of a 7:00pm one on the same board.
# The fallback is `date(pg.date, '+1 day') || 'T05:00:00'`, not `pg.date || 'T23:59:59Z'`,
# and the difference is the 2026-08-19 convention fix. `pg.date` is now the America/New_York
# SLATE DAY for every league but tennis, so `pg.date || 'T23:59:59Z'` is not the end of that
# day at all -- it is 7:59pm Eastern, in the middle of the evening slate. A timeless row
# dated today fell off the board mid-evening, and only looked roughly right because the
# 3-hour grace below happened to push it to about 11pm.
# 05:00Z is midnight Eastern in EST, the worst case of the two offsets. In EDT that is one
# extra hour of grace for a row whose kickoff we do not know, which is the safe direction:
# this fallback exists precisely so a row with no time is not silently deleted from the board.
_KICKOFF = ("datetime(COALESCE(NULLIF(pg.start_time, ''), "
            "date(pg.date, '+1 day') || 'T05:00:00'))")

_UPCOMING = _KICKOFF + " >= datetime('now', '-3 hours')"


_CorePropIngest = PropIngest


class PropIngest(_CorePropIngest):
    start_time: Optional[str] = None


def _league_sql(column: str, league: Optional[str], leagues: Optional[str]):
    """A bound league predicate supporting one legacy key or a sport rollup."""
    if isinstance(league, str) and league.strip():
        return f" AND LOWER({column}) = ?", [league.strip().lower()]
    league_rollup = leagues if isinstance(leagues, str) else ""
    values = sorted({
        value.strip().lower()
        for value in league_rollup.split(",")
        if value.strip()
    })
    if not values:
        return "", []
    return (
        f" AND LOWER({column}) IN ({','.join('?' for _ in values)})",
        values,
    )

@router.get("/api/props")
def list_props(player: Optional[str] = Query(None),
               market: Optional[str] = Query(None),
               league: Optional[str] = Query(None),
               leagues: Optional[str] = Query(None),
               date: Optional[str] = Query(None),
               limit: int = Query(50, ge=1, le=500),
               offset: int = Query(0, ge=0)):
    sql = """SELECT p.id, p.market, p.line, p.side, p.source, p.captured_at,
                    p.odds,
                    p.player_id,
                    pl.name AS player_name, pl.team AS player_team, pl.league,
                    pg.home AS game_home, pg.away AS game_away, pg.date AS game_date,
                    r.actual_value, r.hit, r.settled_at
             FROM props p
             JOIN players pl ON pl.id = p.player_id
             JOIN prop_games pg ON pg.id = p.game_id
             LEFT JOIN prop_results r ON r.prop_id = p.id
             WHERE 1=1"""
    params = []
    if player:
        sql += " AND pl.name LIKE ?"
        params.append(f"%{player}%")
    if market:
        # Market-first boards group source-specific keys such as
        # `total_bases___player_slug` under their base market.
        sql += " AND (p.market = ? OR instr(p.market, ? || '___') = 1)"
        params.extend((market, market))
    # Filter on the game's competition. Leagues Cup athletes belong to their
    # MLS or Liga MX identity spine, so filtering on pl.league drops the board.
    league_sql, league_params = _league_sql("pg.league", league, leagues)
    sql += league_sql
    params.extend(league_params)
    if date:
        sql += " AND pg.date = ?"
        params.append(date)
    # `captured_at` is shared by every row in one ingest. The id tie-breaker is
    # required for deterministic offset pagination; without it, offers can move
    # between pages and an alternate line can be omitted or duplicated.
    sql += " ORDER BY p.captured_at DESC, p.id DESC LIMIT ? OFFSET ?"
    params.extend((limit, offset))
    with closing(_db()) as con:
        rows = con.execute(sql, params).fetchall()
    return [{"id": r["id"], "market": r["market"], "line": r["line"], "side": r["side"],
             "source": r["source"], "captured_at": r["captured_at"], "odds": r["odds"],
             "player_id": r["player_id"],
             "player_name": r["player_name"], "player_team": r["player_team"],
             "league": r["league"], "game_home": r["game_home"],
             "game_away": r["game_away"], "game_date": r["game_date"],
             "actual_value": r["actual_value"],
             "hit": bool(r["hit"]) if r["hit"] is not None else None,
             "result_status": (
                 "graded" if r["hit"] is not None else
                 "push" if r["actual_value"] is not None else
                 "void" if r["settled_at"] is not None else "pending"
             ),
             "settled_at": r["settled_at"]} for r in rows]


@router.get("/api/props/player/{player_id}/history")
def player_prop_history(player_id: int, market: Optional[str] = Query(None)):
    sql = """SELECT p.id, p.market, p.line, p.side, p.captured_at,
                    r.actual_value, r.hit, r.settled_at
             FROM props p
             LEFT JOIN prop_results r ON r.prop_id = p.id
             WHERE p.player_id = ?"""
    params = [player_id]
    if market:
        sql += " AND p.market = ?"
        params.append(market)
    sql += " ORDER BY p.captured_at DESC LIMIT 200"
    with closing(_db()) as con:
        rows = con.execute(sql, params).fetchall()
    history = [{"id": r["id"], "market": r["market"], "line": r["line"], "side": r["side"],
                "captured_at": r["captured_at"], "actual_value": r["actual_value"],
                "hit": bool(r["hit"]) if r["hit"] is not None else None,
                "settled_at": r["settled_at"]} for r in rows]
    # rolling hit rate (last 20 settled)
    settled = [h for h in history if h["hit"] is not None]
    hit_rate = round(sum(1 for h in settled[-20:] if h["hit"]) / max(len(settled[-20:]), 1), 3) if settled else None
    return {"player_id": player_id, "history": history, "hit_rate": hit_rate, "total_settled": len(settled)}


# Which log leagues a chart may read for a prop in this league. Only a
# cross-border competition needs more than its own.
_CHART_LOG_LEAGUES = {
    "lcup": ("lcup", "mls", "ligamx"),
    # A Liga MX athlete's history is his domestic season plus the
    # tournament, and the row reaches here labelled `ligamx` because
    # /api/props returns the player's league rather than the game's.
    "ligamx": ("ligamx", "lcup"),
    "mls": ("mls", "lcup"),
}


@router.get("/api/props/history")
def prop_history(player_id: int = Query(...),
                 market: str = Query(...),
                 line: float = Query(...),
                 side: str = Query("over"),
                 league: str = Query(...)):
    """Per-game stat history for a prop's player+market, with the line."""
    stat_key = _MARKET_STAT_KEY.get(league, {}).get(_base_market(market))
    if not stat_key:
        return {"error": f"market not chartable from logs: {market}", "games": []}

    # A cross-border tournament's athletes keep their domestic logs, and the chart
    # is about the PLAYER, not the competition the prop happens to sit in. Reading
    # `league='lcup'` alone gave a Liga MX player his three group games and an MLS
    # player three games instead of a season. The union is the same one the
    # resolver and the settler use.
    log_leagues = _CHART_LOG_LEAGUES.get(league, (league,))
    league_placeholders = ",".join("?" for _ in log_leagues)

    # A match the player never entered is not a 0. Both are stored -- the row is
    # a real record of not playing -- but charting it as zero shots would count
    # an absence as a measured performance and drag every hit-rate window down.
    # 2026-08-25: a bench player charted five games, four of them DNPs, as
    # 0/0/0/0/0 shots.
    #
    # ONE ROW PER APPEARANCE, from `player_game_logs_all`. Each provider owns
    # its own TABLE -- `player_game_logs` is ESPN's and stays one row per
    # appearance, `player_game_logs_fotmob` is FotMob's -- and the view joins
    # them on (player_id, game_date), putting each provider's line in its own
    # COLUMN. A value's provenance is the column it was read from: nothing to
    # stamp, nothing to drift.
    #
    # This replaces a ROW_NUMBER() PARTITION BY game_date that existed to hide
    # a duplication. Both providers had been kept as separate ROWS in one
    # table, so 2,619 appearances existed twice and every reader had to know to
    # dedupe or double-count. Federico Vinas charted 12 games,
    # [7,7,4,4,3,3,1,1,1,1,1,1], for six he played.
    #
    # ESPN wins a field both publish: it is the identity spine every player_id
    # is keyed on. FotMob fills the markets ESPN does not publish at all
    # (tackles, clearances, crosses, chances created, dribbles).
    def _val(key):
        return (f"COALESCE(json_extract(espn_stats, '$.{key}'),"
                f" json_extract(fotmob_stats, '$.{key}'))")

    def _present(key):
        return (f"(json_extract(espn_stats, '$.{key}') IS NOT NULL"
                f" OR json_extract(fotmob_stats, '$.{key}') IS NOT NULL)")

    # A match the player never entered is not a 0. The summary ingest writes
    # `appearances`, the lazy core read-through writes `minutes`; either at 0
    # means absent, and a row carrying neither is left alone rather than
    # assumed. Checked across BOTH providers so one silent blob cannot readmit
    # a DNP the other correctly marked.
    _PLAYED = (f" AND COALESCE({_val('minutes')}, 1) != 0"
               f" AND COALESCE({_val('appearances')}, 1) != 0")

    # stat_key is either a string (single JSON field) or a list (compound: sum fields)
    if isinstance(stat_key, list):
        keys = stat_key
        # SUM with COALESCE so missing fields don't null the whole row
        val_expr = "(" + " + ".join(f"COALESCE({_val(k)}, 0)" for k in keys) + ")"
        # WHERE: at least one key must be non-null (found_any semantics)
        where_clause = "(" + " OR ".join(_present(k) for k in keys) + ")"
    else:
        keys = None
        val_expr = _val(stat_key)
        where_clause = _present(stat_key)

    with closing(_db()) as con:
        con.row_factory = sqlite3.Row
        # Get player info
        player = con.execute(
            "SELECT id, name, team FROM players WHERE id=?", (player_id,)
        ).fetchone()
        if not player:
            return {"error": "player not found", "games": []}

        has_ufcstats = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='player_game_logs_ufcstats'"
        ).fetchone() is not None
        has_usopen = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='player_game_logs_usopen'"
        ).fetchone() is not None
        if league in ("atp", "wta") and has_usopen:
            tennis_value = f"json_extract(stats, '$.{stat_key}')"
            rows = con.execute(
                f"""SELECT game_date, opponent, NULL AS home_away,
                            {tennis_value} AS val
                       FROM player_game_logs_usopen
                      WHERE player_id=? AND league=?
                        AND {tennis_value} IS NOT NULL
                      ORDER BY game_date DESC LIMIT 100""",
                (player_id, league),
            ).fetchall()
        elif league == "ufc" and has_ufcstats:
            # UFCStats is provider-separated because its native fighter/fight
            # ids do not share ESPN's vocabulary. The profile publishes the
            # completed last-five directly; read that table rather than
            # creating duplicate provider rows in player_game_logs_all.
            ufc_value = f"json_extract(stats, '$.{stat_key}')"
            rows = con.execute(
                f"""SELECT game_date, opponent, NULL AS home_away,
                            {ufc_value} AS val
                       FROM player_game_logs_ufcstats
                      WHERE player_id=? AND league='ufc'
                        AND {ufc_value} IS NOT NULL
                      ORDER BY game_date DESC LIMIT 100""",
                (player_id,),
            ).fetchall()
        else:
            # Get game logs with this stat, most recent first. One row per
            # appearance comes from the view, so there is nothing to dedupe here.
            rows = con.execute(
                f"""SELECT game_date, opponent, home_away, {val_expr} AS val
                      FROM player_game_logs_all
                     WHERE player_id=? AND league IN ({league_placeholders})
                       AND {where_clause}{_PLAYED}
                     ORDER BY game_date DESC LIMIT 100""",
                (player_id, *log_leagues)
            ).fetchall()

    if not rows:
        return {
            "player_id": player_id,
            "player": player["name"],
            "team": player["team"] or "",
            "league": league,
            "market": market,
            "line": line,
            "side": side,
            "projection": None,
            "hit_rate": {"l5": 0, "l10": 0, "l20": 0, "season": 0},
            "hit_rate_n": {"l5": 0, "l10": 0, "l20": 0, "season": 0},
            "games": [],
        }

    games = []
    for r in rows:
        try:
            val = float(r["val"]) if r["val"] is not None else 0
        except (ValueError, TypeError):
            val = 0
        hit = val >= line if side == "over" else val <= line
        games.append({
            "date": r["game_date"] or "",
            "value": val,
            "opponent": r["opponent"] or "",
            "home": (r["home_away"] == "home") if r["home_away"] else None,
            "hit": hit,
        })

    def _rate(games_subset, ln):
        if not games_subset: return 0.0
        hits = sum(1 for g in games_subset if g["hit"])
        return round(hits / len(games_subset), 3)

    # Projection: recency-weighted EV from the shared projections module (games is recent-first).
    proj = proj_mod.project_stat([g["value"] for g in games])
    projection = proj["projection"] if proj else None

    return {
        "player_id": player_id,
        "player": player["name"],
        "team": player["team"] or "",
        "league": league,
        "market": market,
        "line": line,
        "side": side,
        "projection": projection,
        # The SAMPLE behind each window, because a window's NAME is not its
        # size. `games[:20]` on a player with three matches is three matches,
        # so L5, L10 and L20 all report the same number and it reads as a
        # twenty-game record. Surfaced on Liga MX first only because those
        # players have three games where an MLS player has forty; the
        # arithmetic was always this.
        "hit_rate_n": {
            "l5": len(games[:5]),
            "l10": len(games[:10]),
            "l20": len(games[:20]),
            "season": len(games),
        },
        "hit_rate": {
            "l5": _rate(games[:5], line),
            "l10": _rate(games[:10], line),
            "l20": _rate(games[:20], line),
            "season": _rate(games, line),
        },
        "games": games,
    }


@router.get("/api/props/stats")
def prop_stats(market: Optional[str] = Query(None),
               league: Optional[str] = Query(None),
               window: int = Query(30, ge=1, le=365, description="Days of history")):
    sql = """SELECT p.market, p.side,
                    COUNT(*) AS total,
                    SUM(CASE WHEN r.hit = 1 THEN 1 ELSE 0 END) AS hits,
                    AVG(p.line) AS avg_line,
                    AVG(r.actual_value) AS avg_actual
             FROM props p
             JOIN prop_results r ON r.prop_id = p.id
             JOIN players pl ON pl.id = p.player_id
             JOIN prop_games pg ON pg.id = p.game_id
             WHERE r.hit IS NOT NULL
               AND p.captured_at >= date('now', ? || ' days')"""
    params = [f"-{window}"]
    if market:
        sql += " AND p.market = ?"
        params.append(market)
    if league:
        # Same rule as /api/props: hit rates for `lcup` are a property of the
        # competition, not of whichever spine each athlete happens to sit in.
        sql += " AND pg.league = ?"
        params.append(league)
    sql += " GROUP BY p.market, p.side ORDER BY total DESC"
    with closing(_db()) as con:
        rows = con.execute(sql, params).fetchall()
    return [{"market": r["market"], "side": r["side"], "total": r["total"],
             "hits": r["hits"], "hit_rate": round(r["hits"] / r["total"], 3) if r["total"] else 0,
             "avg_line": round(r["avg_line"], 1) if r["avg_line"] else None,
             "avg_actual": round(r["avg_actual"], 1) if r["avg_actual"] else None}
            for r in rows]


@router.get("/api/props/slate")
def props_slate(league: Optional[str] = Query(None),
                leagues: Optional[str] = Query(None),
                date: Optional[str] = Query(None),
                game_id: Optional[int] = Query(None),
                summary: bool = Query(False)):
    """Props grouped by game → team → player, for the Slate tab.

    `summary=1` returns games ONLY (matchup / time / league / prop_count, no nested props) so the slate
    list paints instantly instead of shipping every game's full prop book (the fully-nested slate is
    ~1.4MB / 15k props). The client fetches a single game's props on open via `game_id=`."""
    if summary:
        filters = ""
        filter_params = []
        league_sql, league_params = _league_sql("pg.league", league, leagues)
        filters += league_sql
        filter_params.extend(league_params)
        if date:
            filters += " AND pg.date = ?"
            filter_params.append(date)
        else:
            filters += " AND " + _UPCOMING

        # COUNT(p.id) counted the same question twice once a second book
        # priced a line another already had, so the card header said 495
        # while the card itself listed 454. One number, computed two ways,
        # in one endpoint -- count the distinct questions, as the expanded
        # path does when it dedupes on (market, line, side) per player.
        gsql = ("SELECT pg.id AS game_id, pg.home, pg.away, pg.date AS game_date, pg.start_time, "
                "pg.league, COUNT(DISTINCT p.player_id || '|' || p.market || '|' || "
                "p.line || '|' || p.side) AS prop_count "
                "FROM prop_games pg JOIN props p ON p.game_id = pg.id WHERE 1=1" + filters)
        # Order by when the game starts, NOT by `pg.date`. That column carries two
        # conventions (some rows file a 21:30 ET kickoff under the next UTC day), so
        # sorting by it puts a 9:30pm game ahead of a 7:00pm one whenever the two rows
        # disagree. The kickoff instant is the same number for both conventions.
        gsql += (" GROUP BY pg.id HAVING prop_count > 0 ORDER BY " + _KICKOFF
                 + ", pg.home, pg.away")

        base_market = (
            "CASE WHEN instr(p.market, '___') > 0 "
            "THEN substr(p.market, 1, instr(p.market, '___') - 1) ELSE p.market END"
        )
        market_sql = f"""SELECT game_id, market, COUNT(*) AS row_count
                         FROM (
                           SELECT pg.id AS game_id, {base_market} AS market
                           FROM prop_games pg
                           JOIN props p ON p.game_id = pg.id
                           JOIN players pl ON pl.id = p.player_id
                           WHERE 1=1 {filters}
                           GROUP BY pg.id, p.player_id, {base_market}, p.line,
                                    pg.date, pg.home, pg.away
                         ) grouped_markets
                         GROUP BY game_id, market
                         ORDER BY game_id, market"""
        with closing(_db()) as con:
            grows = con.execute(gsql, filter_params).fetchall()
            market_rows = con.execute(market_sql, filter_params).fetchall()
        markets_by_game = {}
        for row in market_rows:
            markets_by_game.setdefault(row["game_id"], []).append({
                "market": row["market"],
                "count": row["row_count"],
            })
        return [{"game_id": r["game_id"], "home": r["home"], "away": r["away"], "date": r["game_date"],
                 "start_time": r["start_time"], "league": r["league"], "prop_count": r["prop_count"],
                 "markets": markets_by_game.get(r["game_id"], []), "players": []} for r in grows]

    sql = """SELECT p.id, p.market, p.line, p.side, p.source, p.odds,
                    pl.id AS player_id, pl.name AS player_name, pl.team AS player_team, pl.league,
                    pg.id AS game_id, pg.home, pg.away, pg.date AS game_date, pg.start_time,
                    pg.league AS game_league
             FROM props p
             JOIN players pl ON pl.id = p.player_id
             JOIN prop_games pg ON pg.id = p.game_id
             WHERE 1=1"""
    params = []
    league_sql, league_params = _league_sql("pg.league", league, leagues)
    sql += league_sql
    params.extend(league_params)
    if game_id is not None:
        sql += " AND pg.id = ?"
        params.append(game_id)
    elif date:
        sql += " AND pg.date = ?"
        params.append(date)
    else:
        # No specific date → the UPCOMING slate: today forward only. This both drops stale past games
        # (e.g. months-old MLB that never pruned) and lets the client show the whole slate grouped by
        # date, Bovada-style. The exact-date path stays for deep links / the date navigator.
        sql += " AND " + _UPCOMING
    sql += " ORDER BY " + _KICKOFF + ", pg.home, pg.away, pl.name, p.market, p.side"
    with closing(_db()) as con:
        rows = con.execute(sql, params).fetchall()

    # Group: game → team → player → props
    games = {}
    for r in rows:
        gkey = f"{r['game_id']}"
        if gkey not in games:
            games[gkey] = {
                "game_id": r["game_id"],
                "home": r["home"],
                "away": r["away"],
                "date": r["game_date"],
                "start_time": r["start_time"],
                # The GAME's league, not the player's. `pl.league` here made the
                # expanded slate label Leagues Cup fixture 1494 `mls`, and the
                # value flipped to `ligamx` with whichever athlete sorted first,
                # while `summary=1` (which reads pg.league) said `lcup`. Same
                # endpoint, two answers for one game. Fourth site of the shape
                # fixed in b8c3bd7/b8a3f60; those were WHERE clauses, this one is
                # the response body, so no filter test could reach it.
                "league": r["game_league"],
                "players": {}
            }
        pkey = r["player_name"]
        if pkey not in games[gkey]["players"]:
            games[gkey]["players"][pkey] = {
                "id": r["player_id"],
                "name": r["player_name"],
                "team": r["player_team"],
                "props": [],
                "_seen": {},
            }
        # One question, one row. Two sources can price the same player at the
        # same line -- Bovada's anytime goal scorer and PrizePicks' `goals 0.5`
        # are the same bet -- and appending both put 146 duplicate `goals 0.5
        # OVER` rows on the Leagues Cup cards the day PrizePicks was added.
        #
        # The priced row wins. That is not a preference between books: a line
        # carrying odds answers strictly more than the same line without them
        # (here all 163 Bovada goal rows have odds and all 217 PrizePicks ones
        # do not). Ranking books by name would be a trust list keyed on a name.
        entry = {
            "market": r["market"],
            "line": r["line"],
            "side": r["side"],
            "source": r["source"],
            "odds": r["odds"],
        }
        seen = games[gkey]["players"][pkey]["_seen"]
        key = (r["market"], r["line"], r["side"])
        held = seen.get(key)
        if held is None:
            seen[key] = entry
            games[gkey]["players"][pkey]["props"].append(entry)
        elif held["odds"] is None and r["odds"] is not None:
            held.update(entry)

    # Convert to list sorted by date
    result = sorted(games.values(), key=lambda g: g["date"])
    for g in result:
        g["players"] = sorted(g["players"].values(), key=lambda p: p["name"])
        for player in g["players"]:
            player.pop("_seen", None)
        g["prop_count"] = sum(len(p["props"]) for p in g["players"])

    return result


@router.get("/api/props/player/{player_id}/performance")
def player_performance(player_id: int, market: Optional[str] = Query(None)):
    """EMA-weighted hit rates for a player, grouped by market+side.

    Weights: last 5 games = 0.5, next 5 = 0.25, next 10 = 0.15, rest = 0.1.
    """
    sql = """SELECT p.market, p.side, p.line, r.actual_value, r.hit, r.settled_at
             FROM props p
             JOIN prop_results r ON r.prop_id = p.id
             WHERE p.player_id = ? AND r.hit IS NOT NULL"""
    params = [player_id]
    if market:
        sql += " AND p.market = ?"
        params.append(market)
    sql += " ORDER BY r.settled_at DESC LIMIT 200"
    with closing(_db()) as con:
        rows = con.execute(sql, params).fetchall()

    # Group by market+side, compute EMA buckets
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        key = f"{r['market']}|{r['side']}"
        groups[key].append({"hit": r["hit"], "actual": r["actual_value"], "line": r["line"]})

    result = []
    for key, entries in groups.items():
        market_name, side = key.split("|", 1)
        total = len(entries)
        if total == 0:
            continue

        # EMA buckets
        def ema(entries, start, end, weight):
            bucket = entries[start:end]
            if not bucket:
                return None
            return round(sum(1 for e in bucket if e["hit"]) / len(bucket), 3)

        l5 = ema(entries, 0, 5, 0.5)
        l10 = ema(entries, 0, 10, 0.25) if total >= 5 else None
        l20 = ema(entries, 0, 20, 0.15) if total >= 10 else None
        season = ema(entries, 0, total, 0.1)

        # Weighted composite
        parts = []
        if l5 is not None:
            parts.append((l5, 0.5))
        if l10 is not None and total >= 10:
            parts.append((l10, 0.25))
        if l20 is not None and total >= 20:
            parts.append((l20, 0.15))
        parts.append((season, 0.1))
        total_weight = sum(w for _, w in parts)
        weighted = round(sum(r * w for r, w in parts) / total_weight, 3) if total_weight > 0 else season

        # Trend: compare L5 to L20
        trend = "→"
        if l5 is not None and l20 is not None:
            diff = l5 - l20
            if diff > 0.1:
                trend = "↑"
            elif diff < -0.1:
                trend = "↓"

        result.append({
            "market": market_name,
            "side": side,
            "total_settled": total,
            "hit_rate_l5": l5,
            "hit_rate_l10": l10,
            "hit_rate_l20": l20,
            "hit_rate_season": season,
            "hit_rate_weighted": weighted,
            "trend": trend,
        })

    result.sort(key=lambda x: x["total_settled"], reverse=True)
    return {"player_id": player_id, "performance": result}


def _link_or_fold(con, game_id, league, espn_id):
    """Attach `espn_id` to `game_id`, folding into the row that already holds it.

    `ux_prop_games_event` makes (league, espn_event_id) unique, so this UPDATE raises
    IntegrityError exactly when another row IS this event -- the day-early twin the
    ingest created a moment ago because prop_games.date is a UTC first pitch while the
    board is keyed on the local one.

    That is not an error to swallow. The caller used to wrap the UPDATE in
    `except Exception: pass`, which under the new index leaves the twin sitting there
    permanently UNLINKED: no event id, so settlement never resolves a gamePk for it and
    every prop on it is stranded. Silent, and indistinguishable from a game ESPN has not
    published yet.

    So fold instead, the same way link_prop_games does on its nightly pass -- repoint the
    props onto the row that already carries the id and drop the twin. Returns the id of
    the row that survived.
    """
    try:
        con.execute("UPDATE prop_games SET espn_event_id=? WHERE id=?", (espn_id, game_id))
        return game_id
    except sqlite3.IntegrityError:
        holder = con.execute(
            "SELECT id FROM prop_games WHERE league=? AND espn_event_id=? AND id!=?",
            (league, espn_id, game_id)).fetchone()
        if not holder:
            raise
        keep = holder["id"] if hasattr(holder, "keys") else holder[0]
        return fold_prop_game(con, game_id, keep)


def _roster_league_for_ingest(con, league: str, team: str) -> str:
    """The spine allowed to own this player, which is not always the competition.

    A cross-league tournament is filed under its own competition key, so a Leagues
    Cup game is `lcup` while the athletes playing it are `mls` and `ligamx`. The
    resolver matches on `players.league`, and `players WHERE league='lcup'` has
    always held ZERO rows -- so every prop posted under `lcup` resolved against an
    empty spine and was rejected. Measured 2026-08-25: 370 of 370 Bovada Leagues
    Cup props, "REJECTED all 370 -- nothing in `players` matched".

    This is the same defect `0746e83` fixed inside `ingest_rotowire_props.py`, at a
    second site. That fix does not reach here: this is the HTTP ingest endpoint, a
    different path with its own resolver, which the Bovada scraper posts to.

    Routed by the club's own membership rather than a hand-written club list, and
    AMBIGUOUS FAILS CLOSED: `ATL` is Atlanta United in MLS and Atlante in Liga MX,
    so a code naming two spines resolves to neither and the athlete goes to the
    review queue. Widening `mls` to swallow the tournament is the shadow-player
    defect this whole route exists to avoid.
    """
    if league != "lcup" or not team:
        return league
    rows = con.execute(
        "SELECT DISTINCT league FROM players WHERE team=? AND league IN ('mls','ligamx')",
        (team.strip().upper(),)).fetchall()
    if len(rows) == 1:
        return rows[0][0]
    return league


@router.post("/api/props/ingest")
def ingest_props(batch: PropIngest):
    """Ingest a batch of props for one game. Creates player/game rows as needed."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        # ensure game row — match on league+date+home+away (espn_event_id is optional)
        if batch.espn_event_id:
            cur = con.execute(
                "SELECT id, espn_event_id, start_time FROM prop_games WHERE espn_event_id=? AND league=?",
                (batch.espn_event_id, batch.league))
        else:
            cur = con.execute(
                "SELECT id, espn_event_id, start_time FROM prop_games WHERE league=? AND date=? AND home=? AND away=?",
                (batch.league, batch.date, batch.home, batch.away))
        game_row = cur.fetchone()
        if not game_row:
            cur = con.execute(
                "INSERT INTO prop_games(league,date,home,away,espn_event_id,start_time) VALUES(?,?,?,?,?,?)",
                (batch.league, batch.date, batch.home, batch.away,
                 batch.espn_event_id, batch.start_time))
            game_id = cur.lastrowid
            # Try to link espn_event_id for newly created games
            if not batch.espn_event_id:
                try:
                    from link_prop_games import link_prop_game
                    import espn_client as _espn
                    new_row = con.execute("SELECT id, league, date, home, away FROM prop_games WHERE id=?", (game_id,)).fetchone()
                    espn_games = _espn.games(batch.league, batch.date)
                    espn_id = link_prop_game(con, new_row, espn_games)
                    if espn_id:
                        game_id = _link_or_fold(con, game_id, batch.league, espn_id)
                except Exception:
                    pass
        else:
            game_id = game_row["id"]
            from link_prop_games import apply_start_time
            apply_start_time(con, game_id, batch.start_time, game_row["start_time"],
                             label="%s @ %s" % (batch.away, batch.home))
            # If existing game has no espn_event_id, try to link it now
            if not game_row["espn_event_id"] and not batch.espn_event_id:
                try:
                    from link_prop_games import link_prop_game
                    import espn_client as _espn
                    espn_games = _espn.games(batch.league, batch.date)
                    espn_id = link_prop_game(con, game_row, espn_games)
                    if espn_id:
                        game_id = _link_or_fold(con, game_id, batch.league, espn_id)
                except Exception:
                    pass  # crosswalk is best-effort; don't block ingest
        ingested = 0
        refreshed = 0
        unresolved = 0
        for p in batch.props:
            # Resolve player via identity spine (NEVER silently create)
            roster_league = _roster_league_for_ingest(con, batch.league, p.get("team", ""))
            player_id, confidence = _resolve_player_for_ingest(
                con, p["player_name"], p.get("team", ""), roster_league,
                source=p.get("source", "props"), game_id=game_id)
            if player_id is None:
                unresolved += 1
                continue  # logged to unresolved_players by the resolver
            odds_val = p.get("odds")
            odds_int = None
            if odds_val is not None:
                try:
                    odds_int = int(odds_val)
                except (ValueError, TypeError):
                    odds_int = 100 if str(odds_val).upper() == "EVEN" else None

            # Refresh the existing row rather than inserting a second one.
            #
            # `props` has no UNIQUE constraint, and this endpoint used to INSERT
            # unconditionally, so every scrape of an unchanged board wrote a whole new copy
            # of it. The scrapers run on 30-minute timers. Measured on dev 2026-08-16:
            # 47,827 (game_id, player_id, market, line, side, source) groups holding more
            # than one row. Nothing errored -- the board reads "latest per key" and looked
            # right, while every hit-rate denominator counted the same prop once per scrape.
            #
            # `_wc_direct_ingest` and `_ufc_direct_ingest` in bovada_scraper.py have always
            # done this check; the API path is the one that did not, which is why the two
            # leagues that bypass the API are the two that stayed clean. Same key as
            # ix_props_regrade, so the lookup is indexed.
            source = p.get("source", "manual")
            existing = con.execute(
                "SELECT id FROM props WHERE game_id=? AND player_id=? AND market=? "
                "AND line=? AND side=? AND source IS ?",
                (game_id, player_id, p["market"], p["line"], p["side"], source)).fetchone()
            if existing:
                if odds_int is None:
                    con.execute("UPDATE props SET captured_at=? WHERE id=?", (now, existing["id"]))
                else:
                    con.execute(
                        "UPDATE props SET captured_at=?,odds=?,odds_captured_at=? WHERE id=?",
                        (now, odds_int, now, existing["id"]))
                refreshed += 1
            elif odds_int is not None:
                con.execute(
                    "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at,odds,odds_captured_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (game_id, player_id, p["market"], p["line"], p["side"], source, now, odds_int, now))
                ingested += 1
            else:
                con.execute(
                    "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at) VALUES(?,?,?,?,?,?,?)",
                    (game_id, player_id, p["market"], p["line"], p["side"], source, now))
                ingested += 1
        con.commit()
    return {"status": "ok", "game_id": game_id, "ingested": ingested,
            "refreshed": refreshed, "unresolved": unresolved}


@router.post("/api/capture-odds")
def capture_odds(batch: CaptureOddsIn):
    """Write prop_odds_snapshots rows for existing props matched by (player_id, market, line, side).
    Does NOT create new props. Paired odds get de_vig_status='paired', singles get 'single'.
    Line-moved props are logged and skipped."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    snapshots = 0
    paired = 0
    single = 0
    skipped_line = 0
    unmatched = 0

    with closing(_db()) as con:
        # Build a map of existing props: (player_id, market, line, side) -> prop_id + existing odds_opp
        existing = {}
        for r in con.execute(
            "SELECT p.id, p.player_id, p.market, p.line, p.side, p.odds "
            "FROM props p JOIN players pl ON pl.id=p.player_id WHERE pl.league=?",
            (batch.league,)
        ).fetchall():
            key = (r["player_id"], r["market"], round(r["line"], 1), r["side"])
            existing[key] = {"prop_id": r["id"], "odds": r["odds"]}

        # Group scraped props by (player_name, market, line) so we can pair over/under
        by_market = {}
        for p in batch.props:
            pname = p.get("player_name", "")
            mkt = p.get("market", "")
            line = round(float(p.get("line", 0) or 0), 1)
            side = p.get("side", "")
            odds_val = p.get("odds")
            if not pname or not mkt or odds_val is None:
                continue
            try:
                odds_int = int(odds_val)
            except (ValueError, TypeError):
                odds_int = 100 if str(odds_val).upper() == "EVEN" else None
            if odds_int is None:
                continue

            # Resolve player_id
            player_id, confidence = _resolve_player_for_ingest(
                con, pname, p.get("team", ""), batch.league, source="bovada")
            if player_id is None:
                continue

            mkey = (player_id, mkt, line)
            if mkey not in by_market:
                by_market[mkey] = {}
            by_market[mkey][side] = {"player_id": player_id, "odds": odds_int}

        # Write snapshots
        for mkey, sides in by_market.items():
            player_id, mkt, line = mkey
            over_data = sides.get("over")
            under_data = sides.get("under")

            for s, sdata in [("over", over_data), ("under", under_data)]:
                if sdata is None:
                    continue
                prop_key = (player_id, mkt, line, s)
                prop_info = existing.get(prop_key)

                if prop_info is None:
                    # Try to find with looser line matching (line changed)
                    unmatched += 1
                    continue

                # Check line match
                opp_data = under_data if s == "over" else over_data
                odds_opp = opp_data["odds"] if opp_data else None
                de_vig = "paired" if odds_opp is not None else "single"

                # Odds-value-change dedup: skip if odds haven't moved since last snapshot
                last = con.execute(
                    "SELECT odds, odds_opp FROM prop_odds_snapshots WHERE prop_id=? AND side=? ORDER BY captured_at DESC LIMIT 1",
                    (prop_info["prop_id"], s)).fetchone()
                if last and last["odds"] == sdata["odds"] and (last["odds_opp"] or None) == odds_opp:
                    continue  # line didn't move, skip duplicate poll

                con.execute(
                    "INSERT OR IGNORE INTO prop_odds_snapshots(prop_id, side, odds, odds_opp, captured_at, de_vig_status) VALUES(?,?,?,?,?,?)",
                    (prop_info["prop_id"], s, sdata["odds"], odds_opp, now, de_vig))
                snapshots += 1
                if de_vig == "paired":
                    paired += 1
                else:
                    single += 1

        con.commit()

    return {
        "status": "ok",
        "snapshots": snapshots,
        "paired": paired,
        "single": single,
        "skipped_line": skipped_line,
        "unmatched": unmatched,
    }
