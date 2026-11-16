"""NFL view of backend/team_codes.py, the one place team codes are defined for the whole app (since 2026-11-04).

This module holds no list of its own: every code, alias and source spelling comes from backend/team_codes.py.

Measured 2026-11-03 (picks.dev.db and the published nflverse files):

- The LP database stores the ESPN codes LAR and WSH in every team column (nfl_pbp, nfl_schedule, players,
  player_game_logs), for every season 2010-2026. Relocated clubs are stored under their current code (LV, LAC, LAR).
- nflverse files (play-by-play, schedules, depth charts, rosters, injuries, weekly player stats, the dated archives) use
  LA and WAS, also for every season 2010-2026.
- game_id strings keep the nflverse spelling even inside the database: nfl_schedule has game_id '2026_08_LAC_LA' with
  home_team 'LAR'. Never read a team out of a game_id without teams_from_game_id.

The two vocabularies differ only by LA/LAR and WAS/WSH, which is why a missed translation never raises: every other team
matches, and the two that do not look like a coverage gap ("team absent from depth chart"), not a key error. The functions
below therefore refuse any code they do not know instead of passing it through.

The legacy names (PBP_TEAM_CODE_ALIASES, to_pbp_team_code, ...) predate this note; "PBP" in them means the database's
nfl_pbp table, whose codes are the database vocabulary.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import team_codes  # noqa: E402

LEAGUE = 'nfl'
DB_CODES = frozenset(team_codes.CANONICAL[LEAGUE])
DB_TO_NFLVERSE = dict(team_codes.SOURCE_VOCABULARIES[LEAGUE]['nflverse'])
NFLVERSE_CODES = frozenset(DB_TO_NFLVERSE.get(code, code) for code in DB_CODES)
# Every spelling the app knows, mapped to the database code (read-only view of backend/team_codes.py).
TO_DB = {**{code: code for code in DB_CODES}, **team_codes.ALIASES[LEAGUE]}


def to_db(code):
    """The database code (LAR, WSH, ...) for any known spelling. Raises on anything else."""
    try:
        return team_codes.normalize(LEAGUE, code)
    except team_codes.UnknownTeamCode:
        raise ValueError(f'unknown NFL team code {code!r}; add it to backend/team_codes.py ALIASES if a source '
                         'really uses it') from None


def to_nflverse(code):
    """The nflverse code (LA, WAS, ...) for any known spelling. Raises on anything else."""
    db_code = to_db(code)
    return DB_TO_NFLVERSE.get(db_code, db_code)


def convert(codes, to='db'):
    """Convert many codes at once; one error names every unknown code with its count, so a bad column fails whole."""
    target = {'db': to_db, 'nflverse': to_nflverse}[to]
    codes = list(codes)
    unknown = {}
    for code in codes:
        try:
            to_db(code)
        except ValueError:
            unknown[code] = unknown.get(code, 0) + 1
    if unknown:
        raise ValueError(f'unknown NFL team codes (value: rows): {unknown}')
    return [target(code) for code in codes]


def normalize_frame(frame, columns, to='db'):
    """A copy of a DataFrame with the team columns converted. Raises on any unknown code; nulls are an error too."""
    out = frame.copy()
    for column in columns:
        out[column] = convert(out[column].tolist(), to=to)
    return out


def teams_from_game_id(game_id, to='db'):
    """(away, home) from a 'SEASON_WEEK_AWAY_HOME' game_id, converted. game_ids always carry the nflverse spelling."""
    parts = str(game_id).split('_')
    if len(parts) != 4:
        raise ValueError(f'not a SEASON_WEEK_AWAY_HOME game_id: {game_id!r}')
    away, home = convert(parts[2:], to=to)
    return away, home


class TeamKeyed(team_codes.TeamKeyed):
    """backend/team_codes.TeamKeyed for the NFL: keys stored as database codes, any known spelling on lookup, an unknown
    code raises. `team_at` is the team's position in a tuple key, or None when the key is the team itself."""

    def __init__(self, items=(), team_at=None):
        super().__init__(LEAGUE, items, team_at=team_at)

    def _key(self, key):
        try:
            return super()._key(key)
        except team_codes.UnknownTeamCode as exc:
            raise ValueError(f'unknown NFL team code: {exc}') from None

    def copy(self):
        return TeamKeyed(self, team_at=self.team_at)

    def __reduce__(self):
        return (TeamKeyed, ((), self.team_at), None, None, iter(dict.items(self)))


# Legacy names, kept for their callers. They used to pass an unknown code through unchanged, which is how a wrong
# spelling missed instead of raising; they are strict now. An absent code (None, or the blank the play extras file
# writes when no timeout was called) is returned as given.
PBP_TEAM_CODE_ALIASES = {code: target for code, target in TO_DB.items() if code != target}
NFLVERSE_TEAM_CODE_ALIASES = dict(DB_TO_NFLVERSE)
FRANCHISE_TEAM_CODE_ALIASES = dict(PBP_TEAM_CODE_ALIASES)


def _absent(team_code):
    return team_code is None or team_code == ''


def to_pbp_team_code(team_code):
    """The database code; an absent code is returned as given. Raises on an unknown code."""
    return team_code if _absent(team_code) else to_db(team_code)


def to_nflverse_team_code(team_code):
    """The nflverse code; an absent code is returned as given. Raises on an unknown code."""
    return team_code if _absent(team_code) else to_nflverse(team_code)


def canonical_franchise_team_code(team_code):
    """The current club's database code (relocations collapse: OAK to LV, STL to LAR); an absent code as given."""
    return team_code if _absent(team_code) else to_db(team_code)


def missing_pbp_team_codes(required_team_codes, available_team_codes):
    """Required teams absent from a source table, compared as database codes. Raises on an unknown code."""
    return sorted(set(convert(required_team_codes)) - set(convert(available_team_codes)))
