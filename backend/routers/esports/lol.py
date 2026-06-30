"""lol.py — LoL / MSI: pre-game predictions, live match state, Bovada market edge."""

import json
import time
import datetime
import urllib.request as _u

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .common import _amer_to_p

router = APIRouter()

_LOL_KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"  # public lolesports.com web key

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

_LOL_ALIASES = {
    "hanwha": "HLE", "bilibili": "BLG", "t1": "T1", "g2": "G2", "top esports": "TES",
    "lyon": "LYON", "karmine": "KC", "secret whales": "TSW", "team liquid": "TLAW",
    "furia": "FUR", "deep cross": "DCG",
}

_BOV_MSI = ("https://www.bovada.lv/services/sports/event/coupon/events/A/description/"
            "esports/league-of-legends/mid-season-invitational?marketFilterId=def&liveOnly=false&lang=en")
_bov_cache = {"t": 0.0, "data": {}}

_ddv_cache = {"t": 0.0, "v": None}


# --- Helpers ---------------------------------------------------------------

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


def _lol_window(gid):
    """Latest live frame (gold/kills/objectives per side) from the LoL livestats window."""
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


def _ddragon_ver():
    """Latest Data Dragon version (for champion portraits). Cached ~1h."""
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


# --- Routes ----------------------------------------------------------------

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

    order = {"inProgress": 0, "unstarted": 1, "completed": 2}
    matches.sort(key=lambda x: (order.get(x["state"], 1), x["startTime"] or ""))
    return {"event": "MSI 2026", "model": "power-ranking prior (Sheep) · Elo · Bo5",
            "matches": matches}


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
