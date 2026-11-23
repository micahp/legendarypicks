"""One-play research entry point using existing SLC personnel and participation fits.

The caller supplies the existing play-call probability, defensive front, routes,
movement and QB/throw/catch behavior. No missing input is fitted here.
"""
import live_field
import live_participation


def dropback(state, *, field, offense_team, season, offense_resolved, defense_resolved, offense_roster,
             defense_roster, formation_priors, p_dropback, seed, defense_positions, call_selector,
             assignment_builder, as_of, times, qb_policy, throw=None, catch=None, scramble=None,
             previous=None, allow_synthetic=False, rating_verifier=None, formation_verifier=None):
    """Select players, formation and call, then execute the supported live dropback."""
    offense = live_participation.choose_offense(
        field, team=offense_team, season=season, resolved=offense_resolved, roster=offense_roster,
        formation_priors=formation_priors, state=state, p_dropback=p_dropback, seed=seed, previous=previous,
        allow_synthetic=allow_synthetic, formation_verifier=formation_verifier)
    defense = live_participation.defense_lineup(resolved=defense_resolved, roster=defense_roster,
                                                positions=defense_positions)
    call = call_selector(offense['p_dropback_given_personnel_formation'])
    if call != 'dropback':
        raise ValueError('live_one_play_non_dropback_unsupported:' + str(call))
    assignments = assignment_builder(offense, defense)
    offense_field, defense_field = live_participation.bind_field_inputs(
        offense=offense, defense=defense, offense_roster=offense_roster, defense_roster=defense_roster,
        assignments=assignments)
    result = live_field.dropback(
        state, offense=offense_field, defense=defense_field,
        resolved={'offense': offense_resolved, 'defense': defense_resolved}, as_of=as_of,
        formation=offense['formation'], call=call, times=times, qb_policy=qb_policy,
        throw=throw, catch=catch, scramble=scramble, allow_synthetic=allow_synthetic,
        rating_verifier=rating_verifier, formation_verifier=formation_verifier)
    return {'offense': offense, 'defense': defense, 'call': call, 'live_result': result}
