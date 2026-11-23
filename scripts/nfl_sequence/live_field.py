"""A bounded, data-supplied live field for one dropback.

Players move at their assigned constant velocity. This is not a fitted NFL
movement model: inputs, assignments and data provenance must be supplied.
"""
import datetime
import math
import re

import v1_complete_roster


def _timestamp(value):
    try:
        parsed = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, ValueError):
        raise ValueError('live_field_invalid_timestamp')
    if parsed.tzinfo is None:
        raise ValueError('live_field_invalid_timestamp')
    return parsed


def validate_lineups(offense, defense, resolved, as_of, *, allow_synthetic=False, rating_verifier=None):
    cutoff = _timestamp(as_of)
    allowed = {side: v1_complete_roster.eligible_ids(resolved[side]) for side in ('offense', 'defense')}
    all_ids = []
    for side, lineup in (('offense', offense), ('defense', defense)):
        if not allow_synthetic and _timestamp(resolved[side].get('as_of_utc')) != cutoff:
            raise ValueError('live_field_roster_cutoff_mismatch:' + side)
        if len(lineup) != 11:
            raise ValueError('live_field_requires_eleven:' + side)
        positions = {}
        for player in resolved[side]['players']:
            positions.setdefault(player['gsis_id'], set()).add(player['pos'])
        for p in lineup:
            pid = p.get('player_id')
            if not pid or pid not in allowed[side]:
                raise ValueError('live_field_ineligible_player:' + str(pid))
            assignments = ('quarterback', 'route', 'block') if side == 'offense' else ('coverage', 'rush')
            if p.get('position') not in positions.get(pid, set()) or p.get('assignment') not in assignments:
                raise ValueError('live_field_missing_assignment:' + pid)
            rating = p.get('speed_rating') or {}
            kind = rating.get('evidence_type')
            if kind == 'synthetic':
                if not allow_synthetic:
                    raise ValueError('live_field_synthetic_rating_not_allowed:' + pid)
            elif kind in ('observed', 'estimated'):
                if rating_verifier is None or rating_verifier(pid, rating, as_of) is not True:
                    raise ValueError('live_field_rating_not_verified:' + pid)
            else:
                raise ValueError('live_field_rating_unsupported:' + pid)
            sha = rating.get('source_sha256', '')
            if (not rating.get('source') or not isinstance(sha, str) or not re.fullmatch(r'[a-f0-9]{64}', sha)
                    or _timestamp(rating.get('observed_at')) > cutoff):
                raise ValueError('live_field_invalid_rating_provenance:' + pid)
            speed = rating.get('max_yards_per_second')
            values = (p.get('x'), p.get('y'), p.get('vx'), p.get('vy'), speed)
            if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in values):
                raise ValueError('live_field_invalid_motion:' + pid)
            if speed < 0 or math.hypot(p['vx'], p['vy']) > speed:
                raise ValueError('live_field_speed_exceeds_rating:' + pid)
            if side == 'defense' and (not isinstance(p.get('reach'), (int, float))
                                      or not math.isfinite(p['reach']) or p['reach'] < 0):
                raise ValueError('live_field_invalid_reach:' + pid)
            all_ids.append(pid)
    if len(set(all_ids)) != 22:
        raise ValueError('live_field_duplicate_player')
    qbs = [p for p in offense if p['assignment'] == 'quarterback']
    if len(qbs) != 1 or qbs[0]['position'] != 'QB':
        raise ValueError('live_field_requires_one_quarterback')
    if not any(p['assignment'] == 'route' for p in offense):
        raise ValueError('live_field_requires_route')


def observations(offense, defense, *, times):
    """Yield successive positions from validated pre-snap assignments.

    The caller must validate the lineups first. Each time is elapsed since the
    snap. No future position is provided to the quarterback policy.
    """
    previous = -1.0
    for seconds in times:
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0 or seconds <= previous:
            raise ValueError('live_field_non_increasing_time')
        if previous < 0 and seconds != 0:
            raise ValueError('live_field_first_observation_must_be_snap')
        previous = seconds
        def at(p):
            return {'player_id': p['player_id'], 'x': p['x'] + p['vx'] * seconds,
                    'y': p['y'] + p['vy'] * seconds}
        qb = next(p for p in offense if p['assignment'] == 'quarterback')
        yield {'seconds': seconds, 'qb': at(qb),
               'receivers': [at(p) for p in offense if p['assignment'] == 'route'],
               'defenders': [dict(at(p), reach=p['reach']) for p in defense]}


def dropback(state, *, offense, defense, resolved, as_of, formation, call, times, qb_policy, throw=None, catch=None,
             scramble=None, allow_synthetic=False, rating_verifier=None, formation_verifier=None):
    """Run one named dropback from validated personnel through the whistle reducer."""
    validate_lineups(offense, defense, resolved, as_of, allow_synthetic=allow_synthetic, rating_verifier=rating_verifier)
    if not isinstance(formation, str) or not formation.strip():
        raise ValueError('live_field_formation_required')
    if not allow_synthetic and (formation_verifier is None or formation_verifier(offense, formation, as_of) is not True):
        raise ValueError('live_field_formation_not_verified')
    if call != 'dropback':
        raise ValueError('live_field_unsupported_call')
    motion = {p['player_id']: p for p in offense + defense}
    def checked_throw(observation, decision):
        flight, moving = throw(observation, decision)
        for player in moving:
            p = motion.get(player.player_id)
            if p is None or not (math.isclose(player.vx, p['vx'], abs_tol=1e-9)
                                 and math.isclose(player.vy, p['vy'], abs_tol=1e-9)):
                raise ValueError('live_field_throw_velocity_mismatch:' + player.player_id)
        return flight, moving

    def checked_scramble(observation, decision):
        previous = None
        for frame in scramble(observation, decision):
            current = [frame['runner']] + frame['defenders']
            if previous is not None:
                dt = frame['seconds'] - previous['seconds']
                old = {p['player_id']: p for p in [previous['runner']] + previous['defenders']}
                if dt <= 0:
                    raise ValueError('live_scramble_non_increasing_time')
                for p in current:
                    prior, spec = old.get(p['player_id']), motion.get(p['player_id'])
                    if prior is None or spec is None or math.hypot(p['x'] - prior['x'], p['y'] - prior['y']) > (
                            spec['speed_rating']['max_yards_per_second'] * dt + 1e-9):
                        raise ValueError('live_field_scramble_speed_exceeded:' + p['player_id'])
            previous = frame
            yield frame

    import live_dropback
    result = live_dropback.play(state, observations(offense, defense, times=times), qb_policy,
                                offense_ids={p['player_id'] for p in offense},
                                defense_ids={p['player_id'] for p in defense},
                                throw=checked_throw if throw is not None else None, catch=catch,
                                scramble=checked_scramble if scramble is not None else None)
    result['input_classification'] = 'synthetic' if allow_synthetic else 'verifier_checked'
    return result
