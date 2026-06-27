"""routers/game_extras.py — game_extras endpoints. Handlers only; shared code lives in _core."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *

router = APIRouter()

@router.get("/api/game/{league}/{game_id}/props")
def game_props(league: str, game_id: str):
    """Props for an ESPN game (linked via prop_games.espn_event_id), grouped by
    player — the Game page's betting view. Each player's props expand to a chart."""
    with closing(_db()) as con:
        rows = con.execute(
            """SELECT pl.id AS player_id, pl.name, pl.team, p.market, p.line, p.side,
                      MAX(p.captured_at) ca
               FROM props p
               JOIN prop_games g ON g.id = p.game_id
               JOIN players pl ON pl.id = p.player_id
               WHERE g.espn_event_id = ?
               GROUP BY pl.id, p.market, p.side
               ORDER BY pl.name""",
            (str(game_id),)).fetchall()
    players: dict = {}
    for r in rows:
        d = players.setdefault(r["player_id"], {"player_id": r["player_id"], "name": r["name"],
                                                "team": r["team"], "props": []})
        d["props"].append({"market": _base_market(r["market"]), "line": r["line"], "side": r["side"]})
    return {"league": league, "game_id": str(game_id), "players": list(players.values())}


@router.get("/api/game/{league}/{game_id}/story")
def game_story(league: str, game_id: str, refresh: bool = Query(False)):
    """AI matchup blurb (DeepSeek V4 Pro), grounded ONLY in our records/streaks/form.
    Cached per game so it's generated once, not every load."""
    lg = league.lower()
    with closing(_db()) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS game_story(
            league TEXT, game_id TEXT, story TEXT, generated_at TEXT,
            PRIMARY KEY(league, game_id))""")
        if not refresh:
            r = con.execute("SELECT story FROM game_story WHERE league=? AND game_id=?", (lg, game_id)).fetchone()
            if r:
                return {"league": lg, "game_id": game_id, "story": r["story"], "cached": True}

    try:
        gr = espn.game_result(lg, game_id)
        teams = list((gr.get("scores") or {}).keys())
    except Exception:
        teams = []
    if len(teams) != 2:
        return {"league": lg, "game_id": game_id, "story": None}
    smap = espn.team_strength_map(lg)

    def facts(ab):
        s = smap.get(ab) or {}
        return (f"{s.get('name', ab)} ({ab}): {s.get('wins')}-{s.get('losses')}, "
                f"{s.get('win_pct')} win%, streak {s.get('streak')}, last-10 {s.get('last10')}, "
                f"differential {s.get('differential')}")
    grounding = (f"Matchup: {teams[0]} vs {teams[1]}. Game state: {gr.get('state')}.\n"
                 f"{facts(teams[0])}\n{facts(teams[1])}")

    # Notable player form: each prop player's last 5 games for their primary market —
    # grounds "X is hot / cold" without inventing news.
    form_lines, seen = [], set()
    with closing(_db()) as con:
        prs = con.execute(
            """SELECT pl.id, pl.name, p.market, COUNT(*) c FROM props p
               JOIN prop_games g ON g.id = p.game_id JOIN players pl ON pl.id = p.player_id
               WHERE g.espn_event_id = ? GROUP BY pl.id, p.market ORDER BY c DESC""",
            (str(game_id),)).fetchall()
        for r in prs:
            if r["id"] in seen or len(form_lines) >= 8:
                continue
            sk = _MARKET_STAT_KEY.get(lg, {}).get(_base_market(r["market"]))
            if not sk:
                continue
            logs = con.execute(
                """SELECT stats FROM player_game_logs WHERE player_id=?
                   ORDER BY COALESCE(game_date,'') DESC, CAST(game_no AS INTEGER) DESC LIMIT 5""",
                (r["id"],)).fetchall()
            vals = [json.loads(x["stats"]).get(sk) for x in logs]
            vals = [v for v in vals if v is not None]
            if len(vals) >= 3:
                form_lines.append(f"{r['name']} — last 5 {_base_market(r['market'])}: {vals}")
                seen.add(r["id"])
    if form_lines:
        grounding += "\nRecent player form (most recent first):\n" + "\n".join(form_lines)

    system = ("You are a sharp sports writer. In 2-4 sentences, set up this matchup using ONLY the "
              "facts given. Lead with the most interesting thing — a team streak/record/differential, "
              "OR a player on a clear hot or cold run from the form data. Be specific with numbers. "
              "Do NOT invent injuries, trades, lineup news, or anything not in the facts. No clichés, "
              "no hype, plain confident tone.")
    story = _deepseek_chat(system, grounding)
    if story:
        with closing(_db()) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS game_story(
                league TEXT, game_id TEXT, story TEXT, generated_at TEXT,
                PRIMARY KEY(league, game_id))""")
            con.execute("INSERT OR REPLACE INTO game_story(league, game_id, story, generated_at) "
                        "VALUES (?,?,?,datetime('now'))", (lg, game_id, story))
            con.commit()
    return {"league": lg, "game_id": game_id, "story": story, "cached": False}


@router.get("/api/game/{league}/{game_id}/edge")
def game_edge(league: str, game_id: str):
    """Projected stat lines for players in an NBA game (no Bovada props for NBA).
    Queries player_game_logs for this game's participants, computes per-stat
    projections from their recent logs, returns top projected lines."""
    lg = league.lower()
    if lg != "nba":
        return {"league": lg, "game_id": str(game_id), "players": []}

    import json as _json
    with closing(_db()) as con:
        rows = con.execute(
            """SELECT DISTINCT pl.id AS player_id, pl.name, pl.team
               FROM player_game_logs l
               JOIN players pl ON pl.id = l.player_id
               WHERE l.league='nba' AND l.game_id=?""",
            (str(game_id),)).fetchall()

    if not rows:
        return {"league": lg, "game_id": str(game_id), "players": []}

    stat_keys = ["PTS", "REB", "AST", "PRA", "3PM", "STL", "BLK", "TO"]
    players_out = []

    with closing(_db()) as con:
        for r in rows:
            pid = r["player_id"]
            logs = con.execute(
                """SELECT stats FROM player_game_logs
                   WHERE player_id=? AND league='nba'
                   ORDER BY COALESCE(game_date,'') DESC, CAST(game_no AS INTEGER) DESC
                   LIMIT 20""",
                (pid,)).fetchall()
            if not logs:
                continue

            series: dict = {}
            for lr in logs:
                for k, v in _json.loads(lr["stats"]).items():
                    if isinstance(v, (int, float)) and k in stat_keys:
                        series.setdefault(k, []).append(v)

            props = []
            for sk in stat_keys:
                vals = series.get(sk)
                if vals and len(vals) >= 5:
                    avg = round(sum(vals) / len(vals), 1)
                    props.append({"market": sk.lower(), "line": avg, "side": "proj"})

            if props:
                players_out.append({
                    "player_id": pid, "name": r["name"], "team": r["team"],
                    "props": props[:5]
                })

    return {"league": lg, "game_id": str(game_id), "players": players_out}

