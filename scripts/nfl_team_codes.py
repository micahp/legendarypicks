"""The one place NFL team codes are translated. Every read of an outside NFL source goes through it.

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

DB_CODES = frozenset({
    'ARI', 'ATL', 'BAL', 'BUF', 'CAR', 'CHI', 'CIN', 'CLE', 'DAL', 'DEN', 'DET', 'GB', 'HOU', 'IND', 'JAX', 'KC',
    'LAC', 'LAR', 'LV', 'MIA', 'MIN', 'NE', 'NO', 'NYG', 'NYJ', 'PHI', 'PIT', 'SEA', 'SF', 'TB', 'TEN', 'WSH',
})
DB_TO_NFLVERSE = {'LAR': 'LA', 'WSH': 'WAS'}
NFLVERSE_CODES = frozenset(DB_TO_NFLVERSE.get(code, code) for code in DB_CODES)

# Every spelling seen from an outside source, mapped to the database code. Relocations map to the current club.
TO_DB = {
    **{code: code for code in DB_CODES},
    'LA': 'LAR', 'STL': 'LAR', 'RAM': 'LAR',
    'WAS': 'WSH',
    'JAC': 'JAX',
    'ARZ': 'ARI', 'AZ': 'ARI',
    'OAK': 'LV', 'LVR': 'LV',
    'SD': 'LAC', 'SDG': 'LAC',
    'GNB': 'GB', 'KAN': 'KC', 'NOR': 'NO', 'NWE': 'NE', 'SFO': 'SF', 'TAM': 'TB',
}

PBP_TEAM_CODE_ALIASES = {'LA': 'LAR', 'WAS': 'WSH', 'JAC': 'JAX'}
NFLVERSE_TEAM_CODE_ALIASES = dict(DB_TO_NFLVERSE)
# Franchise-level normalization is used only for cross-season identity comparisons. It is not a PBP or roster-file key.
FRANCHISE_TEAM_CODE_ALIASES = {**PBP_TEAM_CODE_ALIASES, 'OAK': 'LV'}


def to_db(code):
    """The database code (LAR, WSH, ...) for any known spelling. Raises on anything else."""
    key = str(code).strip().upper() if code is not None else None
    if key not in TO_DB:
        raise ValueError(f'unknown NFL team code {code!r}; add it to nfl_team_codes.TO_DB if a source really uses it')
    return TO_DB[key]


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
        key = str(code).strip().upper() if code is not None else None
        if key not in TO_DB:
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


def to_pbp_team_code(team_code):
    """Return the PBP/database code for an alias used by frozen source artifacts."""
    return PBP_TEAM_CODE_ALIASES.get(team_code, team_code)


def to_nflverse_team_code(team_code):
    """Return the nflverse roster/venue code for a PBP or already-normalized code."""
    pbp_code = to_pbp_team_code(team_code)
    return NFLVERSE_TEAM_CODE_ALIASES.get(pbp_code, pbp_code)


def canonical_franchise_team_code(team_code):
    """Normalize known historical abbreviations for identity comparisons across seasons."""
    return FRANCHISE_TEAM_CODE_ALIASES.get(team_code, team_code)


def missing_pbp_team_codes(required_team_codes, available_team_codes):
    """Return required PBP teams absent from a source table, after normalizing both sides."""
    required = {to_pbp_team_code(team_code) for team_code in required_team_codes}
    available = {to_pbp_team_code(team_code) for team_code in available_team_codes}
    return sorted(required - available)
