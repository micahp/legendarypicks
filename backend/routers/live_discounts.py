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
_SERIES = {"mlb": "KXMLBGAME", "nfl": "KXNFLGAME", "nba": "KXNBAGAME", "nhl": "KXNHLGAME",
           # WC knockouts: the market that matters is "to advance" (covers ET/pens), and it's
           # where the account's own best trades live (no public WP models -> stale prices).
           "wc": "KXWCADVANCE"}
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
# v0.3 (Micah): price level alone neither qualifies nor disqualifies — a 3c team with a 10%
# comeback probability is a GREAT buy. The rule is price vs ESPN's live win probability
# (the comeback estimate we lacked on the SD@LAD trap): anchor only where the market is
# underpricing the live WP by a real margin, absolute or ratio (ratio matters at low prices —
# "3 cents to make 100").
_WITCHING_MIN_EDGE = 0.05    # wp - price, in probability points
_WITCHING_MIN_RATIO = 1.75   # for prices under 10c: wp must be >= 1.75x the price
# Form gate: a team this cold is not a value candidate in ANY class — quality includes current
# form, not just season record. (last10 wins <= 3, or losing streak >= 4.)
_COLD_MAX_L10_WINS = 3
_COLD_STREAK = 4
_SPARK_N = 24
_KNIFE_MIN_DROP = 0.02
# Class C — PRE-PRICED DISCOUNT (spec: docs/SPEC-live-discounts-widget.md). Level is computed
# PREGAME and immutable; live price touching it fires the card. Sovereign: WP never gates it.
_PREPRICED_K = 0.35            # level = k x pregame (the MEX fill was ~0.28x)
_PREPRICED_MIN_PREGAME = 0.30  # only real contested sides get a level, never longshots
_PREPRICED_FLOOR = 0.05        # fee/noise floor
# Class D — GIFT FADE (Micah's ARG-EGY receipt, Jul-7: bought EGY 29c two minutes after
# Argentina's penalty save, banked 83c, +2.6R). The favorite missing a GIFT chance (penalty
# saved/missed) while NOT leading is real information about THIS game; the market underprices
# the dog because "quality comes back." Fade window decays fast.
_GIFT_WINDOW_MIN = 20          # minutes after the miss during which the card shows

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
        # Class C levels: computed pregame, IMMUTABLE (INSERT OR IGNORE only) — the
        # immutability is what makes it a resting bid rather than a chase.
        con.execute("""CREATE TABLE IF NOT EXISTS live_discount_levels(
            ticker TEXT PRIMARY KEY, league TEXT NOT NULL, team TEXT NOT NULL,
            level REAL NOT NULL, pregame REAL NOT NULL, k REAL NOT NULL,
            computed_at TEXT NOT NULL)""")
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
    if m:
        w, l = int(m.group(1)), int(m.group(2))
        # small-sample guard: "2-0" from a 3-game WC group stage is not a cold streak —
        # the low-wins rule only means something with a real sample behind it
        if w + l >= 8 and w <= _COLD_MAX_L10_WINS:
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


def _live_wp_home(league, game_id):
    """Latest ESPN live HOME win probability for an in-progress game — the state-based
    comeback estimate every value judgment needs (summary endpoint, cached ttl 20s; called
    lazily only for games that pass the cheap gates, and _get dedupes repeat calls)."""
    try:
        _, path = espn._check(league)
        d = espn._get(espn._SITE.format(path=path) + f"/summary?event={game_id}", ttl=20)
        wp = d.get("winprobability") or []
        if wp:
            v = wp[-1].get("homeWinPercentage")
            return float(v) if v is not None else None
    except Exception:
        return None
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


def _gift_events(league, game_id, home_name, away_name):
    """Soccer gift-chances the favorite wasted: penalty saved/missed keyEvents from the ESPN
    summary (same cached _get). -> [(side 'home'|'away', minute|None, event_text)].
    WC/soccer only for now — the MLB analog (bases loaded, no runs) comes later."""
    if league != "wc":
        return []
    try:
        _, path = espn._check(league)
        d = espn._get(espn._SITE.format(path=path) + f"/summary?event={game_id}", ttl=20)
    except Exception:
        return []
    out = []
    for e in (d.get("keyEvents") or []):
        tx = ((e.get("type") or {}).get("text") or "")
        low = tx.lower()
        if "penalty" not in low or not ("saved" in low or "missed" in low):
            continue
        team = ((e.get("team") or {}).get("displayName") or "").lower()
        clock = ((e.get("clock") or {}).get("displayValue") or "")
        m = re.search(r"(\d+)", clock)
        minute = int(m.group(1)) if m else None
        hn, an = (home_name or "").lower(), (away_name or "").lower()
        side = None
        if team and hn and (team in hn or hn in team):
            side = "home"
        elif team and an and (team in an or an in team):
            side = "away"
        if side:
            out.append((side, minute, tx))
    return out


def _time_left_ok(league, g):
    """Class C guard: only fire while enough game remains for the discount to be reachable —
    a level touched in the 89th minute is usually correct pricing, not value."""
    if league == "mlb":
        return (g.get("period") or 0) <= 7
    if league == "wc":
        m = re.search(r"(\d+)'", f"{g.get('status_detail') or ''} {g.get('clock') or ''}")
        if m:
            return int(m.group(1)) <= 70
        return (g.get("period") or 1) <= 1  # minute unknown: 1st half ok, be conservative after
    return True


def _set_level(con, league, ticker, team, pregame, meta_row):
    """Compute the pre-priced level ONCE, pregame. Eligibility: real contested side, not cold."""
    if pregame is None or pregame < _PREPRICED_MIN_PREGAME or _is_cold(meta_row):
        return
    level = max(_PREPRICED_FLOOR, round(_PREPRICED_K * pregame, 2))
    con.execute("""INSERT OR IGNORE INTO live_discount_levels(ticker, league, team, level,
                   pregame, k, computed_at) VALUES (?,?,?,?,?,?,?)""",
                (ticker, league, team, level, pregame, _PREPRICED_K,
                 dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")))


def _get_level(con, ticker):
    return con.execute("SELECT level, pregame, k FROM live_discount_levels WHERE ticker=?",
                       (ticker,)).fetchone()


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


def wc_event_markets(game_id, game_date=None):
    """Exact, currently tradable Kalshi advance markets for one ESPN WC event.

    This is intentionally a market board, not a discount classifier. Broadcast intelligence
    decides whether new match-specific information creates a divergence; this function only
    grounds that decision in the two real event sides and their observed price history.
    """
    games = espn.games("wc", game_date) if game_date else espn.games("wc")
    game = next((g for g in games if str(g.get("game_id")) == str(game_id)), None)
    if not game or game.get("state") not in ("pre", "in"):
        return []

    h, a = game.get("home") or {}, game.get("away") or {}
    hab, aab = h.get("abbrev"), a.get("abbrev")
    if not hab or not aab:
        return []
    token = _et_token(game["date"])
    pair, rpair = f"{aab}{hab}", f"{hab}{aab}"
    by_team = {}
    for market in _kalshi_markets(_SERIES["wc"]):
        ticker = market.get("ticker", "")
        event_ticker, _, side = ticker.rpartition("-")
        if token in event_ticker and (event_ticker.endswith(pair) or event_ticker.endswith(rpair)):
            by_team[side] = market

    now = int(time.time())
    start_ts = _game_start_ts(game)
    board = []
    with closing(_db()) as con:
        for team, team_data in ((hab, h), (aab, a)):
            market = by_team.get(team)
            if not market:
                continue
            price = _yes_price(market)
            if price is None:
                continue
            _snapshot(con, market["ticker"], price)
            pregame, _ = _pregame_ref(con, market["ticker"], start_ts, market)
            previous = con.execute(
                "SELECT price FROM live_price_snapshots WHERE ticker=? AND ts<? "
                "ORDER BY ts DESC LIMIT 1", (market["ticker"], now - 45)).fetchone()
            opening = con.execute(
                "SELECT price FROM live_price_snapshots WHERE ticker=? ORDER BY ts LIMIT 1",
                (market["ticker"],)).fetchone()
            board.append({
                "market_id": f"kalshi:{market['ticker']}",
                "kind": "match",
                "team": team,
                "selection": team_data.get("name") or team,
                "market": "to advance",
                "price": price,
                "previous_price": previous[0] if previous else None,
                "opening_price": pregame if pregame is not None else (opening[0] if opening else None),
                "source": "Kalshi",
                "as_of": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "tradable": market.get("status") not in ("closed", "settled", "finalized"),
            })
        con.commit()
    return board


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
            # MLB events run away+home (26JUL042210SDLAD for SD@LAD); WC advance events run
            # home+away (26JUL05MEXENG for ENG@MEX) — accept either order.
            pair = f"{k(aab)}{k(hab)}"
            rpair = f"{k(hab)}{k(aab)}"
            by_team = {}
            for m in markets:
                tk = m.get("ticker", "")
                ev, _, side = tk.rpartition("-")
                if token in ev and (ev.endswith(pair) or ev.endswith(rpair)):
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
                # Class C: price the discount NOW, while the judge is calm (immutable once set)
                for team, (m, price, _pg, _src, _opp) in prices.items():
                    _set_level(con, league, m["ticker"], team, price, meta.get(team))
                fav = max(prices.items(), key=lambda kv: kv[1][1], default=None)
                upcoming.append({"matchup": f"{aab} @ {hab}", "start": g["date"],
                                 "fav": fav[0] if fav else None,
                                 "fav_price": fav[1][1] if fav else None})
            elif state == "post":
                _resolve(con, g)
            elif state == "in":
                for team, (m, price, pregame, pregame_src, opp) in prices.items():
                    # C. PRE-PRICED DISCOUNT — sovereign, league-agnostic: the level was set
                    # pregame; live price touching it IS the signal. WP/evidence never gate it.
                    lvl = _get_level(con, m["ticker"])
                    if lvl and price <= lvl[0] and _time_left_ok(league, g):
                        spark_c = _spark(con, m["ticker"])
                        card = {
                            "cls": "PREPRICED",
                            "league": league.upper(), "game_id": str(g["game_id"]),
                            "matchup": f"{aab} @ {hab}", "team": team, "opp": opp,
                            "team_name": (h if team == hab else a).get("name"),
                            "score": f"{int(a.get('score') or 0)}\u2013{int(h.get('score') or 0)}",
                            "inning": inning, "status_detail": g.get("status_detail"),
                            "price": price, "pregame": lvl[1], "pregame_source": "level_basis",
                            "level": lvl[0], "level_k": lvl[2],
                            "spark": spark_c, "knife": _knife(spark_c), "ticker": m["ticker"],
                            "rank": rank.get(team), "opp_rank": rank.get(opp),
                            "last10": (meta.get(team) or {}).get("last10"),
                            "streak": (meta.get(team) or {}).get("streak"),
                        }
                        cards.append(card)
                        _fire(con, league, card["game_id"], m["ticker"], "PREPRICED", team,
                              price, lvl[1], {"level": lvl[0], "k": lvl[2],
                                              "state": g.get("status_detail")})
                    if league != "mlb":
                        continue  # Classes A/B are MLB mechanics (innings, base-out evidence)
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
                        wp_home = _live_wp_home(league, g["game_id"])
                        wp = None if wp_home is None else \
                            round(wp_home if team == hab else 1 - wp_home, 3)
                        # If the live WP says the market is already fair or rich, there is no
                        # value claim to make — evidence or not.
                        if wp is not None and wp <= price:
                            continue
                        card = dict(base, cls="DISCOUNT", evidence=evidence, wp=wp,
                                    edge=None if wp is None else round(wp - price, 3))
                        cards.append(card)
                        _fire(con, league, card["game_id"], m["ticker"], "DISCOUNT", team,
                              price, pregame, {"inning": inning, "deficit": deficit,
                                               "score": card["score"], "evidence": evidence,
                                               "wp": wp})
                # D. GIFT FADE — the favorite wasted a gift chance (penalty saved/missed)
                # while NOT leading: fade side = the dog, whose price lags because the market
                # keeps assuming "quality comes back." Event-driven and sovereign (no WP);
                # decays after _GIFT_WINDOW_MIN. Born from a real +2.6R fill (ARG-EGY Jul-7).
                for side, minute, tx in _gift_events(league, g["game_id"], h.get("name"), a.get("name")):
                    fav_t = hab if side == "home" else aab
                    dog_t = aab if side == "home" else hab
                    fav_row, dog_row = prices.get(fav_t), prices.get(dog_t)
                    if not fav_row or not dog_row:
                        continue
                    if not fav_row[2] or fav_row[2] < _QUALITY_MIN_PREGAME:
                        continue  # the misser must be the pregame favorite for the fade to mean anything
                    fav_sc = (h.get("score") or 0) if side == "home" else (a.get("score") or 0)
                    dog_sc = (a.get("score") or 0) if side == "home" else (h.get("score") or 0)
                    if fav_sc > dog_sc:
                        continue  # favorite leads anyway: gift already forgiven, no fade
                    mn = re.search(r"(\d+)", str(g.get("status_detail") or g.get("clock") or ""))
                    now_min = int(mn.group(1)) if mn else None
                    if minute is not None and now_min is not None and now_min - minute > _GIFT_WINDOW_MIN:
                        continue  # window closed — "that shit doesn't last long"
                    m_d, price_d, pregame_d, pregame_src_d, opp_d = dog_row
                    spark_d = _spark(con, m_d["ticker"])
                    ev_txt = f"{fav_t} {tx.lower()} ({minute}') while not leading" if minute \
                        else f"{fav_t} {tx.lower()} while not leading"
                    card = {
                        "cls": "GIFT_FADE",
                        "league": league.upper(), "game_id": str(g["game_id"]),
                        "matchup": f"{aab} @ {hab}", "team": dog_t, "opp": fav_t,
                        "team_name": (a if dog_t == aab else h).get("name"),
                        "score": f"{int(a.get('score') or 0)}–{int(h.get('score') or 0)}",
                        "inning": inning, "status_detail": g.get("status_detail"),
                        "price": price_d, "pregame": pregame_d, "pregame_source": pregame_src_d,
                        "spark": spark_d, "knife": _knife(spark_d), "ticker": m_d["ticker"],
                        "rank": rank.get(dog_t), "opp_rank": rank.get(fav_t),
                        "last10": (meta.get(dog_t) or {}).get("last10"),
                        "streak": (meta.get(dog_t) or {}).get("streak"),
                        "evidence": ev_txt,
                    }
                    cards.append(card)
                    _fire(con, league, card["game_id"], m_d["ticker"], "GIFT_FADE", dog_t,
                          price_d, pregame_d, {"event": tx, "minute": minute,
                                               "favorite": fav_t, "fav_pregame": fav_row[2]})
                # B. WITCHING HOUR — close game, late, anchored on real EDGE: the side whose
                # live Kalshi price sits meaningfully under ESPN's live win probability
                # (absolute points, or ratio for cheap sides — "3 cents to make 100" is a take
                # when the comeback probability supports it). Price level alone neither
                # qualifies nor disqualifies (v0.3); no WP available -> no value claim -> no
                # card ("not that I know what their comeback probability was" — exactly).
                # Cold-form gate stays: state-based WP doesn't know about a 7-game skid.
                if league == "mlb" and inning >= _WITCHING_MIN_INNING and abs(diff) <= _WITCHING_MAX_DIFF and prices:
                    anchor = anchor_wp = anchor_edge = None
                    wp_home = _live_wp_home(league, g["game_id"])
                    if wp_home is not None:
                        for team, tup in sorted(prices.items(), key=lambda kv: kv[1][1]):
                            p = tup[1]
                            if _is_cold(meta.get(team)):
                                continue
                            wp = wp_home if team == hab else 1 - wp_home
                            edge = wp - p
                            if edge >= _WITCHING_MIN_EDGE or \
                                    (p < 0.10 and wp >= p * _WITCHING_MIN_RATIO):
                                anchor, anchor_wp, anchor_edge = (team, tup), round(wp, 3), round(edge, 3)
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
                            "wp": anchor_wp, "edge": anchor_edge,
                        }
                        cards.append(card)
                        _fire(con, league, card["game_id"], m["ticker"], "WITCHING_HOUR", team,
                              price, pregame, {"inning": inning, "diff": diff,
                                               "score": card["score"], "wp": anchor_wp})
        con.execute("DELETE FROM live_price_snapshots WHERE ts < ?", (int(time.time()) - 3 * 86400,))
        con.commit()

    upcoming.sort(key=lambda u: u["start"])
    return {"league": league.upper(),
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "cards": cards, "upcoming": upcoming[:6], "unmatched": unmatched}


@router.get("/api/live/discounts")
def live_discounts(league: str = Query("mlb")):
    """league accepts a comma list ("mlb,wc") — the scores page merges leagues; future
    per-league pages pass a single league. Each league is cached and fails independently
    (one venue's hiccup never blanks another's cards)."""
    leagues = [l.strip().lower() for l in league.split(",") if l.strip()]
    bad = [l for l in leagues if l not in _SERIES]
    if bad or not leagues:
        raise HTTPException(400, f"league must be one of {sorted(_SERIES)}")
    now = time.time()
    payloads, errors = [], []
    for lg in leagues:
        hit = _cache.get(lg)
        if hit and now - hit[0] < _CACHE_TTL:
            payloads.append(hit[1])
            continue
        try:
            p = _build(lg)
            _cache[lg] = (now, p)
            payloads.append(p)
        except Exception as e:
            if hit:
                payloads.append(hit[1])
            else:
                errors.append(f"{lg}: {e}")
    if not payloads:
        raise HTTPException(502, f"live discounts unavailable: {'; '.join(errors)}")
    if len(payloads) == 1 and not errors:
        return payloads[0]
    merged = {"league": ",".join(p["league"] for p in payloads),
              "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
              "cards": [c for p in payloads for c in p["cards"]],
              "upcoming": sorted((u for p in payloads for u in p["upcoming"]),
                                 key=lambda u: u["start"])[:6],
              "unmatched": [x for p in payloads for x in p["unmatched"]]}
    if errors:
        merged["degraded"] = errors
    return merged


@router.get("/api/live/discounts/log")
def discounts_log(league: str = Query("mlb"), limit: int = Query(50, ge=1, le=500)):
    """The receipts: every card ever fired, with its resolution — the widget's own record."""
    with closing(_db()) as con:
        con.row_factory = __import__("sqlite3").Row
        rows = con.execute("""SELECT * FROM live_discount_log WHERE league=?
                              ORDER BY fired_at DESC LIMIT ?""", (league.lower(), limit)).fetchall()
    return [dict(r) for r in rows]
