"""routers/live_discounts.py — the "Cheap Quality, Live" widget backend.

Surfaces, in real time, the setups the prediction-market trading strategy buys
(docs/SPEC-live-discounts-widget.md): a quality team in an early reversible dip (DISCOUNT),
or a close game late (WITCHING_HOUR). Live prices from Kalshi's public API (no auth), game
state from the existing ESPN backend, quality prior from the existing strength rankings.

League-agnostic by construction: /api/live/discounts?league=mlb today; NFL/NBA/NHL activate
by series map when in season, and the future per-league pages (Leagues hub / esports tab)
mount the same endpoint with their own league param.

v0 poller model: refresh-on-request with a short server-side cache — every refresh also
appends price snapshots (sparkline + knife state) and fires/resolves receipt rows in
live_discount_log, so each surfaced card has a checkable lifecycle.
"""
import json
import re
import time
import datetime as dt
import urllib.request as _u
from contextlib import closing

from fastapi import APIRouter, HTTPException, Query

from _core import _db
import espn_client as espn

router = APIRouter()

_KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
_SERIES = {"mlb": "KXMLBGAME", "nfl": "KXNFLGAME", "nba": "KXNBAGAME", "nhl": "KXNHLGAME"}
# ESPN abbrev -> Kalshi ticker abbrev, where they differ. Unmatched games are reported in the
# payload's `unmatched` list rather than silently dropped.
_ESPN_TO_KALSHI = {"mlb": {"ARI": "AZ", "CHW": "CWS", "OAK": "ATH"}}

_CACHE_TTL = 40          # seconds; widget polls at ~45s
_DIP_CENTS = 0.15        # live price this far under pregame = dip
_QUALITY_MIN_PREGAME = 0.55
_REVERSIBLE_MAX_DEFICIT = 3
_REVERSIBLE_MAX_INNING = 6   # "before the 7th"
_WITCHING_MIN_INNING = 7
_WITCHING_MAX_DIFF = 2
# The market's own definition of "close": witching hour requires the cheap side to still be
# genuinely contested. A 3c team down late is cheap-AND-CORRECT (the SD@LAD Jul-4 trap: our own
# game story had SD on a 7-game losing streak) — never a card, no matter the run diff.
_WITCHING_MIN_PRICE = 0.25
# Form gate: a team this cold is not a value candidate in ANY class — quality includes current
# form, not just season record. (last10 wins <= 3, or losing streak >= 4.)
_COLD_MAX_L10_WINS = 3
_COLD_STREAK = 4
_SPARK_N = 24
_KNIFE_MIN_DROP = 0.02

_cache = {}            # league -> (ts, payload)
_strength_cache = {}   # league -> (ts, rank_map, meta_map)


def _ensure_tables():
    with closing(_db()) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS live_price_snapshots(
            ticker TEXT NOT NULL, ts INTEGER NOT NULL, price REAL NOT NULL)""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_lps_ticker ON live_price_snapshots(ticker, ts)")
        con.execute("""CREATE TABLE IF NOT EXISTS live_discount_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league TEXT NOT NULL, game_id TEXT NOT NULL, ticker TEXT NOT NULL,
            cls TEXT NOT NULL, team TEXT NOT NULL,
            fired_at TEXT NOT NULL, price REAL, pregame REAL, detail TEXT,
            result TEXT, resolved_at TEXT)""")
        con.commit()


_ensure_tables()


def _kalshi_markets(series):
    req = _u.Request(f"{_KALSHI_BASE}/markets?series_ticker={series}&limit=200",
                     headers={"Accept": "application/json"})
    with _u.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode()).get("markets", [])


def _dollars(m, key):
    v = m.get(f"{key}_dollars")
    if v is not None:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    v = m.get(key)  # integer-cents fallback
    return (v / 100.0) if isinstance(v, (int, float)) and v else None


def _yes_price(m):
    """Best live yes-price estimate: mid of the yes book (derived from the no side when the
    yes fields are absent), else last trade."""
    yes_bid = _dollars(m, "yes_bid")
    yes_ask = _dollars(m, "yes_ask")
    no_bid, no_ask = _dollars(m, "no_bid"), _dollars(m, "no_ask")
    if yes_bid is None and no_ask is not None:
        yes_bid = round(1.0 - no_ask, 4)
    if yes_ask is None and no_bid is not None:
        yes_ask = round(1.0 - no_bid, 4)
    if yes_bid is not None and yes_ask is not None and 0 < yes_bid <= yes_ask < 1:
        return round((yes_bid + yes_ask) / 2, 4)
    return _dollars(m, "last_price")


def _et_token(iso_utc):
    """Kalshi tickers bucket games by ET calendar date: '2026-07-04T15:05Z' -> '26JUL04'."""
    d = dt.datetime.strptime(iso_utc[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=dt.timezone.utc)
    et = d.astimezone(dt.timezone(dt.timedelta(hours=-4)))  # EDT; MLB season is DST
    return et.strftime("%y%b%d").upper()


def _strength(league):
    now = time.time()
    hit = _strength_cache.get(league)
    if hit and now - hit[0] < 600:
        return hit[1], hit[2]
    rows = espn.team_strength(league)
    rank = {r["abbrev"]: i + 1 for i, r in enumerate(rows)}
    meta = {r["abbrev"]: {"win_pct": r.get("win_pct"), "last10": r.get("last10"),
                          "streak": r.get("streak")} for r in rows}
    _strength_cache[league] = (now, rank, meta)
    return rank, meta


def _is_cold(meta_row):
    """Current-form gate. The game story narrates this signal ('stumble in on a seven-game
    losing streak') — the widget must respect it too."""
    if not meta_row:
        return False
    l10 = meta_row.get("last10") or ""
    m = re.match(r"(\d+)-(\d+)", l10)
    if m and int(m.group(1)) <= _COLD_MAX_L10_WINS:
        return True
    st = meta_row.get("streak") or ""
    if st.startswith("L") and st[1:].isdigit() and int(st[1:]) >= _COLD_STREAK:
        return True
    return False


def _situations(league):
    """game_id -> live base/out situation from the raw ESPN scoreboard. Uses the SAME cached
    URL espn_client.games() reads (ttl 20s), so this adds no upstream traffic — it just keeps
    the fields games() discards. MLB shape: {onFirst,onSecond,onThird,outs,balls,strikes,...}."""
    try:
        _, path = espn._check(league)
        d = espn._get(espn._SITE.format(path=path) + "/scoreboard", ttl=20)
    except Exception:
        return {}
    out = {}
    for ev in d.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        sit = comp.get("situation")
        if sit:
            out[str(ev.get("id"))] = sit
    return out


def _rally_evidence(sit, team_is_home, status_detail):
    """The no-knife-catching rule: a dip is only buyable when the turn is VISIBLY starting —
    the trailing team at bat right now with runners on and outs to work with. No evidence,
    no card; a falling price alone is a knife, not a signal. (MLB mechanic; other leagues
    get their own evidence definitions — possession/red zone for NFL — when they activate.)"""
    if not sit:
        return None
    sd = (status_detail or "").lower()
    at_bat_home = sd.startswith("bot")
    at_bat_away = sd.startswith("top")
    if not (at_bat_home or at_bat_away) or ((at_bat_home) != bool(team_is_home)):
        return None
    runners = sum(1 for k in ("onFirst", "onSecond", "onThird") if sit.get(k))
    outs = sit.get("outs")
    if runners >= 1 and isinstance(outs, int) and outs <= 2:
        return f"{runners} on, {outs} out{'s' if outs != 1 else ''}, at bat"
    return None


def _snapshot(con, ticker, price):
    con.execute("INSERT INTO live_price_snapshots(ticker, ts, price) VALUES (?,?,?)",
                (ticker, int(time.time()), price))


def _spark(con, ticker):
    rows = con.execute("SELECT price FROM live_price_snapshots WHERE ticker=? ORDER BY ts DESC LIMIT ?",
                       (ticker, _SPARK_N)).fetchall()
    return [r[0] for r in reversed(rows)]


def _knife(spark):
    """Jun-8 entry-timing lesson as a label: is the price still falling or stabilizing?"""
    tail = spark[-3:]
    if len(tail) == 3 and tail[0] >= tail[1] >= tail[2] and (tail[0] - tail[2]) >= _KNIFE_MIN_DROP:
        return "falling"
    return "stabilizing"


def _pregame_ref(con, ticker, game_start_ts, market):
    row = con.execute("SELECT price FROM live_price_snapshots WHERE ticker=? AND ts<=? ORDER BY ts DESC LIMIT 1",
                      (ticker, game_start_ts)).fetchone()
    if row:
        return row[0], "snapshot"
    prev = _dollars(market, "previous_price")
    if prev:
        return prev, "kalshi_previous_close"
    return None, None


def _fire(con, league, game_id, ticker, cls, team, price, pregame, detail):
    dup = con.execute("SELECT 1 FROM live_discount_log WHERE game_id=? AND cls=? AND team=?",
                      (game_id, cls, team)).fetchone()
    if dup:
        return
    con.execute("""INSERT INTO live_discount_log(league, game_id, ticker, cls, team, fired_at,
                   price, pregame, detail) VALUES (?,?,?,?,?,?,?,?,?)""",
                (league, game_id, ticker, cls, team,
                 dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                 price, pregame, json.dumps(detail)))


def _resolve(con, game):
    """Game went final: stamp the outcome onto any unresolved receipts for it."""
    h, a = game["home"], game["away"]
    if h.get("score") is None or a.get("score") is None:
        return
    winner = h["abbrev"] if (h["score"] or 0) > (a["score"] or 0) else a["abbrev"]
    con.execute("UPDATE live_discount_log SET result=?, resolved_at=? WHERE game_id=? AND result IS NULL",
                (winner, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                 str(game["game_id"])))


def _game_start_ts(g):
    d = dt.datetime.strptime(g["date"][:16], "%Y-%m-%dT%H:%M").replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp())


def _build(league):
    series = _SERIES[league]
    games = espn.games(league)
    markets = _kalshi_markets(series)
    rank, meta = _strength(league)
    sits = _situations(league)
    alias = _ESPN_TO_KALSHI.get(league, {})
    k = lambda ab: alias.get(ab, ab)

    cards, upcoming, unmatched = [], [], []
    with closing(_db()) as con:
        for g in games:
            h, a = g.get("home") or {}, g.get("away") or {}
            hab, aab = h.get("abbrev"), a.get("abbrev")
            if not hab or not aab:
                continue
            token = _et_token(g["date"])
            pair = f"{k(aab)}{k(hab)}"
            # per-team market: ...-26JUL04HHMM<AWAY><HOME>-<TEAM>
            by_team = {}
            for m in markets:
                tk = m.get("ticker", "")
                ev, _, side = tk.rpartition("-")
                if token in ev and ev.endswith(pair):
                    by_team[side] = m
            if not by_team:
                if g.get("state") in ("pre", "in"):
                    unmatched.append({"matchup": f"{aab} @ {hab}", "token": token, "pair": pair})
                continue

            start_ts = _game_start_ts(g)
            state = g.get("state")
            inning = g.get("period") or 0
            diff = (h.get("score") or 0) - (a.get("score") or 0)

            prices = {}
            for team_ab_espn, opp_ab in ((hab, aab), (aab, hab)):
                m = by_team.get(k(team_ab_espn))
                if not m:
                    continue
                price = _yes_price(m)
                if price is None:
                    continue
                if state in ("pre", "in"):
                    _snapshot(con, m["ticker"], price)
                pregame, pregame_src = _pregame_ref(con, m["ticker"], start_ts, m)
                prices[team_ab_espn] = (m, price, pregame, pregame_src, opp_ab)

            if state == "pre":
                fav = max(prices.items(), key=lambda kv: kv[1][1], default=None)
                upcoming.append({"matchup": f"{aab} @ {hab}", "start": g["date"],
                                 "fav": fav[0] if fav else None,
                                 "fav_price": fav[1][1] if fav else None})
            elif state == "post":
                _resolve(con, g)
            elif state == "in":
                for team, (m, price, pregame, pregame_src, opp) in prices.items():
                    spark = _spark(con, m["ticker"])
                    team_score = (h.get("score") or 0) if team == hab else (a.get("score") or 0)
                    opp_score = (a.get("score") or 0) if team == hab else (h.get("score") or 0)
                    deficit = opp_score - team_score
                    base = {
                        "league": league.upper(), "game_id": str(g["game_id"]),
                        "matchup": f"{aab} @ {hab}", "team": team, "opp": opp,
                        "team_name": (h if team == hab else a).get("name"),
                        "score": f"{int(a.get('score') or 0)}–{int(h.get('score') or 0)}",
                        "inning": inning, "status_detail": g.get("status_detail"),
                        "price": price, "pregame": pregame, "pregame_source": pregame_src,
                        "spark": spark, "knife": _knife(spark), "ticker": m["ticker"],
                        "rank": rank.get(team), "opp_rank": rank.get(opp),
                        "last10": (meta.get(team) or {}).get("last10"),
                        "streak": (meta.get(team) or {}).get("streak"),
                    }
                    # A. QUALITY DIP — model-favored quality team IN FORM, price well under
                    # pregame, deficit small with time left, AND the turn visibly starting
                    # (rally evidence: at bat, runners on, outs left). Quality includes current
                    # form — a cold-streaking team is never a buy-the-dip candidate — and a dip
                    # with no live evidence is a knife, not a discount: we buy the visible
                    # turn, never the fall.
                    evidence = _rally_evidence(sits.get(str(g["game_id"])), team == hab,
                                               g.get("status_detail"))
                    if (pregame and pregame >= _QUALITY_MIN_PREGAME
                            and rank.get(team) and rank.get(opp) and rank[team] < rank[opp]
                            and not _is_cold(meta.get(team))
                            and price <= pregame - _DIP_CENTS
                            and 0 <= deficit <= _REVERSIBLE_MAX_DEFICIT
                            and inning <= _REVERSIBLE_MAX_INNING
                            and evidence):
                        card = dict(base, cls="DISCOUNT", evidence=evidence)
                        cards.append(card)
                        _fire(con, league, card["game_id"], m["ticker"], "DISCOUNT", team,
                              price, pregame, {"inning": inning, "deficit": deficit,
                                               "score": card["score"], "evidence": evidence})
                # B. WITCHING HOUR — close game, late, and CONTESTED BY THE MARKET'S OWN
                # PRICING. Run diff alone lies: SD@LAD Jul-4 was "0–2 in the 8th" by score but
                # 3c/97c by price — cheap-and-correct, and our own game story had SD on a
                # 7-game losing streak. Gates: the anchored side must be priced inside the
                # contested band AND not cold-streaking; prefer the cheaper qualifying side.
                if inning >= _WITCHING_MIN_INNING and abs(diff) <= _WITCHING_MAX_DIFF and prices:
                    anchor = None
                    for team, tup in sorted(prices.items(), key=lambda kv: kv[1][1]):
                        p = tup[1]
                        if p < _WITCHING_MIN_PRICE or p > 1 - _WITCHING_MIN_PRICE:
                            continue
                        if _is_cold(meta.get(team)):
                            continue
                        anchor = (team, tup)
                        break
                    if anchor:
                        team, (m, price, pregame, pregame_src, opp) = anchor
                        spark = _spark(con, m["ticker"])
                        card = {
                            "cls": "WITCHING_HOUR",
                            "league": league.upper(), "game_id": str(g["game_id"]),
                            "matchup": f"{aab} @ {hab}", "team": team, "opp": opp,
                            "team_name": (h if team == hab else a).get("name"),
                            "score": f"{int(a.get('score') or 0)}–{int(h.get('score') or 0)}",
                            "inning": inning, "status_detail": g.get("status_detail"),
                            "price": price, "pregame": pregame, "pregame_source": pregame_src,
                            "spark": spark, "knife": _knife(spark), "ticker": m["ticker"],
                            "rank": rank.get(team), "opp_rank": rank.get(opp),
                            "last10": (meta.get(team) or {}).get("last10"),
                            "streak": (meta.get(team) or {}).get("streak"),
                        }
                        cards.append(card)
                        _fire(con, league, card["game_id"], m["ticker"], "WITCHING_HOUR", team,
                              price, pregame, {"inning": inning, "diff": diff, "score": card["score"]})
        con.execute("DELETE FROM live_price_snapshots WHERE ts < ?", (int(time.time()) - 3 * 86400,))
        con.commit()

    upcoming.sort(key=lambda u: u["start"])
    return {"league": league.upper(),
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "cards": cards, "upcoming": upcoming[:6], "unmatched": unmatched}


@router.get("/api/live/discounts")
def live_discounts(league: str = Query("mlb")):
    league = league.lower()
    if league not in _SERIES:
        raise HTTPException(400, f"league must be one of {sorted(_SERIES)}")
    now = time.time()
    hit = _cache.get(league)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    try:
        payload = _build(league)
    except Exception as e:  # Kalshi/ESPN hiccup: serve stale cache over a 500
        if hit:
            return hit[1]
        raise HTTPException(502, f"live discounts unavailable: {e}")
    _cache[league] = (now, payload)
    return payload


@router.get("/api/live/discounts/log")
def discounts_log(league: str = Query("mlb"), limit: int = Query(50, ge=1, le=500)):
    """The receipts: every card ever fired, with its resolution — the widget's own record."""
    with closing(_db()) as con:
        con.row_factory = __import__("sqlite3").Row
        rows = con.execute("""SELECT * FROM live_discount_log WHERE league=?
                              ORDER BY fired_at DESC LIMIT ?""", (league.lower(), limit)).fetchall()
    return [dict(r) for r in rows]
