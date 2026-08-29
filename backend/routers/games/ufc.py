"""routers/games/ufc.py — UFC rankings and fighter-form endpoints."""
import html
import json

from fastapi import HTTPException
from _core import *
from . import router


def _db():
    """Resolve `routers.games._db` at call time (see scoreboard.py `_db`)."""
    from routers.games import _db as _pkg_db
    return _pkg_db()



@router.get("/api/ufc/rankings")
def ufc_rankings():
    """UFC rankings — reads cached ufc_rankings table populated by
    ingest_ufc_rankings.py (live scrape, never on the request path)."""
    with closing(_db()) as con:
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT division, rank, fighter, is_champion FROM ufc_rankings "
                "ORDER BY division, rank"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise HTTPException(
                503,
                "UFC rankings data unavailable: production data has not been promoted",
            ) from exc

    if not rows:
        raise HTTPException(
            503,
            "UFC rankings data unavailable: production data is empty",
        )

    # Separate P4P from weight divisions
    p4p_men, p4p_women = [], []
    divisions: dict = {}  # division_name -> {champion, ranked: [{rank, fighter}]}

    for r in rows:
        div = r["division"]
        rank = r["rank"]
        raw_fighter = r["fighter"]
        if not isinstance(div, str) or not isinstance(rank, int):
            continue
        if not isinstance(raw_fighter, str) or not raw_fighter.strip():
            continue
        fighter = html.unescape(raw_fighter)
        if "Pound-for-Pound" in div:
            entry = {"rank": rank, "fighter": fighter}
            if r["is_champion"]:
                entry["champion"] = True
            if "Women" in div:
                p4p_women.append(entry)
            else:
                p4p_men.append(entry)
        else:
            if div not in divisions:
                divisions[div] = {"division": div, "champion": "", "ranked": []}
            if r["is_champion"]:
                divisions[div]["champion"] = fighter
            else:
                divisions[div]["ranked"].append(
                    {"rank": rank, "fighter": fighter}
                )

    # Sort P4P by rank (champion=rank 0 first)
    p4p_men.sort(key=lambda x: x["rank"])
    p4p_women.sort(key=lambda x: x["rank"])

    # Order divisions: men's weight classes first, then women's
    MEN_ORDER = [
        "Flyweight", "Bantamweight", "Featherweight", "Lightweight",
        "Welterweight", "Middleweight", "Light Heavyweight", "Heavyweight",
    ]
    WOMEN_ORDER = ["Women's Strawweight", "Women's Flyweight", "Women's Bantamweight"]
    ordered = []
    for d in MEN_ORDER:
        if d in divisions:
            divisions[d]["ranked"].sort(key=lambda x: x["rank"])
            ordered.append(divisions[d])
    for d in WOMEN_ORDER:
        if d in divisions:
            divisions[d]["ranked"].sort(key=lambda x: x["rank"])
            ordered.append(divisions[d])

    expected_divisions = set(MEN_ORDER + WOMEN_ORDER)
    populated_divisions = {
        division["division"] for division in ordered if division["ranked"]
    }
    if (
        not p4p_men
        or not p4p_women
        or populated_divisions != expected_divisions
    ):
        raise HTTPException(
            503,
            "UFC rankings data unavailable: production data is incomplete",
        )

    return {
        "pound_for_pound": {"men": p4p_men, "women": p4p_women},
        "divisions": ordered,
    }


@router.get("/api/ufc/fighter/{player_id}/form")
def ufc_fighter_form(player_id: int):
    """Database-backed last-five form for one internal UFC fighter."""
    with closing(_db()) as con:
        con.row_factory = sqlite3.Row
        player = con.execute(
            "SELECT id, name, espn_id FROM players WHERE id=? AND league='ufc'",
            (player_id,),
        ).fetchone()
        if not player:
            raise HTTPException(404, "UFC fighter not found")
        has_ufcstats = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='player_game_logs_ufcstats'"
        ).fetchone() is not None
        if has_ufcstats:
            rows = con.execute(
                """SELECT game_id,source_event_key,game_date,opponent,stats
                     FROM player_game_logs_ufcstats
                    WHERE player_id=? AND league='ufc'
                    ORDER BY game_date DESC LIMIT 5""",
                (player_id,),
            ).fetchall()
            source = "ufcstats"
        else:
            # Compatibility while the additive migration is pending. This is
            # still DB-only: request handlers never fetch or mutate source data.
            rows = con.execute(
                """SELECT game_id,'' AS source_event_key,game_date,opponent,stats
                     FROM player_game_logs
                    WHERE player_id=? AND league='ufc'
                    ORDER BY game_date DESC LIMIT 5""",
                (player_id,),
            ).fetchall()
            source = "espn"

    fights = []
    for row in rows:
        try:
            stats = json.loads(row["stats"] or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        result = str(stats.get("result") or "").upper()
        method = str(stats.get("method") or "").upper()
        if result not in {"W", "L", "D", "NC"} or not method:
            continue
        fights.append({
            "result": result,
            "method": method,
            "opponent": row["opponent"] or "",
            "date": row["game_date"] or "",
            "event_id": row["source_event_key"] or "",
            "fight_id": row["game_id"] or "",
        })
    return {
        "player_id": player_id,
        "fighter": player["name"],
        "source": source,
        "fights": fights,
    }
