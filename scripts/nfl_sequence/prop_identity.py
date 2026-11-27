"""Shared cutoff-aware NFL QB market evidence; never substitute a conflicting event ID."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from contextlib import closing
from scripts import nfl_team_codes

ROOT = Path(__file__).resolve().parents[2]


def resolve_market_qbs(props_db, game_id, gameday, espn_event_id, as_of):
    cutoff = datetime.fromisoformat(str(as_of).replace('Z', '+00:00'))
    if cutoff.tzinfo is None:
        raise ValueError('PROP_CUTOFF_MISSING_TIMEZONE')
    cutoff = cutoff.astimezone(timezone.utc).isoformat()
    away, home = nfl_team_codes.teams_from_game_id(game_id)
    expected = str(espn_event_id).strip() if espn_event_id else None
    names = json.loads((ROOT / 'docs/espn-team-codes-2026-07-27.json').read_text())['nfl']
    codes = {name: nfl_team_codes.to_db(code) for code, name in names.items()}

    def canonical(value):
        try:
            return nfl_team_codes.to_db(codes.get(value, value))
        except ValueError:
            return None

    def teams_match(row):
        return (canonical(row[1]), canonical(row[2])) == (away, home)

    def event_id(row):
        return str(row[3]).strip() if row[3] else None

    with closing(sqlite3.connect(Path(props_db).resolve().as_uri() + '?mode=ro', uri=True)) as con:
        exact = con.execute(
            "SELECT id, away, home, espn_event_id, date FROM prop_games "
            "WHERE league='nfl' AND CAST(espn_event_id AS TEXT)=?", (expected,)).fetchall() if expected else []
        if len(exact) > 1:
            raise ValueError(f'{game_id}: ambiguous ESPN prop event {expected}')
        candidates = con.execute(
            "SELECT id, away, home, espn_event_id, date FROM prop_games WHERE league='nfl' "
            "AND date BETWEEN date(?, '-1 day') AND date(?, '+1 day')", (gameday, gameday)).fetchall()
        if exact:
            if not teams_match(exact[0]) or exact[0] not in candidates:
                raise ValueError(f'{game_id}: ESPN prop event conflicts with matchup/date')
            selected, method = exact[0], 'espn_event_id'
        else:
            matching = [row for row in candidates if teams_match(row) and row[4] == gameday]
            if expected and any(event_id(row) not in (None, expected) for row in matching):
                raise ValueError(f'{game_id}: conflicting ESPN event ID in team/date fallback')
            if len(matching) > 1:
                raise ValueError(f'{game_id}: ambiguous team/date prop event')
            selected, method = (matching[0], 'team_date') if matching else (None, 'unmatched')
        evidence = {'game_id': game_id, 'as_of': cutoff, 'expected_espn_event_id': expected,
                    'method': method, 'prop_game_id': selected[0] if selected else None,
                    'matched_espn_event_id': event_id(selected) if selected else None,
                    'quotes': []}
        if selected is not None:
            rows = con.execute(
                "SELECT pl.team, pl.nfl_gsis_id, p.captured_at FROM props p "
                "JOIN players pl ON pl.id=p.player_id WHERE p.game_id=? AND p.market='passing_yards' "
                "AND length(p.captured_at)>=19 AND julianday(p.captured_at)<=julianday(?) "
                "ORDER BY pl.team, pl.nfl_gsis_id, p.captured_at", (selected[0], cutoff)).fetchall()
            for team, gsis, captured in rows:
                team = canonical(team)
                if team not in (away, home) or not gsis:
                    raise ValueError(f'{game_id}: invalid player identity on passing-yards prop')
                evidence['quotes'].append({'team': team, 'gsis_id': gsis, 'captured_at': captured})
    evidence['quotes'] = [dict(t) for t in sorted(set(tuple(sorted(q.items())) for q in evidence['quotes']))]
    return evidence


def priced_qbs(evidence):
    result = {}
    for quote in evidence['quotes']:
        result.setdefault(quote['team'], set()).add(quote['gsis_id'])
    return result
