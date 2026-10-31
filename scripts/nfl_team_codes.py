"""Translate NFL team codes between the schedule, PBP, and nflverse artifacts.

The SLC database uses PBP codes. Several pinned inputs use nflverse codes for the same clubs, so conversion direction must
be named at each call site instead of re-creating local dictionaries.
"""

PBP_TEAM_CODE_ALIASES = {
    'LA': 'LAR',
    'WAS': 'WSH',
    'JAC': 'JAX',
}

NFLVERSE_TEAM_CODE_ALIASES = {
    'LAR': 'LA',
    'WSH': 'WAS',
}

# Franchise-level normalization is used only for cross-season identity comparisons. It is not a PBP or roster-file key.
FRANCHISE_TEAM_CODE_ALIASES = {
    **PBP_TEAM_CODE_ALIASES,
    'OAK': 'LV',
}


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
