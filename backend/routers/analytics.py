"""routers/analytics.py — analytics endpoints. Handlers only; shared code lives in _core."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *

router = APIRouter()

@router.get("/api/props/ev")
def props_ev(league: Optional[str] = Query(None),
             market: Optional[str] = Query(None),
             min_ev: float = Query(-1.0, description="Minimum EV to include"),
             settled_only: bool = Query(False),
             limit: int = Query(50, ge=1, le=500)):
    """Props with computed expected value from the opening odds snapshot."""
    sql = _analytics_base_sql()
    params = []
    if league:
        sql += " AND pl.league = ?"; params.append(league)
    if market:
        sql += " AND p.market = ?"; params.append(market)
    if settled_only:
        sql += " AND r.hit IS NOT NULL"
    with closing(_db()) as con:
        rows = con.execute(sql, params).fetchall()

    computed = []
    for r in rows:
        odds, odds_opp, status = _ev_inputs(r)
        e = ev_mod.compute_ev(odds, odds_opp, status) if status else None
        if e is None:
            continue
        computed.append({
            "prop_id": r["id"], "player_name": r["player_name"], "player_id": r["player_id"],
            "team": r["team"], "league": r["league"], "market": r["market"],
            "line": r["line"], "side": r["side"], "game_date": r["game_date"],
            "settled": r["hit"] is not None,
            "hit": bool(r["hit"]) if r["hit"] is not None else None,
            **e,
        })
    n = len(computed)
    pos = [c for c in computed if c["ev"] > 0]
    summary = {
        "total_props": n,
        "positive_ev_pct": round(len(pos) * 100.0 / n, 1) if n else 0.0,
        "mean_ev": round(sum(c["ev"] for c in computed) / n, 4) if n else None,
        "mean_ev_positive_only": round(sum(c["ev"] for c in pos) / len(pos), 4) if pos else None,
    }
    out = [c for c in computed if c["ev"] >= min_ev]
    out.sort(key=lambda c: c["ev"], reverse=True)
    return {"props": out[:limit], "summary": summary,
            "filters": {"league": league, "market": market, "min_ev": min_ev,
                        "settled_only": settled_only, "limit": limit}}


@router.get("/api/props/clv")
def props_clv(league: Optional[str] = Query(None),
              market: Optional[str] = Query(None),
              min_clv: float = Query(-1.0),
              limit: int = Query(50, ge=1, le=500)):
    """Closing-line value per prop. Close = last snapshot captured before game start."""
    sql = """
        SELECT p.id, pl.name AS player_name, pl.league, p.market, p.line, p.side,
               pg.date AS game_date, pg.start_time,
               (SELECT odds FROM prop_odds_snapshots s WHERE s.prop_id=p.id AND s.side=p.side
                  ORDER BY s.captured_at ASC LIMIT 1) AS odds_open,
               (SELECT odds FROM prop_odds_snapshots s WHERE s.prop_id=p.id AND s.side=p.side
                  AND (pg.start_time IS NULL OR s.captured_at <= pg.start_time)
                  ORDER BY s.captured_at DESC LIMIT 1) AS odds_close,
               (SELECT COUNT(*) FROM prop_odds_snapshots s WHERE s.prop_id=p.id) AS snapshots_count
        FROM props p
        JOIN players pl ON pl.id = p.player_id
        JOIN prop_games pg ON pg.id = p.game_id
        WHERE 1=1"""
    params = []
    if league:
        sql += " AND pl.league = ?"; params.append(league)
    if market:
        sql += " AND p.market = ?"; params.append(market)
    with closing(_db()) as con:
        rows = con.execute(sql, params).fetchall()

    computed = []
    for r in rows:
        c = clv_mod.clv(r["odds_open"], r["odds_close"])
        if c is None:
            continue
        computed.append({
            "prop_id": r["id"], "player_name": r["player_name"], "league": r["league"],
            "market": r["market"], "line": r["line"], "side": r["side"],
            "p_open_implied": round(ev_mod.implied_prob(r["odds_open"]), 4),
            "p_close_implied": round(ev_mod.implied_prob(r["odds_close"]), 4),
            "clv": round(c, 4), "odds_open": r["odds_open"], "odds_close": r["odds_close"],
            "snapshots_count": r["snapshots_count"], "game_date": r["game_date"],
        })
    n = len(computed)
    pos = sum(1 for c in computed if c["clv"] > 0)
    out = [c for c in computed if c["clv"] >= min_clv]
    out.sort(key=lambda c: c["clv"], reverse=True)
    return {"props": out[:limit],
            "summary": {"mean_clv": round(sum(c["clv"] for c in computed) / n, 4) if n else None,
                        "positive_clv_pct": round(pos * 100.0 / n, 1) if n else 0.0,
                        "n_props": n},
            "note": None if n else "No opening snapshots captured yet.",
            "filters": {"league": league, "market": market, "min_clv": min_clv, "limit": limit}}


@router.get("/api/calibration")
def calibration(league: Optional[str] = Query(None),
                market: Optional[str] = Query(None),
                min_props_per_bucket: int = Query(10, ge=1)):
    """Reliability curve + Brier score for settled, de-vig-able props."""
    sql = _analytics_base_sql() + " AND r.hit IS NOT NULL"
    params = []
    if league:
        sql += " AND pl.league = ?"; params.append(league)
    if market:
        sql += " AND p.market = ?"; params.append(market)
    with closing(_db()) as con:
        rows = con.execute(sql, params).fetchall()

    # Calibration uses de-vigged (paired) props only — raw single-side implied
    # probs carry the vig and would bias the reliability curve (design §3.3).
    pairs, n_paired, n_single_excluded = [], 0, 0
    for r in rows:
        odds, odds_opp, status = _ev_inputs(r)
        if status is None:
            continue
        p_fair, conf = ev_mod.de_vig(odds, odds_opp, status)
        if p_fair is None:
            continue
        if conf != "high":
            n_single_excluded += 1
            continue
        pairs.append((p_fair, int(r["hit"])))
        n_paired += 1

    return {
        "buckets": calib_mod.reliability_buckets(pairs, min_props_per_bucket),
        "brier_score": round(calib_mod.brier(pairs), 4) if pairs else None,
        "brier_decomposition": calib_mod.brier_decomposition(pairs),
        "n_total": len(pairs), "n_paired": n_paired,
        "n_single_excluded": n_single_excluded,
        "filters": {"league": league, "market": market,
                    "min_props_per_bucket": min_props_per_bucket},
    }

