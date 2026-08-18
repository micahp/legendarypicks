"""routers/games/ufc.py — UFC rankings and fighter-form endpoints."""
import html

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
    """Lazy ESPN-backed last-five form for one internal UFC fighter."""
    with closing(_db()) as con:
        con.row_factory = sqlite3.Row
        player = con.execute(
            "SELECT id, name, espn_id FROM players WHERE id=? AND league='ufc'",
            (player_id,),
        ).fetchone()
        if not player:
            raise HTTPException(404, "UFC fighter not found")
        date_row = con.execute(
            """SELECT pg.date
               FROM props p JOIN prop_games pg ON pg.id=p.game_id
               WHERE p.player_id=? AND pg.league='ufc'
               ORDER BY ABS(julianday(pg.date) - julianday('now')) LIMIT 1""",
            (player_id,),
        ).fetchone()

    athlete_id = str(player["espn_id"] or "")
    canonical_name = player["name"]
    if not athlete_id:
        match = espn.ufc_athlete(player["name"], date_row["date"] if date_row else None)
        if not match:
            return {
                "player_id": player_id,
                "fighter": player["name"],
                "source": "espn",
                "fights": [],
            }
        athlete_id = match["id"]
        canonical_name = match["name"]
        # Persist the source crosswalk only when it is not already owned by a
        # different UFC row. The endpoint never fabricates or merges players.
        with closing(_db()) as con:
            owner = con.execute(
                "SELECT id FROM players WHERE league='ufc' AND espn_id=?",
                (athlete_id,),
            ).fetchone()
            if owner is None or owner[0] == player_id:
                con.execute("UPDATE players SET espn_id=? WHERE id=?", (athlete_id, player_id))
                con.commit()

    try:
        fights = espn.ufc_fight_history(athlete_id, limit=5)
    except Exception as exc:
        raise HTTPException(502, "ESPN UFC fight history unavailable") from exc
    return {
        "player_id": player_id,
        "fighter": canonical_name,
        "espn_id": athlete_id,
        "source": "espn",
        "fights": fights,
    }
