"""Reuse the fitted SLC participation field for eligible offensive skill players.

This does not select offensive linemen or defenders and is not an 11-on-11
lineup. The full live model must resolve those roles before executing a play.
"""
import random

import participation_field
import team_codes
import v1_complete_roster


def advance(field, *, team, season, resolved, roster, group, seed, previous=None, allow_synthetic=False):
    """Advance the chosen personnel grouping using the existing fitted field."""
    if not field.seasons or max(field.seasons) >= int(season):
        raise ValueError('live_participation_training_cutoff_invalid')
    if not field.file_hash_verified and not allow_synthetic:
        raise ValueError('live_participation_source_not_verified')
    if team_codes.normalize('nfl', team) != team_codes.normalize('nfl', resolved['team']):
        raise ValueError('live_participation_team_mismatch')
    allowed = v1_complete_roster.eligible_ids(resolved)
    eligible = [p for p in roster if p.get('gsis_id') in allowed]
    qb_roles = [r for r in resolved.get('roles', []) if r.get('role') == 'QB1' and r.get('status') == 'ASSIGNED']
    if len(qb_roles) != 1 or participation_field.starter_qb(eligible) != qb_roles[0]['gsis_id']:
        raise ValueError('live_participation_qb1_mismatch')
    participation_field.group_counts(group)
    if not any(g == group for _pos, g in field.position_prior):
        raise ValueError('live_participation_group_not_in_fitted_table:' + group)
    previous = previous or {}
    lineup = previous.get('lineup', {})
    if not set(lineup).issubset(allowed):
        raise ValueError('live_participation_previous_player_ineligible')
    result, details = field.advance(team, lineup, group, eligible, random.Random(seed),
                                    prev_group=previous.get('group'), slots=previous.get('slots'))
    if result is None or details.get('status') != 'ok':
        raise ValueError('live_participation_lineup_unavailable:' + str(details.get('status')))
    if not set(result).issubset(allowed):
        raise AssertionError('live_participation_ineligible_selection')
    return {'group': group, 'lineup': result, 'slots': details['slots'], 'qb1': qb_roles[0]['gsis_id'],
            'source_sha256': field.sha256, 'fit_seasons': list(field.seasons), 'selection': details,
            'scope': 'offensive_skill_players_only',
            'source_integrity': 'sha256_checked' if field.file_hash_verified else 'synthetic'}


def offense_lineup(field, *, team, season, resolved, roster, group, formation, formation_priors, state, seed,
                   previous=None, allow_synthetic=False, formation_verifier=None):
    """Resolve a standard five-lineman offense with an existing fitted grouping.

    Skill-player rotation uses the historical field; the five line positions
    use the eligible depth-chart order. Route assignment and field coordinates
    are not inferred by this function.
    """
    import formation_layer
    if '-' in group:
        raise ValueError('live_offense_nonstandard_personnel_unsupported:' + group)
    formation_seasons = formation_priors.get('seasons') or []
    if not formation_seasons or max(formation_seasons) >= int(season):
        raise ValueError('live_offense_formation_training_cutoff_invalid')
    canonical_team = team_codes.normalize('nfl', team)
    if not formation or formation_layer.formation_distribution(formation_priors, state, group, canonical_team).get(formation, 0) <= 0:
        raise ValueError('live_offense_formation_not_supported:' + str(formation))
    if not allow_synthetic and (formation_verifier is None or formation_verifier(formation_priors, season) is not True):
        raise ValueError('live_offense_formation_source_not_verified')
    selected = advance(field, team=team, season=season, resolved=resolved, roster=roster, group=group,
                       seed=seed, previous=previous, allow_synthetic=allow_synthetic)
    allowed = v1_complete_roster.eligible_ids(resolved)
    players = {selected['qb1']: 'QB', **selected['slots']}
    for role in ('LT', 'LG', 'C', 'RG', 'RT'):
        candidates = [p for p in roster if p.get('gsis_id') in allowed and p.get('gsis_id') not in players
                      and p.get('pos_abb') == role and type(p.get('pos_rank')) is int and p['pos_rank'] > 0]
        if not candidates:
            raise ValueError('live_offense_unresolved_line_role:' + role)
        best = min(p['pos_rank'] for p in candidates)
        top = {p['gsis_id'] for p in candidates if p['pos_rank'] == best}
        if len(top) != 1:
            raise ValueError('live_offense_ambiguous_line_role:' + role)
        players[top.pop()] = role
    if len(players) != 11:
        raise ValueError('live_offense_wrong_player_count:' + str(len(players)))
    return {**selected, 'formation': formation, 'players': players, 'scope': 'offense_11',
            'line_selection': 'eligible_depth_chart', 'routes': 'unsupported',
            'defensive_lineup': 'unsupported'}


def choose_offense(field, *, team, season, resolved, roster, formation_priors, state, p_dropback, seed, previous=None,
                   allow_synthetic=False, formation_verifier=None):
    """Draw the existing personnel and formation prior before the call."""
    import formation_layer
    seasons = formation_priors.get('seasons') or []
    if not seasons or max(seasons) >= int(season):
        raise ValueError('live_offense_formation_training_cutoff_invalid')
    if not allow_synthetic and (formation_verifier is None or formation_verifier(formation_priors, season) is not True):
        raise ValueError('live_offense_formation_source_not_verified')
    previous_group = (previous or {}).get('group', formation_layer.START)
    group, formation, p_given = formation_layer.personnel_first(
        formation_priors, p_dropback, state, previous_group, str(seed), team=team_codes.normalize('nfl', team))
    result = offense_lineup(field, team=team, season=season, resolved=resolved, roster=roster, group=group,
                            formation=formation, formation_priors=formation_priors, state=state, seed=seed,
                            previous=previous, allow_synthetic=allow_synthetic, formation_verifier=formation_verifier)
    result['p_dropback_given_personnel_formation'] = p_given
    result['formation_fit_seasons'] = list(seasons)
    return result


def defense_lineup(*, resolved, roster, positions):
    """Resolve explicit defensive positions by eligible depth order.

    The caller supplies positions for the intended defensive front. This does
    not claim to fit a defensive formation or coverage assignment.
    """
    if len(positions) != 11:
        raise ValueError('live_defense_requires_eleven_positions')
    allowed = v1_complete_roster.eligible_ids(resolved)
    selected = {}
    for position in positions:
        candidates = [p for p in roster if p.get('gsis_id') in allowed and p.get('gsis_id') not in selected
                      and p.get('pos_abb') == position and type(p.get('pos_rank')) is int and p['pos_rank'] > 0]
        if not candidates:
            raise ValueError('live_defense_unresolved_role:' + str(position))
        best = min(p['pos_rank'] for p in candidates)
        top = {p['gsis_id'] for p in candidates if p['pos_rank'] == best}
        if len(top) != 1:
            raise ValueError('live_defense_ambiguous_role:' + str(position))
        selected[top.pop()] = position
    return {'players': selected, 'scope': 'defense_11', 'selection': 'eligible_depth_chart',
            'coverage': 'unsupported', 'defensive_front_source': 'caller_supplied'}


def bind_field_inputs(*, offense, defense, offense_roster, defense_roster, assignments):
    """Attach caller-supplied assignments and motion to already selected players.

    Motion, routes and ratings are not created by participation data. The live
    field must separately validate their evidence and timing.
    """
    if offense.get('scope') != 'offense_11' or defense.get('scope') != 'defense_11':
        raise ValueError('live_participation_lineups_required')
    ids = set(offense['players']) | set(defense['players'])
    if len(ids) != 22 or set(assignments) != ids:
        raise ValueError('live_participation_assignments_incomplete')
    results = []
    for chosen, roster in ((offense, offense_roster), (defense, defense_roster)):
        entries = []
        for pid, role in chosen['players'].items():
            choices = [p for p in roster if p.get('gsis_id') == pid and
                       (p.get('pos_abb') == role or role == 'RB' and p.get('pos_abb') == 'FB')]
            if not choices:
                raise ValueError('live_participation_roster_position_missing:' + pid)
            record = dict(assignments[pid])
            if 'player_id' in record or 'position' in record:
                raise ValueError('live_participation_identity_override:' + pid)
            record.update(player_id=pid, position=choices[0]['pos_abb'])
            entries.append(record)
        results.append(entries)
    return tuple(results)
