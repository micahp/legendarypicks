#!/usr/bin/env python3
"""sports_service.py — unified multi-league sports API (ESPN-backed) + prediction store.

ONE service. Replaces the old sportsipy-based `sports_service` and the NBA-only `nba_service`
(now a deprecation stub). All data flows through espn_client (free, reliable, every league).

What changed from the original:
  - real data for ALL leagues (was: dead sportsipy + a 1-game hardcoded fixture fallback)
  - predictions persisted to SQLite and graded against REAL finals (was: in-memory list vs fixture)
  - /strength endpoint: teams ranked by win% / differential / form — the quality prior shared
    with the prediction-market trading strategy (its only unfalsified edge: buy undervalued QUALITY)
"""
import os, sqlite3, datetime as dt
from contextlib import closing
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import espn_client as espn

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
ALLOWED_ORIGINS = os.environ.get("LP_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3007").split(",")

app = FastAPI(title="Legendary Picks Sports API", description="Multi-league sports data (ESPN)", version="2.0.0")
print(f"DEBUG: espn_client leagues: {sorted(espn.LEAGUES)}")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


def _db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def _init_db():
    with closing(_db()) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS predictions(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          league TEXT NOT NULL, game_id TEXT NOT NULL, predicted_winner TEXT NOT NULL,
          created_at TEXT NOT NULL, correct INTEGER);
        CREATE TABLE IF NOT EXISTS strength_snap(
          captured_at TEXT NOT NULL, league TEXT NOT NULL, abbrev TEXT NOT NULL,
          win_pct REAL, differential REAL, wins INTEGER, losses INTEGER);
        CREATE TABLE IF NOT EXISTS roster_snap(
          captured_at TEXT NOT NULL, league TEXT NOT NULL, team_abbrev TEXT NOT NULL,
          player_id TEXT NOT NULL, name TEXT, jersey TEXT, position TEXT);
        CREATE TABLE IF NOT EXISTS team_game_stats(
          league TEXT NOT NULL, game_id TEXT NOT NULL, captured_at TEXT NOT NULL,
          team_abbrev TEXT NOT NULL, home_away TEXT NOT NULL,
          fgm_fga TEXT, fg_pct REAL, tpm_tpa TEXT, tp_pct REAL,
          ftm_fta TEXT, ft_pct REAL, rebounds INTEGER, off_rebounds INTEGER,
          def_rebounds INTEGER, assists INTEGER, steals INTEGER, blocks INTEGER,
          turnovers INTEGER, fouls INTEGER, pts_off_to INTEGER,
          fast_break_pts INTEGER, pts_in_paint INTEGER, largest_lead INTEGER,
          lead_changes INTEGER, lead_pct REAL,
          shots INTEGER, blocked_shots INTEGER, hits INTEGER,
          takeaways INTEGER, giveaways INTEGER, faceoffs_won INTEGER,
          faceoff_pct REAL, powerplay_goals INTEGER, powerplay_opps INTEGER,
          powerplay_pct REAL, shorthanded_goals INTEGER,
          penalties INTEGER, penalty_min INTEGER);
        CREATE TABLE IF NOT EXISTS scoring_plays(
          league TEXT NOT NULL, game_id TEXT NOT NULL, play_id TEXT NOT NULL,
          captured_at TEXT NOT NULL, period INTEGER, period_disp TEXT,
          clock TEXT, away_score INTEGER, home_score INTEGER,
          team_abbrev TEXT, scorer_name TEXT, play_text TEXT, play_type TEXT);
        CREATE TABLE IF NOT EXISTS game_context(
          league TEXT NOT NULL, game_id TEXT NOT NULL PRIMARY KEY,
          captured_at TEXT NOT NULL, home_team TEXT, away_team TEXT,
          venue_name TEXT, venue_city TEXT, attendance INTEGER,
          officials TEXT);
        -- Phase 2: prop-outcome data engine
        CREATE TABLE IF NOT EXISTS players(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL, team TEXT, league TEXT NOT NULL,
          espn_id TEXT, mlbam_id INTEGER, nfl_gsis_id TEXT,
          nhl_id INTEGER, nba_id INTEGER,
          active INTEGER DEFAULT 1, position TEXT, updated_at TEXT,
          UNIQUE(espn_id, league));
        CREATE TABLE IF NOT EXISTS prop_games(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          league TEXT NOT NULL, date TEXT NOT NULL,
          home TEXT, away TEXT, espn_event_id TEXT,
          final_home INTEGER, final_away INTEGER);
        CREATE TABLE IF NOT EXISTS props(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          game_id INTEGER REFERENCES prop_games(id),
          player_id INTEGER REFERENCES players(id),
          market TEXT NOT NULL, line REAL NOT NULL, side TEXT NOT NULL,
          source TEXT, captured_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS prop_results(
          prop_id INTEGER PRIMARY KEY REFERENCES props(id),
          actual_value REAL, hit INTEGER, settled_at TEXT);
        CREATE TABLE IF NOT EXISTS player_stats(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          player_name TEXT NOT NULL, league TEXT NOT NULL, team TEXT,
          season INTEGER, games INTEGER,
          pts REAL, reb REAL, ast REAL, stl REAL, blk REAL, tov REAL,
          fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER,
          ftm INTEGER, fta INTEGER, minutes REAL,
          ts_pct REAL, source TEXT,
          UNIQUE(player_name, league, season));
        """)
        con.commit()


_init_db()


class PredictionIn(BaseModel):
    league: str
    game_id: str
    predicted_winner: str   # team abbreviation, e.g. "MIL"


@app.get("/")
def root():
    return {"service": "Legendary Picks Sports API", "version": "2.0.0",
            "source": "ESPN", "leagues": sorted(espn.LEAGUES)}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/{league}/games")
def get_games(league: str, date: Optional[str] = Query(None, description="YYYY-MM-DD (default today)")):
    if league.lower() == "cod":
        # Call of Duty League — real data from official CDL schedule page
        import cdl_client
        return cdl_client.get_matches(date_str=date)
    try:
        games = espn.games(league, date)
    except ValueError as e:
        raise HTTPException(404, str(e))
    # ── finished-game final score: DB-first, no ESPN on the request path ──
    # For a post-state game, prefer OUR captured final (scoring_plays) over the
    # scoreboard tick. DB-only — no per-request ESPN calls. If the DB has no record
    # (we never snapshotted it), leave the scoreboard score as-is. An occasional
    # out-of-band job can reconcile DB vs ESPN; the page request never does.
    lg = league.lower()
    for g in games:
        if g.get("state") != "post":
            continue
        final = _final_score_from_db(lg, g["game_id"])
        if final:
            if g.get("home"):
                g["home"]["score"] = final["home"]
            if g.get("away"):
                g["away"]["score"] = final["away"]
    return JSONResponse(content=games, headers={"Cache-Control": "public, max-age=30"})


@app.get("/api/{league}/strength")
def get_strength(league: str):
    """Teams ranked by quality (win%, differential, streak, last-10) — the selection prior."""
    try:
        rows = espn.team_strength(league)
    except ValueError as e:
        raise HTTPException(404, str(e))
    _snapshot_strength(league.lower(), rows)
    return rows


@app.get("/api/{league}/strength/{team}")
def get_team_strength(league: str, team: str):
    try:
        m = espn.team_strength_map(league)
    except ValueError as e:
        raise HTTPException(404, str(e))
    row = m.get(team.upper())
    if not row:
        raise HTTPException(404, f"team {team!r} not found in {league}")
    return row


@app.get("/api/{league}/boxscore/{game_id}")
def get_boxscore(league: str, game_id: str):
    try:
        result = espn.boxscore(league, game_id)
        # Persist team stats + scoring plays + game context (NBA+NHL only)
        lg = league.lower()
        if lg in ("nba", "nhl"):
            try: _snapshot_boxscore_full(lg, game_id)
            except Exception: pass  # snapshot failure must not break the API response
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/{league}/game/{game_id}/detail")
def get_game_detail(league: str, game_id: str):
    """NBA/NHL game detail: persisted team stats, scoring timeline, venue, and strength priors."""
    lg = league.lower()
    if lg not in ("nba", "nhl"):
        raise HTTPException(400, "game detail only available for NBA and NHL")
    out = {"game_id": game_id, "league": lg,
           "team_stats": [], "scoring_plays": [], "context": None, "strength": {},
           "final_score": None}
    # ── final score from OUR DB (scoring_plays); no ESPN on the request path ──
    try:
        out["final_score"] = _final_score_from_db(lg, game_id)
    except Exception:
        pass
    with closing(_db()) as con:
        # Team stats
        for r in con.execute(
            "SELECT * FROM team_game_stats WHERE league=? AND game_id=? ORDER BY home_away",
            (lg, game_id)
        ).fetchall():
            out["team_stats"].append({
                "team_abbrev": r["team_abbrev"], "home_away": r["home_away"],
                "fgm_fga": r["fgm_fga"], "fg_pct": r["fg_pct"],
                "tpm_tpa": r["tpm_tpa"], "tp_pct": r["tp_pct"],
                "ftm_fta": r["ftm_fta"], "ft_pct": r["ft_pct"],
                "rebounds": r["rebounds"], "off_rebounds": r["off_rebounds"],
                "def_rebounds": r["def_rebounds"], "assists": r["assists"],
                "steals": r["steals"], "blocks": r["blocks"],
                "turnovers": r["turnovers"], "fouls": r["fouls"],
                "fast_break_pts": r["fast_break_pts"], "pts_in_paint": r["pts_in_paint"],
                "largest_lead": r["largest_lead"],
                "shots": r["shots"], "blocked_shots": r["blocked_shots"],
                "hits": r["hits"], "takeaways": r["takeaways"],
                "giveaways": r["giveaways"], "faceoffs_won": r["faceoffs_won"],
                "faceoff_pct": r["faceoff_pct"],
                "powerplay_goals": r["powerplay_goals"], "powerplay_opps": r["powerplay_opps"],
                "penalties": r["penalties"], "penalty_min": r["penalty_min"],
            })
        # Scoring plays
        for r in con.execute(
            "SELECT * FROM scoring_plays WHERE league=? AND game_id=? ORDER BY period, clock",
            (lg, game_id)
        ).fetchall():
            out["scoring_plays"].append({
                "period": r["period"], "period_disp": r["period_disp"],
                "clock": r["clock"], "away_score": r["away_score"],
                "home_score": r["home_score"], "team_abbrev": r["team_abbrev"],
                "play_text": r["play_text"], "play_type": r["play_type"],
            })
        # Game context
        ctx = con.execute(
            "SELECT * FROM game_context WHERE league=? AND game_id=?",
            (lg, game_id)
        ).fetchone()
        if ctx:
            import json
            out["context"] = {
                "venue_name": ctx["venue_name"], "venue_city": ctx["venue_city"],
                "attendance": ctx["attendance"],
                "officials": json.loads(ctx["officials"] or "[]"),
                "home_team": ctx["home_team"], "away_team": ctx["away_team"],
            }
        # Strength priors for both teams
        for ab in [out["context"]["home_team"], out["context"]["away_team"]] if out["context"] else []:
            if not ab: continue
            try:
                out["strength"][ab] = espn.team_strength_map(lg).get(ab)
            except Exception:
                pass
    return out


@app.get("/api/{league}/team/{team}/roster")
def get_roster(league: str, team: str):
    try:
        result = espn.roster(league, team)
        # Persist roster (NBA+NHL only)
        lg = league.lower()
        if lg in ("nba", "nhl"):
            try: _snapshot_rosters(lg, team.upper(), result)
            except Exception: pass
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/predictions")
def submit_prediction(pred: PredictionIn):
    league = pred.league.lower()
    if league not in espn.LEAGUES:
        raise HTTPException(404, f"unsupported league {pred.league!r}")
    correct = _evaluate(league, pred.game_id, pred.predicted_winner)
    with closing(_db()) as con:
        cur = con.execute(
            "INSERT INTO predictions(league,game_id,predicted_winner,created_at,correct) VALUES(?,?,?,?,?)",
            (league, pred.game_id, pred.predicted_winner.upper(),
             dt.datetime.now(dt.timezone.utc).isoformat(),
             None if correct is None else int(correct)))
        con.commit()
        pid = cur.lastrowid
    return {"id": pid, "league": league, "game_id": pred.game_id,
            "predicted_winner": pred.predicted_winner.upper(), "correct": correct}


@app.get("/api/predictions")
def list_predictions():
    out = []
    with closing(_db()) as con:
        for r in con.execute("SELECT * FROM predictions ORDER BY id").fetchall():
            correct = r["correct"]
            if correct is None:                     # re-grade: the game may have finished since
                correct = _evaluate(r["league"], r["game_id"], r["predicted_winner"])
                if correct is not None:
                    con.execute("UPDATE predictions SET correct=? WHERE id=?", (int(correct), r["id"]))
            out.append({"id": r["id"], "league": r["league"], "game_id": r["game_id"],
                        "predicted_winner": r["predicted_winner"], "correct": correct})
        con.commit()
    accuracy = None
    graded = [p for p in out if p["correct"] is not None]
    if graded:
        accuracy = round(sum(1 for p in graded if p["correct"]) / len(graded), 4)
    return {"predictions": out, "graded": len(graded), "accuracy": accuracy}


# ── Phase 2: prop-outcome data engine ──────────────────────────────

@app.get("/api/players/search")
def search_players(q: str = Query("", description="Search query")):
    if not q or len(q) < 2:
        return []
    with closing(_db()) as con:
        rows = con.execute(
            "SELECT DISTINCT id, name, team, league FROM players WHERE name LIKE ? LIMIT 20",
            (f"%{q}%",)
        ).fetchall()
    return [{"id": r["id"], "name": r["name"], "team": r["team"], "league": r["league"]} for r in rows]


@app.get("/api/props")
def list_props(player: Optional[str] = Query(None),
               market: Optional[str] = Query(None),
               league: Optional[str] = Query(None),
               date: Optional[str] = Query(None),
               limit: int = Query(50, ge=1, le=500)):
    sql = """SELECT p.id, p.market, p.line, p.side, p.source, p.captured_at,
                    pl.name AS player_name, pl.team AS player_team, pl.league,
                    r.actual_value, r.hit, r.settled_at
             FROM props p
             JOIN players pl ON pl.id = p.player_id
             LEFT JOIN prop_results r ON r.prop_id = p.id
             WHERE 1=1"""
    params = []
    if player:
        sql += " AND pl.name LIKE ?"
        params.append(f"%{player}%")
    if market:
        sql += " AND p.market = ?"
        params.append(market)
    if league:
        sql += " AND pl.league = ?"
        params.append(league)
    if date:
        sql += " AND p.captured_at >= ? AND p.captured_at < ?"
        params.extend([f"{date}T00:00:00", f"{date}T23:59:59"])
    sql += " ORDER BY p.captured_at DESC LIMIT ?"
    params.append(limit)
    with closing(_db()) as con:
        rows = con.execute(sql, params).fetchall()
    return [{"id": r["id"], "market": r["market"], "line": r["line"], "side": r["side"],
             "source": r["source"], "captured_at": r["captured_at"],
             "player_name": r["player_name"], "player_team": r["player_team"],
             "league": r["league"], "actual_value": r["actual_value"],
             "hit": bool(r["hit"]) if r["hit"] is not None else None,
             "settled_at": r["settled_at"]} for r in rows]


@app.get("/api/props/player/{player_id}/history")
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


@app.get("/api/props/stats")
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


# ── Slate: props grouped by game ──────────────────────────────────

@app.get("/api/props/slate")
def props_slate(league: Optional[str] = Query(None),
                date: Optional[str] = Query(None)):
    """Return props grouped by game → team → player. For the Slate tab."""
    sql = """SELECT p.id, p.market, p.line, p.side, p.source,
                    pl.name AS player_name, pl.team AS player_team, pl.league,
                    pg.id AS game_id, pg.home, pg.away, pg.date AS game_date
             FROM props p
             JOIN players pl ON pl.id = p.player_id
             JOIN prop_games pg ON pg.id = p.game_id
             WHERE 1=1"""
    params = []
    if league:
        sql += " AND pl.league = ?"
        params.append(league)
    if date:
        sql += " AND pg.date = ?"
        params.append(date)
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


# ── Performance: EMA-weighted hit rates ────────────────────────────

@app.get("/api/props/player/{player_id}/performance")
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


# ── Name normalization (fixes Bobby Witt Jr. / accent / punct mismatches) ──

import re, unicodedata

def _normalize_name(name: str) -> str:
    """Normalize player name for matching: lowercase, strip punctuation + suffixes + accents."""
    if not name:
        return ""
    n = name.lower().strip()
    # Strip suffixes
    n = re.sub(r'\b(jr\.?|sr\.?|ii|iii|iv|v)\b', '', n)
    # Strip punctuation
    n = re.sub(r'[^\w\s]', '', n)
    # Strip accents
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode('ascii')
    # Collapse whitespace
    n = re.sub(r'\s+', ' ', n).strip()
    return n


# ── Player Stats (DB-backed, all leagues) ──────────────────────────

@app.get("/api/player/{player_id}/stats")
def player_stats(player_id: int,
                 league: str = Query("mlb"),
                 statcast_id: Optional[int] = Query(None)):
    """Return advanced stats for a player. MLB uses Statcast via pybaseball."""
    from datetime import datetime as dt2, timedelta

    if league not in ("mlb", "nfl", "nba", "nhl"):
        return {"player_id": player_id, "stats": None,
                "message": f"Advanced stats not yet available for {league}"}

    # Look up player name
    with closing(_db()) as con:
        row = con.execute("SELECT name FROM players WHERE id=?", (player_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Player not found")
    player_name = row["name"]

    result = {"player_id": player_id, "player_name": player_name, "league": league}

    # ── MLB: Statcast via pybaseball ──────────────────────────────
    if league == "mlb":
        result.update(_get_mlb_stats(player_name, player_id, statcast_id, now))

    # ── NFL: nflverse via nfl_data_py ─────────────────────────────
    elif league == "nfl":
        result.update(_get_nfl_stats(player_name, player_id, now))

    # ── NBA: nba_api (stats.nba.com) ──────────────────────────────
    elif league == "nba":
        result.update(_get_nba_stats(player_name, player_id, now))

    # ── NHL: api-web.nhle.com ─────────────────────────────────────
    elif league == "nhl":
        result.update(_get_nhl_stats(player_name, player_id, now))

    return result


def _get_mlb_stats(player_name: str, player_id: int, statcast_id, now: float):
    """Pull MLB stats from player_stats table (populated by ingest_statcast.py)."""
    import os, sqlite3 as sq

    try:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sq.connect(db_path)
        con.row_factory = sq.Row
        nname = _normalize_name(player_name)

        # Batting row
        bat = con.execute(
            "SELECT * FROM player_stats WHERE league='mlb' AND stat_type='batting' AND name_norm=? ORDER BY season DESC LIMIT 1",
            (nname,)
        ).fetchone()
        # Pitching row
        pit = con.execute(
            "SELECT * FROM player_stats WHERE league='mlb' AND stat_type='pitching' AND name_norm=? ORDER BY season DESC LIMIT 1",
            (nname,)
        ).fetchone()

        if not bat and not pit:
            con.close()
            return {"stats": None, "message": f"No Statcast data for {player_name}. Run ingest_statcast.py to populate."}

        out = {"window": str(bat["season"]) if bat else (str(pit["season"]) if pit else "?"), "batting": None, "pitching": None}

        if bat and bat["avg"] is not None:
            out["batting"] = {
                "avg": bat["avg"], "hr": bat["hr"], "k_pct": bat["k_pct"], "bb_pct": bat["bb_pct"],
                "exit_velo": bat["exit_velo"], "hard_hit_pct": bat["hard_hit_pct"],
                "barrel_pct": bat["barrel_pct"], "launch_angle": bat["launch_angle"],
                "woba": bat["woba"], "xwoba": bat["xwoba"],
            }

        if pit and pit["whiff_pct"] is not None:
            out["pitching"] = {
                "whiff_pct": pit["whiff_pct"], "k_pct": pit["k_pct"],
                "exit_velo_against": pit["exit_velo_against"],
                "barrel_pct_against": pit["barrel_pct_against"],
                "xwoba_against": pit["xwoba_against"],
            }

        con.close()
        return out
    except Exception as e:
        return {"stats": None, "message": f"MLB stats error: {str(e)[:200]}"}


def _get_nfl_stats(player_name: str, player_id: int, now: float):
    """Pull NFL stats from player_stats table (populated by ingest_nfl.py)."""
    import os, sqlite3 as sq

    try:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sq.connect(db_path)
        con.row_factory = sq.Row
        nname = _normalize_name(player_name)
        row = con.execute(
            "SELECT * FROM player_stats WHERE league='nfl' AND name_norm=? ORDER BY season DESC LIMIT 1",
            (nname,)
        ).fetchone()
        if not row:
            parts = player_name.strip().split(" ", 1)
            last = parts[-1] if len(parts) > 1 else player_name
            row = con.execute(
                "SELECT * FROM player_stats WHERE league='nfl' AND player_name LIKE ? ORDER BY season DESC LIMIT 1",
                (f"%{last}%",)
            ).fetchone()
        if not row:
            con.close()
            return {"stats": None, "message": f"No NFL data for {player_name}. Run ingest_nfl.py."}

        out = {
            "window": str(row["season"]),
            "player_name_nfl": row["player_name"],
            "position": row["nfl_position"],
            "team": row["nfl_team"],
            "games": row["games"],
            "source": row["source"] or "nflverse",
            "stats": {
                "passing_yards_pg": row["pass_yds_g"],
                "passing_tds": row["pass_td"],
                "interceptions": row["interceptions"],
                "completions_pg": row["cmp_g"],
                "passing_epa": row["pass_epa"],
                "carries_pg": row["carries_g"],
                "rushing_yards_pg": row["rush_yds_g"],
                "receptions": row["receptions"],
                "receiving_yards_pg": row["rec_yds_g"],
                "targets": row["targets"],
                "fantasy_points_pg": row["fantasy_pts_g"],
                "fantasy_points_ppr_pg": row["fantasy_ppr_g"],
            }
        }
        con.close()
        return out
    except Exception as e:
        return {"stats": None, "message": f"NFL stats error: {str(e)[:200]}"}


def _get_nba_stats(player_name: str, player_id: int, now: float):
    """Pull NBA stats from player_stats table (populated by ingest_hoopR.py)."""
    import os, sqlite3 as sq

    try:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sq.connect(db_path)
        con.row_factory = sq.Row
        # Fuzzy name match — try exact first, then LIKE
        nname = _normalize_name(player_name)
        row = con.execute(
            "SELECT * FROM player_stats WHERE league='nba' AND name_norm=? ORDER BY season DESC LIMIT 1",
            (nname,)
        ).fetchone()
        if not row:
            parts = player_name.strip().split(" ", 1)
            last = parts[-1] if len(parts) > 1 else player_name
            row = con.execute(
                "SELECT * FROM player_stats WHERE league='nba' AND player_name LIKE ? ORDER BY season DESC LIMIT 1",
                (f"%{last}%",)
            ).fetchone()
        if not row:
            con.close()
            return {"stats": None, "message": f"Could not find NBA stats for {player_name}. Run ingest_hoopR.py to populate."}

        out = {
            "window": str(row["season"]),
            "player_name_nba": row["player_name"],
            "team": row["team"],
            "games": row["games"],
            "source": row["source"] or "hoopR",
            "stats": {
                "pts": round(float(row["pts"]), 1),
                "reb": round(float(row["reb"]), 1),
                "ast": round(float(row["ast"]), 1),
                "stl": round(float(row["stl"]), 1),
                "blk": round(float(row["blk"]), 1),
                "fg_pct": round(float(row["fgm"]) / float(row["fga"]) * 100, 1) if row["fga"] else 0,
                "fg3_pct": round(float(row["fg3m"]) / float(row["fg3a"]) * 100, 1) if row["fg3a"] else 0,
                "ft_pct": round(float(row["ftm"]) / float(row["fta"]) * 100, 1) if row["fta"] else 0,
                "min_pg": round(float(row["minutes"]), 1) if row["minutes"] else 0,
                "turnovers": round(float(row["tov"]), 1),
                "ts_pct": round(float(row["ts_pct"]), 1),
            }
        }
        con.close()
        return out
    except Exception as e:
        return {"stats": None, "message": f"NBA stats error: {str(e)[:200]}"}


def _get_nhl_stats(player_name: str, player_id: int, now: float):
    """Pull NHL stats from player_stats table (populated by ingest_nhl.py from full rosters)."""
    import os, sqlite3 as sq

    try:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sq.connect(db_path)
        con.row_factory = sq.Row
        nname = _normalize_name(player_name)
        row = con.execute(
            "SELECT * FROM player_stats WHERE league='nhl' AND name_norm=? ORDER BY season DESC LIMIT 1",
            (nname,)
        ).fetchone()
        if not row:
            parts = player_name.strip().split(" ", 1)
            last = parts[-1] if len(parts) > 1 else player_name
            row = con.execute(
                "SELECT * FROM player_stats WHERE league='nhl' AND name_norm LIKE ? ORDER BY season DESC LIMIT 1",
                (f"%{_normalize_name(last)}%",)
            ).fetchone()
        if not row:
            con.close()
            return {"stats": None, "message": f"No NHL data for {player_name}. Run ingest_nhl.py."}

        out = {
            "window": str(row["season"]),
            "player_name_nhl": row["player_name"],
            "position": row["nhl_position"],
            "team": row["nhl_team"],
            "games": row["games"],
            "source": row["source"] or "nhle.com",
            "stats": {
                "goals": row["goals"], "assists": row["assists"], "points": row["points_nhl"],
                "shots": row["shots"], "shooting_pct": row["shooting_pct"],
                "plus_minus": row["plus_minus"], "pim": row["pim"],
                "ppg": row["ppg"], "ppp": row["ppp"], "shg": row["shg"],
                "toi": row["toi"], "faceoff_pct": row["faceoff_pct"],
            }
        }
        con.close()
        return out
    except Exception as e:
        return {"stats": None, "message": f"NHL stats error: {str(e)[:200]}"}


# ── ingestion helper ───────────────────────────────────────────────

class PropIngest(BaseModel):
    league: str
    date: str
    home: str = ""
    away: str = ""
    espn_event_id: str = ""
    props: list  # [{"player_name": str, "team": str, "market": str, "line": float, "side": "over"|"under"}]


@app.post("/api/props/ingest")
def ingest_props(batch: PropIngest):
    """Ingest a batch of props for one game. Creates player/game rows as needed."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        # ensure game row — match on league+date+home+away (espn_event_id is optional)
        if batch.espn_event_id:
            cur = con.execute(
                "SELECT id FROM prop_games WHERE espn_event_id=? AND league=?",
                (batch.espn_event_id, batch.league))
        else:
            cur = con.execute(
                "SELECT id FROM prop_games WHERE league=? AND date=? AND home=? AND away=?",
                (batch.league, batch.date, batch.home, batch.away))
        game_row = cur.fetchone()
        if not game_row:
            cur = con.execute(
                "INSERT INTO prop_games(league,date,home,away,espn_event_id) VALUES(?,?,?,?,?)",
                (batch.league, batch.date, batch.home, batch.away, batch.espn_event_id))
            game_id = cur.lastrowid
        else:
            game_id = game_row["id"]
        ingested = 0
        for p in batch.props:
            # ensure player
            cur = con.execute(
                "SELECT id FROM players WHERE name=? AND league=?",
                (p["player_name"], batch.league))
            player_row = cur.fetchone()
            if not player_row:
                cur = con.execute(
                    "INSERT INTO players(name,team,league) VALUES(?,?,?)",
                    (p["player_name"], p.get("team", ""), batch.league))
                player_id = cur.lastrowid
            else:
                player_id = player_row["id"]
            # insert prop
            con.execute(
                "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at) VALUES(?,?,?,?,?,?,?)",
                (game_id, player_id, p["market"], p["line"], p["side"], p.get("source", "manual"), now))
            ingested += 1
        con.commit()
    return {"status": "ok", "game_id": game_id, "ingested": ingested}


def _evaluate(league, game_id, predicted_winner):
    """True/False vs the REAL final, or None if the game isn't final yet."""
    try:
        res = espn.game_result(league, game_id)
    except ValueError:
        return None
    if res["winner"] is None:
        return None
    return predicted_winner.upper() == res["winner"].upper()


def _final_score_from_db(league: str, game_id: str):
    """Return {home: int, away: int} for a finished game from OUR DB, or None.

    DB-ONLY — never calls ESPN on the request path. Cumulative game scores are
    monotonic non-decreasing, so MAX per side from persisted scoring_plays IS the
    final. The DB is populated by the /boxscore snapshot (backfill / live capture).
    Catching DB gaps against ESPN is an out-of-band job run occasionally — NOT here —
    so serving a page never makes an ESPN round-trip.
    (Do NOT order by `clock`: it is TEXT with mixed formats '8:44' vs '9.4', so a
    string sort picks the wrong play, and the clock counts DOWN anyway.)
    """
    lg = league.lower()
    with closing(_db()) as con:
        row = con.execute(
            "SELECT MAX(home_score) AS home, MAX(away_score) AS away FROM scoring_plays "
            "WHERE league=? AND game_id=?",
            (lg, game_id),
        ).fetchone()
    if row and row["home"] is not None and row["away"] is not None:
        return {"home": int(row["home"]), "away": int(row["away"])}
    return None


def _snapshot_strength(league, rows):
    """Persist a strength snapshot so we accumulate history (the trading side wants the time series)."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.executemany(
            "INSERT INTO strength_snap(captured_at,league,abbrev,win_pct,differential,wins,losses) "
            "VALUES(?,?,?,?,?,?,?)",
            [(now, league, r["abbrev"], r["win_pct"], r["differential"], r["wins"], r["losses"])
             for r in rows])
        con.commit()


# ---------------------------------------------------------------------------
# NEW: data-collection helpers (NBA+NHL only). Follow the _snapshot_strength pattern:
# grab ESPN data, INSERT into SQLite. Called from endpoints so every API hit
# persists. The trading side reads these tables directly.
# ---------------------------------------------------------------------------

def _parse_int(v):
    try: return int(v)
    except (TypeError, ValueError): return None

def _parse_real(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _fetch_summary(league, game_id):
    """Raw ESPN summary payload for a single game. Returns the full JSON dict."""
    import json, urllib.request
    _, path = espn._check(league)
    url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary?event={game_id}"
    req = urllib.request.Request(url, headers=espn._HDRS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _extract_team_stats(league, game_id, summary):
    """Parse boxscore.teams[].statistics[] → list of {team_abbrev, home_away, stats_dict}."""
    bs = summary.get("boxscore", {})
    teams = bs.get("teams", [])
    if not teams:
        # fall back to header
        comp = (summary.get("header", {}).get("competitions") or [{}])[0]
        teams = [{"team": c.get("team", {}),
                   "statistics": [],
                   "_homeAway": c.get("homeAway")}
                  for c in comp.get("competitors", [])]
    out = []
    for t in teams:
        team_info = t.get("team", {})
        abbrev = team_info.get("abbreviation", "")
        home_away = t.get("_homeAway") or t.get("homeAway", "")
        raw = {}
        for s in t.get("statistics", []):
            name = s.get("name")
            if name:
                raw[name] = s.get("displayValue")
        out.append({"team_abbrev": abbrev, "home_away": home_away, "stats": raw})
    return out


def _extract_scoring_plays(league, game_id, summary):
    """Parse plays[] filtered to scoringPlay=true → list of dicts."""
    plays = summary.get("plays", [])
    out = []
    for p in plays:
        if not p.get("scoringPlay"):
            continue
        period = p.get("period", {})
        clock = p.get("clock", {})
        ptype = p.get("type", {})
        # Determine scoring team from text: "[Team] Goal" / "[Player] made..."
        text = p.get("text", "")
        team_abbrev = ""
        scorer = ""
        # Try to extract team from competitors or text pattern
        comp = (summary.get("header", {}).get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])
        if p.get("homeScore", 0) > p.get("_prev_home", -1) if "_prev_home" in p else (len(out) > 0 and p["homeScore"] > out[-1]["home_score"]):
            # home scored
            for c in competitors:
                if c.get("homeAway") == "home":
                    team_abbrev = c.get("team", {}).get("abbreviation", "")
        elif len(competitors) == 2:
            # away scored (or we guess from context)
            for c in competitors:
                if c.get("homeAway") == "away":
                    team_abbrev = c.get("team", {}).get("abbreviation", "")
        out.append({
            "play_id": str(p.get("id", "")),
            "period": _parse_int(period.get("number")) if period else None,
            "period_disp": period.get("displayValue", "") if period else "",
            "clock": clock.get("displayValue", "") if clock else "",
            "away_score": _parse_int(p.get("awayScore")),
            "home_score": _parse_int(p.get("homeScore")),
            "team_abbrev": team_abbrev,
            "scorer_name": scorer,
            "play_text": text,
            "play_type": ptype.get("text", "") if ptype else "",
        })
    return out


def _extract_game_context(league, game_id, summary):
    """Parse gameInfo + header → {venue_name, venue_city, attendance, officials, home/away}."""
    gi = summary.get("gameInfo", {})
    venue = gi.get("venue", {})
    officials = [o.get("displayName", "") for o in gi.get("officials", [])]
    header = summary.get("header", {})
    comp = (header.get("competitions") or [{}])[0]
    home_team = ""
    away_team = ""
    for c in comp.get("competitors", []):
        ab = c.get("team", {}).get("abbreviation", "")
        if c.get("homeAway") == "home":
            home_team = ab
        else:
            away_team = ab
    import json
    return {
        "venue_name": venue.get("fullName", ""),
        "venue_city": venue.get("address", {}).get("city", ""),
        "attendance": _parse_int(gi.get("attendance")),
        "officials": json.dumps(officials) if officials else "[]",
        "home_team": home_team,
        "away_team": away_team,
    }


# --- snapshot functions (same pattern as _snapshot_strength) ---

def _snapshot_rosters(league, team_abbrev, players):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.executemany(
            "INSERT INTO roster_snap(captured_at,league,team_abbrev,player_id,name,jersey,position) "
            "VALUES(?,?,?,?,?,?,?)",
            [(now, league, team_abbrev, p["player_id"], p["name"], p["jersey"], p["position"])
             for p in players])
        con.commit()


def _snapshot_team_game_stats(league, game_id, team_stats_list):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        for t in team_stats_list:
            s = t["stats"]
            con.execute(
                "INSERT OR REPLACE INTO team_game_stats("
                "league,game_id,captured_at,team_abbrev,home_away,"
                "fgm_fga,fg_pct,tpm_tpa,tp_pct,ftm_fta,ft_pct,"
                "rebounds,off_rebounds,def_rebounds,assists,steals,blocks,"
                "turnovers,fouls,pts_off_to,fast_break_pts,pts_in_paint,"
                "largest_lead,lead_changes,lead_pct,"
                "shots,blocked_shots,hits,takeaways,giveaways,faceoffs_won,"
                "faceoff_pct,powerplay_goals,powerplay_opps,powerplay_pct,"
                "shorthanded_goals,penalties,penalty_min"
                ") VALUES(?,?,?,?,?,  ?,?,?,?,?,?,  ?,?,?,?,?,?,  ?,?,?,?,?,  ?,?,?,  ?,?,?,?,?,?,  ?,?,?,?,  ?,?,?)",
                (league, game_id, now, t["team_abbrev"], t["home_away"],
                 s.get("fieldGoalsMade-fieldGoalsAttempted"), _parse_real(s.get("fieldGoalPct")),
                 s.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"), _parse_real(s.get("threePointFieldGoalPct")),
                 s.get("freeThrowsMade-freeThrowsAttempted"), _parse_real(s.get("freeThrowPct")),
                 _parse_int(s.get("totalRebounds")), _parse_int(s.get("offensiveRebounds")),
                 _parse_int(s.get("defensiveRebounds")), _parse_int(s.get("assists")),
                 _parse_int(s.get("steals")), _parse_int(s.get("blocks")),
                 _parse_int(s.get("turnovers")), _parse_int(s.get("fouls")),
                 _parse_int(s.get("turnoverPoints")), _parse_int(s.get("fastBreakPoints")),
                 _parse_int(s.get("pointsInPaint")), _parse_int(s.get("largestLead")),
                 _parse_int(s.get("leadChanges")), _parse_real(s.get("leadPercentage")),
                 _parse_int(s.get("shotsTotal")), _parse_int(s.get("blockedShots")),
                 _parse_int(s.get("hits")), _parse_int(s.get("takeaways")),
                 _parse_int(s.get("giveaways")), _parse_int(s.get("faceoffsWon")),
                 _parse_real(s.get("faceoffPercent")), _parse_int(s.get("powerPlayGoals")),
                 _parse_int(s.get("powerPlayOpportunities")), _parse_real(s.get("powerPlayPct")),
                 _parse_int(s.get("shortHandedGoals")), _parse_int(s.get("penalties")),
                 _parse_int(s.get("penaltyMinutes"))))
        con.commit()


def _snapshot_scoring_plays(league, game_id, plays):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.executemany(
            "INSERT OR IGNORE INTO scoring_plays("
            "league,game_id,play_id,captured_at,period,period_disp,clock,"
            "away_score,home_score,team_abbrev,scorer_name,play_text,play_type"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(league, game_id, p["play_id"], now,
              p["period"], p["period_disp"], p["clock"],
              p["away_score"], p["home_score"], p["team_abbrev"],
              p["scorer_name"], p["play_text"], p["play_type"])
             for p in plays])
        con.commit()


def _snapshot_game_context(league, game_id, ctx):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.execute(
            "INSERT OR REPLACE INTO game_context("
            "league,game_id,captured_at,home_team,away_team,"
            "venue_name,venue_city,attendance,officials"
            ") VALUES(?,?,?,?,?,?,?,?,?)",
            (league, game_id, now,
             ctx["home_team"], ctx["away_team"],
             ctx["venue_name"], ctx["venue_city"],
             ctx["attendance"], ctx["officials"]))
        con.commit()


def _snapshot_boxscore_full(league, game_id):
    """One call snapshots team_game_stats + scoring_plays + game_context for a game."""
    try:
        summary = _fetch_summary(league, game_id)
    except Exception:
        return  # game not available yet (pre-game) — silently skip
    team_stats = _extract_team_stats(league, game_id, summary)
    if team_stats:
        _snapshot_team_game_stats(league, game_id, team_stats)
    plays = _extract_scoring_plays(league, game_id, summary)
    if plays:
        _snapshot_scoring_plays(league, game_id, plays)
    ctx = _extract_game_context(league, game_id, summary)
    _snapshot_game_context(league, game_id, ctx)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
