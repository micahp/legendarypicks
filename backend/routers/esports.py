"""routers/esports.py — live esports surfaces.

v0 = chess (Lichess), the "Live Now / moment that matters" proof. Stateless: each request
snapshots the current featured Lichess TV game plus a short window of its most recent moves,
and reads live *material momentum* off the FENs. This is the cheapest honest inflection signal
without an engine — Lichess `cloud-eval` does not cover live mid-game positions, so true win%
(engine eval) is a deliberate later upgrade. The same shape (players, live clocks, a "moment"
string) is what the Dota/CS2 adapters will return, so the frontend card is title-agnostic.
"""
import json
import math
import os
import shutil
import threading
import urllib.request as _u

import chess
import chess.engine
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

_PIECE = {"p": 1, "n": 3, "b": 3, "r": 5, "q": 9}  # king excluded


def _material(fen: str) -> int:
    """White-minus-black material from a FEN board field."""
    board = fen.split(" ", 1)[0]
    total = 0
    for ch in board:
        v = _PIECE.get(ch.lower())
        if v is None:
            continue
        total += v if ch.isupper() else -v
    return total


# --- Engine eval (Stockfish) → real win% --------------------------------------------------
# Lichess cloud-eval doesn't cover live positions, so we run our own engine at a shallow,
# bounded depth (fast enough for the request path) and convert to a White-POV win%.
_ENGINE_PATH = os.environ.get("STOCKFISH_PATH") or shutil.which("stockfish") or "/usr/games/stockfish"
_engine = None
_engine_lock = threading.Lock()


def _get_engine():
    global _engine
    if _engine is None:
        _engine = chess.engine.SimpleEngine.popen_uci(_ENGINE_PATH)
    return _engine


def _win_pct_from_cp(cp: int) -> float:
    """Centipawns (White POV) → White win%, using Lichess's logistic constant."""
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def _engine_eval(fen: str, depth: int = 11):
    """{cp, mate, win_pct} from White's POV, or None if the engine is unavailable."""
    try:
        board = chess.Board(fen)
    except Exception:
        return None
    if board.is_game_over():
        res = board.result()
        wp = 100.0 if res == "1-0" else 0.0 if res == "0-1" else 50.0
        return {"cp": None, "mate": None, "win_pct": round(wp, 1)}
    try:
        with _engine_lock:
            info = _get_engine().analyse(board, chess.engine.Limit(depth=depth))
        score = info["score"].white()
        if score.is_mate():
            m = score.mate()
            return {"cp": None, "mate": m, "win_pct": 100.0 if m > 0 else 0.0}
        cp = max(-1500, min(1500, score.score()))
        return {"cp": cp, "mate": None, "win_pct": round(_win_pct_from_cp(cp), 1)}
    except Exception:
        global _engine  # engine crashed → drop it so the next call respawns
        try:
            if _engine:
                _engine.quit()
        except Exception:
            pass
        _engine = None
        return None


def _read_tv(window: int = 6, timeout: float = 3.5):
    """Read the global featured TV game: the 'featured' snapshot (sent first on connect, and
    again whenever TV switches games) + up to `window` following fen updates, each carrying the
    live clocks wc/bc. Returns (featured_dict, [fen_events]).

    Resilient by design: a slow game may not produce `window` moves before the deadline, so we
    return whatever we captured (the featured snapshot alone is enough to render the card) rather
    than letting a socket timeout discard it."""
    import time
    req = _u.Request("https://lichess.org/api/tv/feed",
                     headers={"Accept": "application/x-ndjson"})
    featured, fens = None, []
    deadline = time.time() + timeout
    try:
        resp = _u.urlopen(req, timeout=timeout)
    except Exception:
        return None, []
    try:
        for raw in resp:
            try:
                ev = json.loads(raw.decode().strip())
            except Exception:
                continue
            t = ev.get("t")
            if t == "featured":
                featured = ev.get("d")
                fens = []  # reset: only collect updates for the current featured game
            elif t == "fen":
                fens.append(ev.get("d"))
            if featured and (len(fens) >= window or time.time() >= deadline):
                break
            if time.time() >= deadline:
                break
    except Exception:
        pass  # socket timeout / reset — fall through with whatever we collected
    finally:
        try:
            resp.close()
        except Exception:
            pass
    return featured, fens


@router.get("/api/esports/chess/live")
def chess_live():
    """The current top live chess game with a 'moment that matters' read."""
    try:
        featured, fens = _read_tv()
    except Exception:
        return JSONResponse({"live": False, "error": "feed unavailable"}, status_code=200)
    if not featured:
        return {"live": False}

    players = featured.get("players", []) or []

    def pl(color: str):
        p = next((x for x in players if x.get("color") == color), {}) or {}
        u = p.get("user") or {}
        return {"name": u.get("name") or "Anonymous",
                "rating": p.get("rating"),
                "clock": p.get("seconds")}

    cur = fens[-1] if fens else None
    cur_fen = (cur.get("fen") if cur else featured.get("fen")) or ""
    wc = cur.get("wc") if cur else pl("white")["clock"]
    bc = cur.get("bc") if cur else pl("black")["clock"]

    mat = _material(cur_fen) if cur_fen else 0
    turn = "white" if (cur_fen.split(" ")[1:2] or ["w"])[0] == "w" else "black"

    # Real win% from the engine: evaluate the current position, and the window-start
    # position, so we can read a *win-probability swing* (the truest "moment that matters").
    eval_now = _engine_eval(cur_fen) if cur_fen else None
    start_fen = fens[0].get("fen") if len(fens) >= 2 else None
    eval_then = _engine_eval(start_fen) if start_fen else None
    win_now = eval_now["win_pct"] if eval_now else None
    win_swing = (round(win_now - eval_then["win_pct"], 1)
                 if (win_now is not None and eval_then) else None)

    # Moment priority: a big win% swing (someone blundered/converted) → time scramble →
    # decisive position → material fallback when the engine is unavailable.
    low = min([c for c in (wc, bc) if c is not None], default=None)
    moment = None
    if win_swing is not None and abs(win_swing) >= 12 and eval_then:
        who = "White" if win_swing > 0 else "Black"
        moment = f"{who} swung the game — win% {eval_then['win_pct']:.0f}→{win_now:.0f}"
    elif low is not None and low <= 20:
        moment = "Time scramble — under 20s on the clock"
    elif eval_now and eval_now.get("mate") is not None:
        who = "White" if eval_now["mate"] > 0 else "Black"
        moment = f"{who} has forced mate in {abs(eval_now['mate'])}"
    elif win_now is not None and (win_now >= 80 or win_now <= 20):
        who = "White" if win_now >= 80 else "Black"
        moment = f"{who} is winning ({max(win_now, 100 - win_now):.0f}% win)"
    elif abs(mat) >= 5:  # engine-less fallback
        moment = f"{'White' if mat > 0 else 'Black'} is winning (+{abs(mat)})"

    return {
        "live": True, "sport": "chess", "source": "lichess",
        "gameId": featured.get("id"),
        "url": f"https://lichess.org/{featured.get('id')}",
        "white": pl("white"), "black": pl("black"),
        "fen": cur_fen, "turn": turn,
        "clocks": {"white": wc, "black": bc},
        "material": mat,
        "eval": eval_now,          # {cp, mate, win_pct} White POV, or null
        "winPct": win_now,         # White win% (null if engine unavailable)
        "winSwing": win_swing,
        "moment": moment,
    }


# --- LoL / MSI pre-game prediction ---------------------------------------------------------
# Data: the LoL Esports web API (the semi-public key embedded in lolesports.com — not a
# secret). getSchedule gives MSI matches + team codes; we price each one with a power-ranking
# prior (Sheep Esports MSI 2026 rankings, encoded as Elo) → per-game win prob → Bo5 series
# prob. This is the "selection prior" layer; Oracle's Elixir team form blends in later, and the
# live gold/objective window replaces the prior once a game is actually being played.
_LOL_KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"  # public lolesports.com web key

# code -> (rank, Elo rating, display name). Ratings derived from the Sheep MSI 2026 order,
# spaced to reflect its tiers (top Asian sides + G2 tight at the top, then clear gaps).
_LOL_TEAMS = {
    "HLE":  (1, 1700, "Hanwha Life Esports"),
    "BLG":  (2, 1690, "BiliBili Gaming"),
    "T1":   (3, 1668, "T1"),
    "G2":   (4, 1622, "G2 Esports"),
    "TES":  (5, 1600, "Top Esports"),
    "LYON": (6, 1520, "LYON"),
    "KC":   (7, 1500, "Karmine Corp"),
    "TSW":  (8, 1462, "Team Secret Whales"),
    "TLAW": (9, 1450, "Team Liquid"),
    "FUR":  (10, 1410, "FURIA"),
    "DCG":  (11, 1372, "Deep Cross Gaming"),
}
# name-keyword fallback when a broadcast code differs from the above
_LOL_ALIASES = {
    "hanwha": "HLE", "bilibili": "BLG", "t1": "T1", "g2": "G2", "top esports": "TES",
    "lyon": "LYON", "karmine": "KC", "secret whales": "TSW", "team liquid": "TLAW",
    "furia": "FUR", "deep cross": "DCG",
}


def _team_rating(code, name):
    if code in _LOL_TEAMS:
        return _LOL_TEAMS[code]
    n = (name or "").lower()
    for kw, c in _LOL_ALIASES.items():
        if kw in n:
            return _LOL_TEAMS[c]
    return None


def _p_game(ra, rb):
    """Elo win prob for A vs B (single game)."""
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def _p_bo5(p):
    """Probability of winning a best-of-5 given per-game prob p (win 3 before opp)."""
    q = 1 - p
    return p ** 3 * (1 + 3 * q + 6 * q * q)


def _lol_get(url):
    req = _u.Request(url, headers={"x-api-key": _LOL_KEY, "Accept": "application/json"})
    with _u.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


# --- Bovada market line (model vs market = the edge) ---------------------------------------
_BOV_MSI = ("https://www.bovada.lv/services/sports/event/coupon/events/A/description/"
            "esports/league-of-legends/mid-season-invitational?marketFilterId=def&liveOnly=false&lang=en")
_bov_cache = {"t": 0.0, "data": {}}


def _amer_to_p(american):
    o = float(american)
    return (-o) / (-o + 100) if o < 0 else 100 / (o + 100)


def _resolve_code(name):
    n = (name or "").lower()
    for code in _LOL_TEAMS:
        if code.lower() == n:
            return code
    for kw, c in _LOL_ALIASES.items():
        if kw in n:
            return c
    return None


def _bovada_msi_market():
    """Map {frozenset(codeA,codeB): {code: de-vigged market win%}} from Bovada moneylines.
    Cached ~45s (odds move slowly; don't hammer Bovada on every poll)."""
    import time
    if _bov_cache["data"] and time.time() - _bov_cache["t"] < 45:
        return _bov_cache["data"]
    out = {}
    try:
        req = _u.Request(_BOV_MSI, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with _u.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        for grp in data:
            for e in grp.get("events", []):
                ml = None
                for dg in e.get("displayGroups", []):
                    for mk in dg.get("markets", []):
                        if (mk.get("description") or "").lower() == "moneyline":
                            ml = mk
                            break
                    if ml:
                        break
                if not ml:
                    continue
                pairs = []
                for o in ml.get("outcomes", []):
                    code = _resolve_code(o.get("description"))
                    am = (o.get("price") or {}).get("american")
                    if code and am not in (None, "EVEN"):
                        try:
                            pairs.append((code, _amer_to_p(am)))
                        except Exception:
                            pass
                if len(pairs) == 2:
                    s = pairs[0][1] + pairs[1][1]
                    if s > 0:
                        out[frozenset(c for c, _ in pairs)] = {c: round(p / s * 100, 1) for c, p in pairs}
        _bov_cache.update(t=time.time(), data=out)
    except Exception:
        return _bov_cache["data"]  # stale-but-ok on failure
    return out


@router.get("/api/esports/lol/msi/predictions")
def msi_predictions():
    """Pre-game win predictions for upcoming/known MSI 2026 matches, with the Bovada market
    line attached so model% vs market% surfaces the edge."""
    try:
        sched = _lol_get("https://esports-api.lolesports.com/persisted/gw/getSchedule?hl=en-US&sport=lol")
    except Exception:
        return {"event": "MSI 2026", "matches": [], "error": "schedule unavailable"}

    market = _bovada_msi_market()

    events = (((sched.get("data") or {}).get("schedule") or {}).get("events") or [])
    matches = []
    for e in events:
        if (e.get("league") or {}).get("slug") != "msi":
            continue
        m = e.get("match") or {}
        teams = m.get("teams") or []
        if len(teams) != 2:
            continue
        a, b = teams[0], teams[1]
        if a.get("code") == "TBD" or b.get("code") == "TBD":
            continue
        ra = _team_rating(a.get("code"), a.get("name"))
        rb = _team_rating(b.get("code"), b.get("name"))
        if not ra or not rb:
            continue

        bo = (m.get("strategy") or {}).get("count") or 1
        pa = _p_game(ra[1], rb[1])
        sa = _p_bo5(pa) if bo >= 5 else pa  # series prob for team A

        mkt = market.get(frozenset({a.get("code"), b.get("code")})) or {}

        def team(t, rt, series_pct):
            res = t.get("result") or {}
            model_pct = round(series_pct * 100, 1)
            market_pct = mkt.get(t.get("code"))
            return {"name": t.get("name"), "code": t.get("code"), "image": t.get("image"),
                    "rank": rt[0], "winPct": model_pct,
                    "marketPct": market_pct,
                    "edge": round(model_pct - market_pct, 1) if market_pct is not None else None,
                    "wins": res.get("gameWins")}

        fav = a.get("code") if sa >= 0.5 else b.get("code")
        matches.append({
            "startTime": e.get("startTime"), "state": e.get("state"), "bestOf": bo,
            "teamA": team(a, ra, sa), "teamB": team(b, rb, 1 - sa),
            "favorite": fav, "hasMarket": bool(mkt),
        })

    # upcoming first (inProgress, unstarted), completed last; each by start time
    order = {"inProgress": 0, "unstarted": 1, "completed": 2}
    matches.sort(key=lambda x: (order.get(x["state"], 1), x["startTime"] or ""))
    return {"event": "MSI 2026", "model": "power-ranking prior (Sheep) · Elo · Bo5",
            "matches": matches}


# --- LoL / MSI live game (embed the actual broadcast + live state) -------------------------
def _lol_window(gid):
    """Latest live frame (gold/kills/objectives per side) from the LoL livestats window.
    The window needs a startingTime ~now-60s rounded to 10s, else it returns opening frames."""
    import datetime
    t = datetime.datetime.utcnow() - datetime.timedelta(seconds=60)
    t = t.replace(microsecond=0, second=(t.second // 10) * 10)
    ts = t.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    url = f"https://feed.lolesports.com/livestats/v1/window/{gid}?startingTime={ts}"
    try:
        with _u.urlopen(_u.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=8) as r:
            d = json.loads(r.read().decode())
    except Exception:
        return None
    frames = d.get("frames") or []
    if not frames:
        return None
    f = frames[-1]
    md = d.get("gameMetadata") or {}

    def side(team, meta):
        return {"id": meta.get("esportsTeamId"), "gold": team.get("totalGold"),
                "kills": team.get("totalKills"), "towers": team.get("towers"),
                "barons": team.get("barons"), "dragons": len(team.get("dragons") or [])}

    def roster(meta):
        return [{"pid": p.get("participantId"), "playerId": p.get("esportsPlayerId"),
                 "name": p.get("summonerName"), "role": p.get("role"),
                 "champ": p.get("championId"), "teamId": meta.get("esportsTeamId")}
                for p in (meta.get("participantMetadata") or [])]
    return {"state": f.get("gameState"),
            "blue": side(f.get("blueTeam") or {}, md.get("blueTeamMetadata") or {}),
            "red": side(f.get("redTeam") or {}, md.get("redTeamMetadata") or {}),
            "roster": roster(md.get("blueTeamMetadata") or {}) + roster(md.get("redTeamMetadata") or {})}


_ddv_cache = {"t": 0.0, "v": None}


def _ddragon_ver():
    """Latest Data Dragon version (for champion portraits). Cached ~1h."""
    import time
    if _ddv_cache["v"] and time.time() - _ddv_cache["t"] < 3600:
        return _ddv_cache["v"]
    try:
        with _u.urlopen("https://ddragon.leagueoflegends.com/api/versions.json", timeout=6) as r:
            _ddv_cache.update(t=time.time(), v=json.loads(r.read().decode())[0])
    except Exception:
        pass
    return _ddv_cache["v"]


def _lol_details(gid):
    """Per-player live stats {participantId: {level,kills,deaths,assists,cs,gold}}."""
    import datetime
    t = datetime.datetime.utcnow() - datetime.timedelta(seconds=60)
    t = t.replace(microsecond=0, second=(t.second // 10) * 10)
    ts = t.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    url = f"https://feed.lolesports.com/livestats/v1/details/{gid}?startingTime={ts}"
    try:
        with _u.urlopen(_u.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=8) as r:
            d = json.loads(r.read().decode())
    except Exception:
        return {}
    frames = d.get("frames") or []
    if not frames:
        return {}
    out = {}
    for p in frames[-1].get("participants") or []:
        out[p.get("participantId")] = {"level": p.get("level"), "kills": p.get("kills"),
                                       "deaths": p.get("deaths"), "assists": p.get("assists"),
                                       "cs": p.get("creepScore"), "gold": p.get("totalGold")}
    return out


@router.get("/api/esports/lol/msi/live")
def msi_live():
    """The currently-live MSI match: broadcast embed (YouTube/Twitch) + live game state."""
    try:
        live = _lol_get("https://esports-api.lolesports.com/persisted/gw/getLive?hl=en-US")
    except Exception:
        return {"live": False}
    for e in (((live.get("data") or {}).get("schedule") or {}).get("events") or []):
        if (e.get("league") or {}).get("slug") != "msi":
            continue
        if e.get("type") != "match" or e.get("state") != "inProgress":
            continue
        m = e.get("match") or {}
        teams = m.get("teams") or []
        yt = tw = None
        for s in e.get("streams") or []:
            loc = (s.get("mediaLocale") or {}).get("locale", "")
            if loc.startswith("en"):
                if s.get("provider") == "youtube" and not yt:
                    yt = s.get("parameter")
                if s.get("provider") == "twitch" and not tw:
                    tw = s.get("parameter")
        gid = gnum = None
        games = []
        for g in m.get("games") or []:
            games.append({"number": g.get("number"), "state": g.get("state")})
            if g.get("state") == "inProgress":
                gid, gnum = g.get("id"), g.get("number")
        win = _lol_window(gid) if gid else None
        bo = (m.get("strategy") or {}).get("count") or 1
        details = _lol_details(gid) if gid else {}
        ddv = _ddragon_ver()
        roster = win.get("roster", []) if win else []

        def players_for(team_id):
            rows = []
            for pm in roster:
                if str(pm.get("teamId")) != str(team_id):
                    continue
                st = details.get(pm["pid"], {})
                champ = pm.get("champ")
                rows.append({
                    "name": pm.get("name"), "role": pm.get("role"), "champ": champ,
                    "champImg": (f"https://ddragon.leagueoflegends.com/cdn/{ddv}/img/champion/{champ}.png"
                                 if (ddv and champ) else None),
                    "kills": st.get("kills"), "deaths": st.get("deaths"), "assists": st.get("assists"),
                    "cs": st.get("cs"), "gold": st.get("gold"), "level": st.get("level"),
                })
            order = {"top": 0, "jungle": 1, "mid": 2, "bottom": 3, "support": 4}
            rows.sort(key=lambda r: order.get(r.get("role"), 9))
            return rows

        def team(x):
            r = _team_rating(x.get("code"), x.get("name"))
            t = {"name": x.get("name"), "code": x.get("code"), "image": x.get("image"),
                 "id": x.get("id"), "rank": r[0] if r else None,
                 "wins": (x.get("result") or {}).get("gameWins"),
                 "gold": None, "kills": None, "towers": None,
                 "players": players_for(x.get("id"))}
            if win:  # map live side by team id
                for s in (win["blue"], win["red"]):
                    if s.get("id") and str(s["id"]) == str(x.get("id")):
                        t.update(gold=s["gold"], kills=s["kills"], towers=s["towers"],
                                 barons=s["barons"], dragons=s["dragons"])
            return t

        a = team(teams[0]) if teams else None
        b = team(teams[1]) if len(teams) > 1 else None
        gold_lead = None
        if a and b and a.get("gold") and b.get("gold"):
            gold_lead = {"code": a["code"] if a["gold"] >= b["gold"] else b["code"],
                         "amount": abs(a["gold"] - b["gold"])}
        return {"live": True, "matchId": m.get("id"), "gameId": gid, "gameNumber": gnum,
                "bestOf": bo, "winsNeeded": bo // 2 + 1, "games": games,
                "gameState": win.get("state") if win else None,
                "youtube": yt, "twitch": tw, "teamA": a, "teamB": b, "goldLead": gold_lead}
    return {"live": False}


# --- GRID (official CS2 / Dota data via Open Access) ---------------------------------------
# api-op.grid.gg (the Open Access host). Covers CS2 + Dota2 only. Commercial-legit, unlike the
# unofficial lolesports feed. central-data = schedule/teams; series-state = live score + KDA.
_GRID_KEY = os.environ.get("GRID_API_KEY")
_GRID_CD = "https://api-op.grid.gg/central-data/graphql"
_GRID_SS = "https://api-op.grid.gg/live-data-feed/series-state/graphql"


def _grid(url, query):
    if not _GRID_KEY:
        return None
    try:
        body = json.dumps({"query": query}).encode()
        req = _u.Request(url, data=body, headers={"x-api-key": _GRID_KEY, "Content-Type": "application/json"})
        with _u.urlopen(req, timeout=10) as r:
            return (json.loads(r.read().decode()) or {}).get("data")
    except Exception:
        return None


def _grid_state(sid):
    # Known-good fields only (format/games subfields differ in the schema — add later if needed).
    q = ('{ seriesState(id:"%s") { started finished valid '
         'teams { name score won players { name kills deaths } } } }' % sid)
    d = _grid(_GRID_SS, q)
    return (d or {}).get("seriesState") if d else None


_GRID_TITLE_LABELS = [("counter", "CS2"), ("ancient", "Dota 2"), ("dota", "Dota 2")]


def _grid_title_label(name):
    n = (name or "").lower()
    for kw, label in _GRID_TITLE_LABELS:
        if kw in n:
            return label
    return None


@router.get("/api/esports/grid/live")
def grid_live():
    """A currently-live CS2 or Dota 2 series via GRID (official): series score + per-player K/D.
    Returns the most-recently-started in-progress one. Data-only — Open Access has no stream."""
    if not _GRID_KEY:
        return {"live": False, "error": "GRID key not configured"}
    import datetime
    now = datetime.datetime.utcnow()
    lo = (now - datetime.timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hi = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    q = ('{ allSeries(first:40, orderBy: StartTimeScheduled, orderDirection: DESC, '
         'filter:{ startTimeScheduled:{ gte:"%s", lte:"%s" } }) '
         '{ edges { node { id startTimeScheduled title { name } tournament { name } '
         'teams { baseInfo { name } } } } } }' % (lo, hi))
    d = _grid(_GRID_CD, q)
    edges = (((d or {}).get("allSeries") or {}).get("edges") or [])

    def is_test(n):
        names = [((t.get("baseInfo") or {}).get("name") or "") for t in (n.get("teams") or [])]
        return any(x in ("CS2-1", "CS2-2", "DOTA-1", "DOTA-2", "TBD-1", "TBD-2") for x in names)

    cands = []
    for e in edges:
        node = e.get("node") or {}
        label = _grid_title_label(((node.get("title") or {}).get("name")))
        if label and not is_test(node):
            cands.append((node, label))
    for node, label in cands[:10]:
        st = _grid_state(node["id"])
        if st and st.get("started") and not st.get("finished"):
            def tm(t):
                return {"name": t.get("name"), "score": t.get("score"), "won": t.get("won"),
                        "players": [{"name": p.get("name"), "kills": p.get("kills"), "deaths": p.get("deaths")}
                                    for p in (t.get("players") or [])]}
            teams = st.get("teams") or []
            return {"live": True, "title": label, "seriesId": node["id"],
                    "tournament": (node.get("tournament") or {}).get("name"),
                    "teamA": tm(teams[0]) if len(teams) > 0 else None,
                    "teamB": tm(teams[1]) if len(teams) > 1 else None}
    return {"live": False}
