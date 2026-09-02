"""transactions — NFL offseason transactions layer."""
import copy
import datetime as dt
import os
import re
import sqlite3
import threading
import time
from collections import defaultdict
from contextlib import closing
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence, Set, Tuple
from fastapi import APIRouter, HTTPException, Query
from _core import _db, _normalize_name
from team_codes import normalize, normalize_optional
from .constants import (_CONTEXT_CONTRACT, _DRAFT_BOARD_CONTRACT, _CURRENT_SEASON, _DRAFT_BOARD_CACHE_TTL, _DRAFT_BOARD_CACHE_MAX_ENTRIES, _DATABASE_TOKEN_MEMO_MAX_ENTRIES, _DRAFT_CACHE_SOURCES, _REG_SEASON_TEAM_GAMES, _REG_SEASON_LAST_WEEK, _POSTSEASON_FIRST_WEEK, _THIN_SAMPLE_GAMES, _CALENDAR_VALID_THROUGH, _NFL_CALENDAR_SOURCE, _NFL_CAMP_SOURCE, _NFL_MILESTONES, _SKILL_POSITIONS, _DEF_POSITION, _FANTASY_DRAFT_POSITIONS, _POSITION_FILTERS, _SORT_FIELDS, _SEARCH_MAX_LEN, _SEARCH_MAX_TOKENS, _TRANSACTIONS_CONTRACT, _POSITION_PREFIX, _SENTENCE_SPLIT, _TRAILING_INITIAL, _SIGNIFICANCE_CACHE_TTL)  # noqa: E402
from . import router

_significance_cache: Dict[str, object] = {"ts": 0.0, "name_to_pid": None, "pid_to_name": None}



def _pkg__db(*args, **kwargs):
    """Resolve `routers.nfl_offseason._db` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _db as _pkg_f
    return _pkg_f(*args, **kwargs)


def _pkg__table_columns(*args, **kwargs):
    """Resolve `routers.nfl_offseason._table_columns` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _table_columns as _pkg_f
    return _pkg_f(*args, **kwargs)

def _player_significance_lookup(connection: sqlite3.Connection):
    """name -> ADP, as a proxy for "how significant is this player" — lower ADP
    is more significant/valuable. Missing/unresolved names return None (treated
    as least significant, so a real ADP always wins the mirror tie-break)."""
    now = time.time()
    if now - _significance_cache["ts"] < _SIGNIFICANCE_CACHE_TTL and _significance_cache["name_to_pid"] is not None:
        name_to_pid: Dict[str, int] = _significance_cache["name_to_pid"]
        pid_to_adp: Dict[int, float] = _significance_cache["pid_to_adp"]
    else:
        name_to_pid = {}
        for r in connection.execute("SELECT id, name FROM players WHERE league='nfl'"):
            name_to_pid[_normalize_name(r["name"])] = r["id"]
        pid_to_adp = {}
        try:
            for r in connection.execute(
                "SELECT player_id, adp FROM nfl_adp WHERE season=? AND adp IS NOT NULL",
                (_CURRENT_SEASON,),
            ):
                pid_to_adp[r["player_id"]] = r["adp"]
        except sqlite3.OperationalError:
            pass  # nfl_adp not populated yet — significance lookup degrades to "unknown" for everyone
        _significance_cache["ts"] = now
        _significance_cache["name_to_pid"] = name_to_pid
        _significance_cache["pid_to_adp"] = pid_to_adp

    def significance(name: str) -> Optional[float]:
        pid = name_to_pid.get(_normalize_name(name))
        return pid_to_adp.get(pid) if pid is not None else None

    return significance

def _outgoing_player(sentence: str, players: List[str]) -> Optional[str]:
    """Which named player is THIS team's own outgoing asset, not the return
    they got back. ESPN's standard phrasing is "Traded [outgoing] to [team]
    for [incoming]" — a player named before " for " is outgoing; one named
    only after " for " (e.g. this team gave up picks only, got a named player
    back — "Traded a 1st... to Miami for WR Jaylen Waddle") is incoming, and
    must NOT be mistaken for this team's own significant piece."""
    if not players:
        return None
    m = re.search(r"\bfor\b", sentence)
    if not m:
        return players[0]  # no "for" clause (e.g. "Traded QB X to Kansas City.") — best effort
    before_for = sentence[: m.start()]
    before_names = _POSITION_PREFIX.findall(before_for)
    return before_names[0] if before_names else None  # gave up picks only, no named outgoing player

def _split_trade_sentences(description: str) -> List[Tuple[str, List[str], Optional[str]]]:
    """A logged transaction can bundle unrelated moves in one blob ("Signed X.
    Released Y. Traded Z..."). Split into sentences, keep only the trade ones,
    and pull out the player name(s) mentioned in each for bolding client-side,
    plus which one (if any) is THIS team's own outgoing player."""
    out = []
    for sentence in _SENTENCE_SPLIT.split(description.strip()):
        sentence = sentence.strip()
        if not sentence or "trad" not in sentence.lower():
            continue
        players = [
            p if _TRAILING_INITIAL.search(p) else p.rstrip(".")
            for p in _POSITION_PREFIX.findall(sentence)
        ]
        out.append((sentence, players, _outgoing_player(sentence, players)))
    return out

def _dedupe_trade_rows(connection: sqlite3.Connection, rows: list, limit: int) -> List[dict]:
    """Split raw transaction rows into individual trade sentences (dropping any
    bundled non-trade sentences), dedupe mirror entries — ESPN logs one row per
    team in a deal, so the same trade otherwise appears once per side — and
    return the most recent `limit` distinct trades.

    Mirror entries are grouped by the set of player names mentioned (reliable;
    team names in free text are often ambiguous, e.g. "Los Angeles" alone
    doesn't say Rams vs Chargers). Within a group, keep the entry for the team
    that gave up the more significant player (ADP as the significance proxy,
    lower = more significant) — that's "the from team" for a headline trade.
    If ADP can't disambiguate (tie, or neither player resolves), it doesn't
    matter which side is kept, so fall back to team abbreviation for a stable,
    deterministic pick."""
    significance = _player_significance_lookup(connection)
    groups: Dict[frozenset, list] = defaultdict(list)
    for r in rows:
        for sentence, players, from_player in _split_trade_sentences(r["description"]):
            key = frozenset(p.lower() for p in players) if players else frozenset({sentence.lower()})
            groups[key].append({
                "date": r["txn_date"],
                "team": r["team_abbr"],
                "teamName": r["team_name"],
                "description": sentence,
                "players": players,
                "_from_player": from_player,
            })

    def sort_key(e: dict) -> tuple:
        sig = significance(e["_from_player"]) if e["_from_player"] else None
        return (sig if sig is not None else float("inf"), e["team"])

    deduped = [min(events, key=sort_key) for events in groups.values()]
    deduped.sort(key=lambda e: e["date"], reverse=True)
    for e in deduped:
        del e["_from_player"]  # internal only, not part of the API contract
    return deduped[:limit]

@router.get("/api/nfl/transactions")
def nfl_transactions(
    limit: int = Query(30, ge=1, le=100),
    team: Optional[str] = Query(None, description="team abbreviation, e.g. ATL"),
    trades_only: bool = Query(False, description="only transactions whose description mentions a trade"),
):
    """Recent NFL roster moves (waives, signings, IR, releases, retirements) —
    ingested from ESPN's public transactions feed by nfl_transactions_sync.py.
    "Offseason Movers" card content; see docs on why this replaced the raw
    season-milestone timeline (it's actual news, not a static calendar).

    trades_only: no dedicated "type" field exists in ESPN's feed (free text
    only). Each bundled description is split into individual trade sentences
    (a signing/release bundled in the same blob is dropped), and mirror
    entries — ESPN logs one row per team in a deal, so the same trade
    otherwise appears twice — are deduped by the set of player names
    mentioned (reliable; team names in the text are often ambiguous, e.g.
    "Los Angeles" alone doesn't say Rams vs Chargers). Within a duplicate
    pair, keep the entry for the team that gave up the more significant
    player — ADP (nfl_adp) as the significance proxy, lower = more
    significant — since that's "the from team" for a headline trade; if
    ADP can't disambiguate (tie, or neither player resolves), it doesn't
    matter which side is kept, so fall back to team abbreviation for a
    stable, deterministic pick."""
    with closing(_pkg__db()) as connection:
        connection.row_factory = sqlite3.Row
        columns = _pkg__table_columns(connection, "nfl_transactions")
        if not columns:
            return {"contract": _TRANSACTIONS_CONTRACT, "transactions": [], "count": 0}
        conditions = []
        params: list = []
        if team:
            conditions.append("team_abbr=?")
            params.append(team.upper())
        if trades_only:
            conditions.append("description LIKE '%trad%'")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        # Trade sentences get split out of bundled rows and deduped, so pull a
        # wider raw window than `limit` — the final trade-event count is smaller
        # than the raw row count once bundling/mirroring collapse.
        raw_limit = limit * 6 if trades_only else limit
        rows = connection.execute(
            f"""SELECT txn_date, team_id, team_abbr, team_name, description
                FROM nfl_transactions {where}
                ORDER BY txn_date DESC, id DESC LIMIT ?""",
            (*params, raw_limit),
        ).fetchall()

        if not trades_only:
            return {
                "contract": _TRANSACTIONS_CONTRACT,
                "count": len(rows),
                "transactions": [
                    {
                        "date": r["txn_date"],
                        "team": r["team_abbr"],
                        "teamName": r["team_name"],
                        "description": r["description"],
                    }
                    for r in rows
                ],
            }

        deduped = _dedupe_trade_rows(connection, rows, limit)
        return {
            "contract": _TRANSACTIONS_CONTRACT,
            "count": len(deduped),
            "transactions": deduped,
        }
