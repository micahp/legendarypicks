#!/usr/bin/env python3
"""espn_leagues.py — single registry of ESPN league metadata for ingests and reconcile_totals.

Every consumer that needs an ESPN path, a scope group, or the regular-season type name
reads it from here — nothing else in the codebase may hardcode a group id.

Paths are sports.core.api.espn.com style (sport/leagues/<slug>), matching the season
documents the ingests read. `scope_group` is None for leagues that are their own scope;
NCAAF FBS is published group id '80' (146 teams, 888 of 911 events in 2025).
"""

ESPN_LEAGUES = {
    'mls': {'path': 'soccer/leagues/usa.1', 'scope_group': None, 'regular_type_name': 'Regular Season', 'display_name': 'MLS'},
    'ligamx': {'path': 'soccer/leagues/mex.1', 'scope_group': None, 'regular_type_name': 'Regular Season', 'display_name': 'Liga MX'},
    'ncaaf': {'path': 'football/leagues/college-football', 'scope_group': '80', 'regular_type_name': 'Regular Season', 'display_name': 'NCAAF'},
}
