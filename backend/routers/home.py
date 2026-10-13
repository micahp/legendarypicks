"""Homepage featured payload: the real numbers behind the hero slides and the chain cards.

READ-ONLY. GET /api/home/featured returns every piece the homepage shows, each chosen by a fixed
rule so the same database always gives the same page. Nothing here invents a number: a piece that
cannot be computed is null and `absent` names it with a reason; the frontend hides that slide or
card instead of drawing a placeholder.

Selection rules
  prop       Market receiving_yards, side over, NFL props captured in the last 36 hours that belong
             to a game that has not started (prop_games.start_time after now, UTC; a game with no
             start time is excluded). A finished game's line is never featured. For each
             player take the line offered by the most distinct sources (ties: the most recently
             captured line, then the higher line). Keep players whose line has at least 8 distinct
             sources and at least 20 settled games of history (hit_rate_n.season, from
             routers/props.py prop_history, called as is so hit rates and games equal the prop board
             chart). Pick the highest line; ties by more sources, then lowest player id. If nobody
             qualifies, relax once to at least 5 sources; if still nobody, the prop is null and
             `absent` says why. prop_history reads at most 100 games.
  game       Adopted model only (nfl_model.ADOPTED, label 'v1 points'), locked = 1. The most recent
             game (by gameday, gametime, game_id) with a final score in nfl_schedule and a row in
             projection_grades; if none, the next locked game not yet final whose kickoff is not in
             the past; if none, null. The line is the lock's own snapshot (or the lock row for older
             locks), never the live schedule.
  playoffs   Top five teams by p_playoffs (ties by team code) from the latest complete run, found
             with the same helpers as /api/nfl/playoff-odds. `sims` is the run's own params_json n.
  record     The adopted model's win-loss-push against the line for the latest locked season, from
             projection_grades via nfl_model.record_payload; null with no graded game against a line.
  chain      player = the featured prop's player with the recency-weighted projection that
             prop_history returns (null when the prop is null); game = the featured game; market =
             the featured game's model win probability beside the market's, from the locked
             moneylines with the vig removed (null if either moneyline is missing); season = the top
             playoff team and the next three.

Spread convention (nflverse): positive spread = home team favored. Our line is the projected home
margin read the same way. The pick is the side our line likes against the market: the away team
when our home margin is below the market spread, the home team when above; none when equal.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from contextlib import closing
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from _core import _db
import check_nfl_schedule_scores as cs
from routers import nfl_model
from routers import props as props_router
from routers.models import nfl as nfl_models

router = APIRouter()

PROP_LEAGUE = "nfl"
PROP_WINDOW_HOURS = 36
PROP_MIN_GAMES = 20
PROP_MARKET = "receiving_yards"
PROP_MIN_SOURCES = (8, 5)      # the rule, then its one stated relaxation
CHART_GAMES = 20
PLAYOFF_TOP_N = 5


def _f(x):
    return None if x is None else float(x)


def _now(now: Optional[dt.datetime]) -> dt.datetime:
    return now or dt.datetime.now(dt.timezone.utc)


def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(s: Optional[str]) -> Optional[dt.datetime]:
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------- prop

def featured_prop(con, now: dt.datetime) -> Dict[str, Any]:
    """Return {'prop': dict or None, 'reason': str or None, 'history': raw prop_history or None}."""
    cutoff = _iso(now - dt.timedelta(hours=PROP_WINDOW_HOURS))
    rows = con.execute(
        "SELECT p.id, p.player_id, p.market, p.line, p.captured_at, p.source, p.game_id "
        "FROM props p JOIN prop_games g ON g.id = p.game_id "
        "WHERE g.league = ? AND p.market = ? AND p.side = 'over' AND p.captured_at >= ? "
        "AND g.start_time > ? AND p.player_id IS NOT NULL ORDER BY p.captured_at, p.id",
        (PROP_LEAGUE, PROP_MARKET, cutoff, _iso(now))).fetchall()
    # Per player and line: the distinct sources offering it and its latest capture row.
    lines: Dict[Any, Dict[str, Any]] = {}
    for r in rows:                       # ascending, so the last row per line is the latest
        d = lines.setdefault((r[1], float(r[3])), {"sources": set(), "row": r})
        if r[5]:
            d["sources"].add(r[5])
        d["row"] = r
    # One line per player: most sources, then latest capture, then the higher line.
    consensus: Dict[Any, Any] = {}
    for (player_id, line), d in lines.items():
        stamp = _parse_ts(d["row"][4])
        key = (len(d["sources"]), stamp.timestamp() if stamp else 0.0, line)
        if player_id not in consensus or key > consensus[player_id][0]:
            consensus[player_id] = (key, d["row"], len(d["sources"]))
    best = None
    for min_sources in PROP_MIN_SOURCES:
        ranked = []
        for player_id, (key, r, n_src) in consensus.items():
            if n_src < min_sources:
                continue
            h = props_router.prop_history(player_id=player_id, market=PROP_MARKET, line=float(r[3]),
                                          side="over", league=PROP_LEAGUE)
            if h.get("error") or not h.get("games") or h["hit_rate_n"]["season"] < PROP_MIN_GAMES:
                continue
            # highest line first, then more sources, then lowest player id
            ranked.append(((-float(r[3]), -n_src, player_id), r, h, n_src))
        if ranked:
            _, r0, h0, n0 = min(ranked, key=lambda t: t[0])
            best = (r0, h0, n0)
            break
    if best is None:
        return {"prop": None, "history": None,
                "reason": "no upcoming game has a widely offered receiving yards line"}
    r, h, n_sources = best
    game = con.execute("SELECT home, away, date, start_time FROM prop_games WHERE id = ?",
                       (r[6],)).fetchone()
    recent = list(reversed(h["games"][:CHART_GAMES]))      # oldest first for the chart
    prop = {
        "player_id": h["player_id"], "player": h["player"], "team": h["team"],
        "market": h["market"], "line": float(r[3]), "side": "over",
        "matchup": ({"home": game[0], "away": game[1], "date": game[2], "start_time": game[3]}
                    if game else None),
        "hit_rate": h["hit_rate"], "hit_rate_n": h["hit_rate_n"],
        "games": [{"date": g["date"], "opponent": g["opponent"], "home": g["home"],
                   "value": g["value"], "hit": g["hit"]} for g in recent],
        "sources": n_sources,
        "source": {"line": "props board, offered by %d sources" % n_sources,
                   "history": "player game logs via /api/props/history",
                   "as_of": r[4]},
    }
    return {"prop": prop, "history": h, "reason": None}


# ---------------------------------------------------------------- game

def _no_vig(home_ml, away_ml) -> Optional[float]:
    """Home win probability from two American moneylines with the vig removed."""
    if home_ml is None or away_ml is None:
        return None

    def imp(ml):
        ml = float(ml)
        if ml == 0:
            return None
        return 100.0 / (ml + 100.0) if ml > 0 else -ml / (-ml + 100.0)

    h, a = imp(home_ml), imp(away_ml)
    if h is None or a is None or h + a <= 0:
        return None
    return h / (h + a)


def _pick(home: str, away: str, margin: float, spread: Optional[float]) -> Optional[Dict[str, Any]]:
    if spread is None or margin == spread:
        return None
    if margin < spread:                  # we rate home lower than the market does: take the away side
        return {"team": away, "line": spread, "gap": spread - margin}
    return {"team": home, "line": -spread, "gap": margin - spread}


def featured_game(con, now: dt.datetime) -> Dict[str, Any]:
    rows = con.execute(
        "SELECT g.game_id, g.season, g.week, g.home, g.away, g.proj_home, g.proj_away, "
        "       g.proj_margin, g.proj_total, g.p_home_win, g.locked_at, g.market_spread, "
        "       s.snapshot_id, s.spread_line, s.home_moneyline, s.away_moneyline, s.captured_at, "
        "       pg.ats_result, pg.margin_err, sc.gameday, sc.gametime, sc.home_score, "
        "       sc.away_score, sc.result "
        "FROM game_projections g "
        "JOIN nfl_schedule sc ON sc.game_id = g.game_id "
        "LEFT JOIN nfl_line_snapshots s ON s.snapshot_id = g.line_snapshot_id "
        "LEFT JOIN projection_grades pg ON pg.league = g.league AND pg.game_id = g.game_id "
        "     AND pg.model_version = g.model_version "
        "WHERE g.league = 'nfl' AND g.locked = 1 AND g.model_version = ?",
        (nfl_model.ADOPTED,)).fetchall()
    graded, upcoming = [], []
    for r in rows:
        final = r["home_score"] is not None and r["away_score"] is not None and r["result"] is not None
        kick = cs.kickoff_utc(r["gameday"], r["gametime"]) if r["gameday"] else None
        order = (r["gameday"] or "", r["gametime"] or "", r["game_id"])
        if final and r["margin_err"] is not None:
            graded.append((order, r, kick))
        elif not final and kick is not None and kick >= now:
            upcoming.append((order, r, kick))
    if graded:
        _, r, kick = max(graded, key=lambda t: t[0])
    elif upcoming:
        _, r, kick = min(upcoming, key=lambda t: t[0])
    else:
        return {"game": None,
                "reason": "no locked game of the adopted model has a final score and grade, "
                          "and none is upcoming"}
    names = {x[0]: x[1] for x in con.execute(
        "SELECT team, team_name FROM nfl_teams WHERE season = ?", (r["season"],))}
    snap = r["snapshot_id"] is not None
    spread = _f(r["spread_line"] if snap else r["market_spread"])
    margin = _f(r["proj_margin"])
    final = (r["home_score"] is not None and r["away_score"] is not None and r["result"] is not None)
    has_scores = r["proj_home"] is not None and r["proj_away"] is not None
    game = {
        "game_id": r["game_id"], "season": r["season"], "week": r["week"],
        "home": r["home"], "away": r["away"],
        "home_name": names.get(r["home"]), "away_name": names.get(r["away"]),
        "kickoff_utc": _iso(kick) if kick else None,
        "proj_home": _f(r["proj_home"]) if has_scores else None,
        "proj_away": _f(r["proj_away"]) if has_scores else None,
        "our_margin": margin, "our_total": _f(r["proj_total"]),
        "p_home_win": _f(r["p_home_win"]),
        "market_spread": spread,
        "pick": _pick(r["home"], r["away"], margin, spread),
        "final": {"home": _f(r["home_score"]), "away": _f(r["away_score"])} if final else None,
        "pick_result": r["ats_result"] if final else None,
        "model_label": nfl_model.describe(None, nfl_model.ADOPTED)["label"],
        "source": {"projection": "locked projection, %s" % nfl_model.ADOPTED,
                   "line": "nfl_line_snapshots" if snap else "lock row",
                   "as_of": r["locked_at"]},
        "_market_p_home": _no_vig(r["home_moneyline"], r["away_moneyline"]) if snap else None,
    }
    return {"game": game, "reason": None}


# ---------------------------------------------------------------- record

def featured_record(con) -> Dict[str, Any]:
    """Adopted model's against-the-line tally for the latest locked season (nfl_model.record_payload).
    `games` counts win + loss + push only; a graded game with no pick or no line is not in it."""
    row = con.execute("SELECT MAX(season) FROM game_projections WHERE league = 'nfl' AND locked = 1"
                      ).fetchone()
    if row is None or row[0] is None:
        return {"record": None, "reason": "no locked NFL projection exists"}
    season = int(row[0])
    mine = [r for r in nfl_model.record_payload(con, season) if r["version"] == nfl_model.ADOPTED]
    if not mine or not mine[0]["ats"]:
        return {"record": None, "reason": "no graded game for the adopted model in %d" % season}
    ats = mine[0]["ats"]
    w, l, p = ats["win"], ats["loss"], ats["push"]
    if w + l + p == 0:
        return {"record": None, "reason": "no graded game against a line for the adopted model"}
    return {"record": {"season": season, "win": w, "loss": l, "push": p, "games": w + l + p,
                       "model_label": mine[0]["label"],
                       "source": {"table": "projection_grades", "model_version": nfl_model.ADOPTED}},
            "reason": None}


# ---------------------------------------------------------------- playoff odds

def featured_playoffs(con) -> Dict[str, Any]:
    try:
        season = nfl_models._season(con, None, "playoff_odds")
        run = nfl_models._latest_complete_run(con, "playoff_odds", season, None, None, 32)
        identity = nfl_models._team_identity(con, season)
    except HTTPException as e:
        return {"playoff_odds": None, "reason": str(e.detail)}
    rows = con.execute(
        "SELECT team, p_playoffs FROM playoff_odds WHERE run_id = ? AND p_playoffs IS NOT NULL",
        (run["run_id"],)).fetchall()
    rows = sorted(rows, key=lambda x: (-x[1], x[0]))[:PLAYOFF_TOP_N]
    if len(rows) < PLAYOFF_TOP_N:
        return {"playoff_odds": None, "reason": "the latest run has fewer than %d teams with odds"
                                                % PLAYOFF_TOP_N}
    sims = None
    p = con.execute("SELECT params_json FROM model_runs WHERE run_id = ?", (run["run_id"],)).fetchone()
    if p and p[0]:
        try:
            n = json.loads(p[0]).get("n")
            sims = int(n) if isinstance(n, (int, float)) else None
        except (ValueError, TypeError):
            sims = None
    return {"playoff_odds": {
        "season": run["season"], "week": run["week"], "teams_in_run": run["teams"], "sims": sims,
        "top": [{"team": t, "team_name": identity[t]["team_name"], "p_playoffs": float(pp)}
                for t, pp in rows],
        "source": {"table": "playoff_odds", "model_version": run["model_version"],
                   "run_id": run["run_id"], "as_of": run["as_of"]}}, "reason": None}


# ---------------------------------------------------------------- payload

def featured_payload(con, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    now = _now(now)
    con.row_factory = sqlite3.Row
    absent: Dict[str, str] = {}
    fp = featured_prop(con, now)
    fg = featured_game(con, now)
    fo = featured_playoffs(con)
    fr = featured_record(con)
    prop, game, odds = fp["prop"], fg["game"], fo["playoff_odds"]
    for name, piece, reason in (("prop", prop, fp["reason"]), ("game", game, fg["reason"]),
                                ("playoff_odds", odds, fo["reason"])):
        if piece is None:
            absent[name] = reason

    if fr["record"] is None:
        absent["record"] = fr["reason"]
    market_p = game.pop("_market_p_home") if game else None
    player_chain = None
    if prop is not None and fp["history"].get("projection") is not None:
        player_chain = {"player": prop["player"], "market": prop["market"], "line": prop["line"],
                        "matchup": prop["matchup"], "projection": fp["history"]["projection"],
                        "games": prop["hit_rate_n"]["season"], "source": {
                            "projection": "recency-weighted mean of the player's game log "
                                          "(analytics/projections.py)", "as_of": prop["source"]["as_of"]}}
    if player_chain is None:
        absent["chain.player"] = absent.get("prop") or "the featured prop has no projection"
    market_chain = None
    if game is not None and market_p is not None:
        market_chain = {"home": game["home"], "away": game["away"], "home_name": game["home_name"],
                        "away_name": game["away_name"], "model_p_home_win": game["p_home_win"],
                        "market_p_home_win": market_p,
                        "source": {"model": game["source"]["projection"],
                                   "market": "locked moneylines, vig removed",
                                   "as_of": game["source"]["as_of"]}}
    if market_chain is None:
        absent["chain.market"] = absent.get("game") or "the featured game has no locked moneylines"
    season_chain = None
    if odds is not None:
        season_chain = {"top": odds["top"][0], "next": odds["top"][1:4], "sims": odds["sims"],
                        "week": odds["week"], "source": odds["source"]}
    return {"contract": "home-featured-v1", "generated_at": _iso(now),
            "prop": prop, "game": game, "playoff_odds": odds, "record": fr["record"],
            "chain": {"player": player_chain, "game": game, "market": market_chain,
                      "season": season_chain},
            "absent": absent}


# Selecting the prop reads a game log per qualifying player (about 0.3 s on the dev DB), so the response is
# kept for CACHE_SECONDS. This is a speed-up for an identical read, not a source of truth: the next
# request after expiry recomputes from the database.
CACHE_SECONDS = 300
_cache: Dict[str, Any] = {"at": 0.0, "payload": None}


@router.get("/api/home/featured")
def home_featured():
    import time
    if _cache["payload"] is None or time.monotonic() - _cache["at"] > CACHE_SECONDS:
        with closing(_db()) as con:
            _cache["payload"] = featured_payload(con)
        _cache["at"] = time.monotonic()
    return JSONResponse(_cache["payload"], headers={"X-LP-Data-Source": "db"})
