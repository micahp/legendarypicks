import pytest

import live_participation as lp
import participation_field as pf
from test_formation_layer import personnel_first_table
from test_participation_field import _data, _player, _roster


def priors():
    return {**personnel_first_table(), 'seasons': [2024]}


def inputs():
    field = pf.Field(_data(seasons=[2024]), 'a' * 64)
    roster = _roster() + [_player(role.lower(), role) for role in ('LT', 'LG', 'C', 'RG', 'RT')]
    players = [{'gsis_id': p['gsis_id'], 'pos': p['pos_abb'], 'official_eligible': True,
                'membership': 'ACTIVE_ROSTER', 'exclusion_reason': None} for p in roster]
    resolved = {'schema': 'lp-nfl-resolved-roster-2', 'team': 'KC', 'blocks': [], 'players': players,
                'roles': [{'role': 'QB1', 'status': 'ASSIGNED', 'gsis_id': 'qb1', 'required': True}]}
    return field, roster, resolved


def test_uses_fitted_skill_field_and_eligible_depth_chart_for_eleven():
    field, roster, resolved = inputs()
    args = dict(team='KC', season=2026, resolved=resolved, roster=roster, group='11', formation='SHOTGUN',
                formation_priors=priors(), state={'quarter': 1, 'clock': 600, 'down': 1, 'togo': 10},
                seed=7, allow_synthetic=True)
    result = lp.offense_lineup(field, **args)
    assert len(result['players']) == 11
    assert set(result['players'].values()) >= {'QB', 'RB', 'TE', 'WR', 'LT', 'LG', 'C', 'RG', 'RT'}
    assert result['routes'] == 'unsupported'
    assert result['players'] == lp.offense_lineup(field, **args)['players']


def test_excluded_player_and_missing_line_role_fail_closed():
    field, roster, resolved = inputs()
    next(p for p in resolved['players'] if p['gsis_id'] == 'lt')['official_eligible'] = False
    with pytest.raises(ValueError, match='live_offense_unresolved_line_role:LT'):
        lp.offense_lineup(field, team='KC', season=2026, resolved=resolved, roster=roster, group='11',
                          formation='SHOTGUN', formation_priors=priors(),
                          state={'quarter': 1, 'clock': 600, 'down': 1, 'togo': 10}, seed=7, allow_synthetic=True)


def test_rejects_future_fit_and_unsupported_formation():
    field, roster, resolved = inputs()
    with pytest.raises(ValueError, match='live_participation_training_cutoff_invalid'):
        lp.advance(field, team='KC', season=2024, resolved=resolved, roster=roster, group='11', seed=7)
    with pytest.raises(ValueError, match='live_participation_source_not_verified'):
        lp.advance(field, team='KC', season=2026, resolved=resolved, roster=roster, group='11', seed=7)
    with pytest.raises(ValueError, match='live_offense_formation_not_supported'):
        lp.offense_lineup(field, team='KC', season=2026, resolved=resolved, roster=roster, group='11',
                          formation='MADE UP', formation_priors=priors(),
                          state={'quarter': 1, 'clock': 600, 'down': 1, 'togo': 10}, seed=7)


def test_defense_resolves_only_explicit_eligible_positions():
    _field, roster, resolved = inputs()
    roster += [_player('def' + str(i), 'DB', i) for i in range(1, 12)]
    resolved['players'] += [{'gsis_id': 'def' + str(i), 'pos': 'DB', 'official_eligible': True,
                              'membership': 'ACTIVE_ROSTER', 'exclusion_reason': None} for i in range(1, 12)]
    result = lp.defense_lineup(resolved=resolved, roster=roster, positions=['DB'] * 11)
    assert len(result['players']) == 11
    assert result['coverage'] == 'unsupported'
    resolved['players'][-1]['membership'] = 'RESERVE'
    with pytest.raises(ValueError, match='live_defense_unresolved_role:DB'):
        lp.defense_lineup(resolved=resolved, roster=roster, positions=['DB'] * 11)


def test_chosen_personnel_and_formation_precede_the_call():
    field, roster, resolved = inputs()
    field.position_prior[('RB', '12')] = 0.5
    state = {'quarter': 1, 'clock': 600, 'down': 1, 'togo': 10}
    one = lp.choose_offense(field, team='KC', season=2026, resolved=resolved, roster=roster,
                                formation_priors=priors(), state=state, p_dropback=0.2, seed=7, allow_synthetic=True)
    two = lp.choose_offense(field, team='KC', season=2026, resolved=resolved, roster=roster,
                                formation_priors=priors(), state=state, p_dropback=0.8, seed=7, allow_synthetic=True)
    assert (one['group'], one['formation'], one['players']) == (two['group'], two['formation'], two['players'])
    assert len(one['players']) == 11


def test_field_binding_requires_assignments_for_both_lineups():
    offense_roster = [_player('o' + str(i), 'QB' if i == 0 else 'WR', i + 1) for i in range(11)]
    defense_roster = [_player('d' + str(i), 'DB', i + 1) for i in range(11)]
    offense = {'scope': 'offense_11', 'players': {p['gsis_id']: p['pos_abb'] for p in offense_roster}}
    defense = {'scope': 'defense_11', 'players': {p['gsis_id']: p['pos_abb'] for p in defense_roster}}
    assignments = {pid: {'assignment': 'supplied'} for pid in list(offense['players']) + list(defense['players'])}
    left, right = lp.bind_field_inputs(offense=offense, defense=defense, offense_roster=offense_roster,
                                       defense_roster=defense_roster, assignments=assignments)
    assert len(left) == len(right) == 11
    del assignments['d0']
    with pytest.raises(ValueError, match='live_participation_assignments_incomplete'):
        lp.bind_field_inputs(offense=offense, defense=defense, offense_roster=offense_roster,
                             defense_roster=defense_roster, assignments=assignments)
