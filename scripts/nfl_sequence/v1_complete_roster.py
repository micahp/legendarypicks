"""Strict participant checks for the V1 Complete live-play path.

The resolved roster is the source of eligibility. In particular, a projected
practice-squad elevation is not an actual game-specific elevation.
"""


def eligible_ids(resolved_team):
    if resolved_team.get('schema') != 'lp-nfl-resolved-roster-2':
        raise ValueError('v1_complete_roster_schema_missing')
    if resolved_team.get('blocks'):
        raise ValueError('v1_complete_roster_blocked:' + ','.join(resolved_team['blocks']))
    players = resolved_team.get('players')
    if not isinstance(players, list):
        raise ValueError('v1_complete_roster_players_missing')
    by_id = {}
    for player in players:
        player_id = player.get('gsis_id')
        if not player_id:
            raise ValueError('v1_complete_roster_player_id_missing')
        valid = (player.get('official_eligible') is True
                 and player.get('membership') in ('ACTIVE_ROSTER', 'ELEVATED')
                 and player.get('exclusion_reason') is None)
        if player_id in by_id and by_id[player_id] != valid:
            raise ValueError('v1_complete_roster_conflicting_eligibility:' + player_id)
        by_id[player_id] = valid
    for role in resolved_team.get('roles', []):
        if role.get('required') and (role.get('status') != 'ASSIGNED' or not by_id.get(role.get('gsis_id'), False)):
            raise ValueError('v1_complete_roster_unresolved_role:' + str(role.get('role')))
    return frozenset(player_id for player_id, valid in by_id.items() if valid)


def require_participants(resolved_team, selected_ids):
    allowed = eligible_ids(resolved_team)
    for player_id in selected_ids:
        if player_id not in allowed:
            raise ValueError('v1_complete_roster_ineligible_participant:' + str(player_id))
    return allowed


def participant_validator(resolved):
    """Make a per-play check for the existing SLC pre-event participant chooser.

    This covers the player records that chooser returns. Other selection paths,
    including defense and special teams, still need their own checks.
    """
    allowed = {side: eligible_ids(resolved[side]) for side in ('home', 'away')}

    def validate(offense, pre_event):
        if offense not in ('A', 'B'):
            raise ValueError('v1_complete_roster_unknown_offense:' + str(offense))
        side = 'home' if offense == 'A' else 'away'
        if pre_event is None:
            return
        for value in pre_event.values():
            if isinstance(value, dict) and 'gsis_id' in value and value['gsis_id'] not in allowed[side]:
                raise ValueError('v1_complete_roster_ineligible_participant:' + str(value['gsis_id']))

    return validate
