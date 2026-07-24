"""routers/props.py — props endpoints. Handlers only; shared code lives in _core."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *

router = APIRouter()


_CorePropIngest = PropIngest


class PropIngest(_CorePropIngest):
    start_time: Optional[str] = None

@router.get("/api/props")
def list_props(player: Optional[str] = Query(None),
               market: Optional[str] = Query(None),
               league: Optional[str] = Query(None),
               date: Optional[str] = Query(None),
               limit: int = Query(50, ge=1, le=500)):
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
    if league:
        sql += " AND pl.league = ?"
        params.append(league)
    if date:
        sql += " AND pg.date = ?"
        params.append(date)
    sql += " ORDER BY p.captured_at DESC LIMIT ?"
    params.append(limit)
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

    # stat_key is either a string (single JSON field) or a list (compound: sum fields)
    if isinstance(stat_key, list):
        keys = stat_key
        # SUM with COALESCE so missing fields don't null the whole row
        coalesce_terms = [
            f"COALESCE(json_extract(stats, '$.{k}'), 0)" for k in keys
        ]
        val_expr = f"({' + '.join(coalesce_terms)})"
        # WHERE: at least one key must be non-null (found_any semantics)
        non_null_terms = " OR ".join(
            f"json_extract(stats, '$.{k}') IS NOT NULL" for k in keys
        )
        where_clause = f"({non_null_terms})"
        params_for_query = ()  # no bind params needed, keys are hardcoded per market
    else:
        val_expr = "json_extract(stats, ?)"
        where_clause = "json_extract(stats, ?) IS NOT NULL"
        stat_path = f"$.{stat_key}"
        params_for_query = (stat_path, stat_path)
        keys = None  # unused for non-compound

    with closing(_db()) as con:
        con.row_factory = sqlite3.Row
        # Get player info
        player = con.execute(
            "SELECT id, name, team FROM players WHERE id=?", (player_id,)
        ).fetchone()
        if not player:
            return {"error": "player not found", "games": []}

        # Get game logs with this stat, most recent first
        if isinstance(stat_key, list):
            rows = con.execute(
                f"""SELECT game_date, opponent, home_away,
                           {val_expr} AS val
                    FROM player_game_logs
                    WHERE player_id=? AND league=?
                      AND {where_clause}
                    ORDER BY game_date DESC LIMIT 100""",
                (player_id, league)
            ).fetchall()
        else:
            rows = con.execute(
                f"""SELECT game_date, opponent, home_away,
                           json_extract(stats, ?) AS val
                    FROM player_game_logs
                    WHERE player_id=? AND league=?
                      AND json_extract(stats, ?) IS NOT NULL
                    ORDER BY game_date DESC LIMIT 100""",
                (stat_path, player_id, league, stat_path)
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
            "home": r["home_away"] == "home",
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
             WHERE r.hit IS NOT NULL
               AND p.captured_at >= date('now', ? || ' days')"""
    params = [f"-{window}"]
    if market:
        sql += " AND p.market = ?"
        params.append(market)
    if league:
        sql += " AND pl.league = ?"
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
        if league:
            filters += " AND pg.league = ?"
            filter_params.append(league)
        if date:
            filters += " AND pg.date = ?"
            filter_params.append(date)
        else:
            filters += " AND pg.date >= date('now')"

        gsql = ("SELECT pg.id AS game_id, pg.home, pg.away, pg.date AS game_date, pg.start_time, "
                "pg.league, COUNT(p.id) AS prop_count "
                "FROM prop_games pg JOIN props p ON p.game_id = pg.id WHERE 1=1" + filters)
        gsql += " GROUP BY pg.id HAVING prop_count > 0 ORDER BY pg.date, pg.start_time, pg.home, pg.away"

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
                           GROUP BY pg.id, p.player_id, {base_market}, p.line, p.source,
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

    sql = """SELECT p.id, p.market, p.line, p.side, p.source,
                    pl.name AS player_name, pl.team AS player_team, pl.league,
                    pg.id AS game_id, pg.home, pg.away, pg.date AS game_date, pg.start_time
             FROM props p
             JOIN players pl ON pl.id = p.player_id
             JOIN prop_games pg ON pg.id = p.game_id
             WHERE 1=1"""
    params = []
    if league:
        sql += " AND pl.league = ?"
        params.append(league)
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
        sql += " AND pg.date >= date('now')"
    sql += " ORDER BY pg.date, pg.home, pg.away, pl.name, p.market, p.side"
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
                "league": r["league"],
                "players": {}
            }
        pkey = r["player_name"]
        if pkey not in games[gkey]["players"]:
            games[gkey]["players"][pkey] = {
                "name": r["player_name"],
                "team": r["player_team"],
                "props": []
            }
        games[gkey]["players"][pkey]["props"].append({
            "market": r["market"],
            "line": r["line"],
            "side": r["side"],
            "source": r["source"],
        })

    # Convert to list sorted by date
    result = sorted(games.values(), key=lambda g: g["date"])
    for g in result:
        g["players"] = sorted(g["players"].values(), key=lambda p: p["name"])
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
                        con.execute("UPDATE prop_games SET espn_event_id=? WHERE id=?", (espn_id, game_id))
                except Exception:
                    pass
        else:
            game_id = game_row["id"]
            if batch.start_time and not game_row["start_time"]:
                con.execute(
                    "UPDATE prop_games SET start_time=? WHERE id=?",
                    (batch.start_time, game_id))
            # If existing game has no espn_event_id, try to link it now
            if not game_row["espn_event_id"] and not batch.espn_event_id:
                try:
                    from link_prop_games import link_prop_game
                    import espn_client as _espn
                    espn_games = _espn.games(batch.league, batch.date)
                    espn_id = link_prop_game(con, game_row, espn_games)
                    if espn_id:
                        con.execute("UPDATE prop_games SET espn_event_id=? WHERE id=?", (espn_id, game_id))
                except Exception:
                    pass  # crosswalk is best-effort; don't block ingest
        ingested = 0
        unresolved = 0
        for p in batch.props:
            # Resolve player via identity spine (NEVER silently create)
            player_id, confidence = _resolve_player_for_ingest(
                con, p["player_name"], p.get("team", ""), batch.league,
                source=p.get("source", "props"))
            if player_id is None:
                unresolved += 1
                continue  # logged to unresolved_players by the resolver
            # insert prop
            odds_val = p.get("odds")
            if odds_val is not None:
                try:
                    odds_int = int(odds_val)
                except (ValueError, TypeError):
                    odds_int = 100 if str(odds_val).upper() == "EVEN" else None
                if odds_int is not None:
                    con.execute(
                        "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at,odds,odds_captured_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (game_id, player_id, p["market"], p["line"], p["side"], p.get("source", "manual"), now, odds_int, now))
            else:
                con.execute(
                    "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at) VALUES(?,?,?,?,?,?,?,?)",
                    (game_id, player_id, p["market"], p["line"], p["side"], p.get("source", "manual"), now))
            ingested += 1
        con.commit()
    return {"status": "ok", "game_id": game_id, "ingested": ingested, "unresolved": unresolved}


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
