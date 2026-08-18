"""Load the UFC fighter work set from the local database."""
from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .names import _opponent_for, _parse_date
from .schema import _read_only_connection

@dataclass(frozen=True)
class FighterTarget:
    player_id: int
    name: str
    espn_id: Optional[str]
    card_date: Optional[str]
    prop_game_id: Optional[int]
    opponent: Optional[str]
    prop_game_espn_id: Optional[str] = None

def load_targets(
    db_path: str,
    as_of: dt.date,
    lookback_days: int = 7,
    lookahead_days: int = 21,
    all_fighters: bool = False,
) -> Tuple[List[FighterTarget], Set[Tuple[str, str, int, str]], Dict[str, int]]:
    """Load a finite fighter work set and existing keys without opening prod writable."""
    with closing(_read_only_connection(db_path)) as con:
        player_rows = con.execute(
            "SELECT id, name, espn_id FROM players WHERE league='ufc' ORDER BY name"
        ).fetchall()
        associations = con.execute(
            """
            SELECT DISTINCT p.player_id, pg.id AS prop_game_id, pg.date, pg.home,
                            pg.away, pg.espn_event_id
            FROM props p
            JOIN prop_games pg ON pg.id=p.game_id
            WHERE pg.league='ufc'
            """
        ).fetchall()
        existing_keys = {
            ("ufc", str(row["source_player_key"]), int(row["season"]), str(row["game_no"]))
            for row in con.execute(
                """
                SELECT source_player_key, season, game_no
                FROM player_game_logs
                WHERE league='ufc'
                  AND source_player_key IS NOT NULL
                  AND game_no IS NOT NULL
                """
            )
        }
        owner_by_espn = {
            str(row["espn_id"]): int(row["id"])
            for row in con.execute(
                """
                SELECT id, espn_id FROM players
                WHERE league='ufc' AND NULLIF(espn_id, '') IS NOT NULL
                """
            )
        }
    by_player: Dict[int, List[sqlite3.Row]] = {}
    for row in associations:
        by_player.setdefault(int(row["player_id"]), []).append(row)
    start_date = as_of - dt.timedelta(days=max(0, lookback_days))
    end_date = as_of + dt.timedelta(days=max(0, lookahead_days))
    targets: List[FighterTarget] = []
    for player in player_rows:
        choices = []
        for row in by_player.get(int(player["id"]), []):
            card_date = _parse_date(row["date"])
            if card_date is None:
                continue
            if all_fighters or start_date <= card_date <= end_date:
                choices.append((abs((card_date - as_of).days), -card_date.toordinal(), row))
        choices.sort(key=lambda item: (item[0], item[1], int(item[2]["prop_game_id"])))
        if not choices and not all_fighters:
            continue
        selected = choices[0][2] if choices else None
        targets.append(
            FighterTarget(
                player_id=int(player["id"]),
                name=str(player["name"]),
                espn_id=str(player["espn_id"] or "").strip() or None,
                card_date=str(selected["date"])[:10] if selected else None,
                prop_game_id=int(selected["prop_game_id"]) if selected else None,
                opponent=(
                    _opponent_for(player["name"], selected["home"], selected["away"])
                    if selected
                    else None
                ),
                prop_game_espn_id=(
                    str(selected["espn_event_id"] or "").strip() or None
                    if selected
                    else None
                ),
            )
        )
    return targets, existing_keys, owner_by_espn

def _dedupe_games(games: Iterable[dict]) -> List[dict]:
    by_id = {}
    for game in games:
        game_id = str(game.get("game_id") or "")
        if game_id:
            by_id[game_id] = game
    return list(by_id.values())
