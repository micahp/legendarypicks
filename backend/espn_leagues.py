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
    # Liga MX publishes no phase called a regular season. Its two regular
    # tournaments are 'Torneo Apertura' and 'Torneo Clausura'; every knockout
    # phase is named for its round ('Apertura - Quarterfinals', '... - Finals').
    # So 'Torneo' is the discriminator the publisher itself provides, and
    # 'Regular Season' -- which nothing here is called -- would have filed all
    # 153 Apertura fixtures as POST.
    'ligamx': {'path': 'soccer/leagues/mex.1', 'scope_group': None, 'regular_type_name': 'Torneo', 'display_name': 'Liga MX'},
    # Leagues Cup publishes five phases and none of them is called a regular season:
    # 'League Phase' is the group stage and the other four are knockout rounds. The
    # name is what `regular_type_name` is for -- see ingest_soccer_logs._game_type_for_type,
    # which reads this rather than matching the literal string 'regular season'.
    'lcup': {'path': 'soccer/leagues/concacaf.leagues.cup', 'scope_group': None, 'regular_type_name': 'League Phase', 'display_name': 'Leagues Cup'},
    'ncaaf': {'path': 'football/leagues/college-football', 'scope_group': '80', 'regular_type_name': 'Regular Season', 'display_name': 'NCAAF'},
}
