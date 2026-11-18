"""Deterministic pregame roster resolution, contract lp-nfl-resolved-roster-2 (SLC-NFL-ROSTER-RESOLUTION-V2), first slice.

Pure functions over explicit evidence. The same roster, events, cutoff and role request always give the same canonical
output and content hash. Nothing here reads a database or the network; source capture is separate work.

A block names a condition that must stop a scenario. Roster-quality blocks are reported apart from football results.
"""
from __future__ import annotations

import hashlib
import json
import re

SCHEMA = 'lp-nfl-resolved-roster-2'
RESOLVER_VERSION = 'roster-resolution-v2-slice1'
FORECAST_CLASSES = ('PROVISIONAL', 'UPDATED_PROVISIONAL', 'GAMEDAY_FINAL')
ON_ROSTER = ('ACTIVE_ROSTER', 'ELEVATED')
TIMESTAMP = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')

# kind -> (membership it creates, membership it may only be applied from, or None for any)
TRANSITIONS = {
    'signing_active': ('ACTIVE_ROSTER', None),
    'signing_practice': ('PRACTICE_SQUAD', None),
    'elevation': ('ELEVATED', 'PRACTICE_SQUAD'),
    'ir': ('RESERVE', None),
    'activation': ('ACTIVE_ROSTER', 'RESERVE'),
    'suspension': ('SUSPENDED', None),
    'release': ('DEPARTED', None),
    'trade_away': ('DEPARTED', None),
    'return_to_practice': (None, None),  # a practice designation changes no membership
}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _check_timestamp(value, label):
    if not isinstance(value, str) or not TIMESTAMP.match(value):
        raise ValueError(f'{label} must be a UTC timestamp like 2026-11-17T22:00:00Z, got {value!r}')


def _check_inputs(as_of, events, forecast_class):
    _check_timestamp(as_of, 'as_of')
    if forecast_class not in FORECAST_CLASSES:
        raise ValueError(f'forecast_class must be one of {FORECAST_CLASSES}, got {forecast_class!r}')
    ids = set()
    for event in events:
        _check_timestamp(event['observed_utc'], f"event {event.get('id')} observed_utc")
        if event.get('effective_utc') is not None:
            _check_timestamp(event['effective_utc'], f"event {event.get('id')} effective_utc")
        if event['kind'] not in TRANSITIONS:
            raise ValueError(f"event {event.get('id')} has unknown kind {event['kind']!r}")
        if event['id'] in ids:
            raise ValueError(f"duplicate event id {event['id']!r}")
        ids.add(event['id'])


def _visible(events, as_of):
    """Events whose result was observed by the cutoff and whose effective time is not after it. Others are not evidence
    for this snapshot and are left out of the output entirely, so a later update cannot change an earlier hash."""
    used = []
    for event in events:
        effective = event.get('effective_utc') or event['observed_utc']
        if event['observed_utc'] <= as_of and effective <= as_of:
            used.append(dict(event, effective_utc=effective))
    return sorted(used, key=lambda e: (e['effective_utc'], e['observed_utc'], e['id']))


def _membership(row, events):
    """(membership, applied event ids, reasons). A transition from the wrong state, or two different results at one
    effective time, is a contradiction: the membership becomes UNKNOWN rather than a guess (rule 9)."""
    applied = []
    real = [e for e in events if TRANSITIONS[e['kind']][0] is not None]
    by_time = {}
    for event in real:
        by_time.setdefault(event['effective_utc'], set()).add(TRANSITIONS[event['kind']][0])
    for when in sorted(by_time):
        if len(by_time[when]) > 1:
            return 'UNKNOWN', applied, [f'conflicting_transactions_at_{when}']
    state = row['membership']
    for event in real:
        target, required_from = TRANSITIONS[event['kind']]
        if required_from is not None and state != required_from:
            return 'UNKNOWN', applied, [f"{event['kind']}_from_{state}_not_{required_from}"]
        state = target
        applied.append(event['id'])
    return state, applied, []


def _eligibility(row, membership, inactives):
    """(official_eligible, flags, exclusion reason). Official inactives and Out designations exclude; questionable and
    doubtful stay in with a flag; a missing report is never read as healthy."""
    if membership not in ON_ROSTER:
        return False, [], f'membership_{membership.lower()}'
    if row['gsis_id'] in inactives:
        return False, [], 'official_inactive'
    injury = row.get('injury')
    if injury == 'OUT':
        return False, [], 'injury_out'
    flags = []
    if injury == 'MISSING':
        flags.append('injury_report_missing')
    elif injury in ('QUESTIONABLE', 'DOUBTFUL'):
        flags.append(f'game_status_{injury.lower()}')
    if injury == 'DOUBTFUL':
        flags.append('conditional_baseline')
    return True, flags, None


def _pick(role, players, taken):
    """(status, gsis_id, basis, extra, block). Explicit starters first, then depth rank, then the unique candidate, then
    the practice-squad emergency rule. Never ordered by name, jersey or id. `taken` holds players already filling a role
    in this role group, so one person cannot fill two starter slots of the same group."""
    if role.get('announced_starter') in taken:
        return 'UNRESOLVED', None, 'announced_starter_already_assigned', None, 'duplicate_role_assignment'
    pool = [p for p in players if p['pos'] in role['positions'] and p['gsis_id'] not in taken]
    eligible = [p for p in pool if p['official_eligible']]
    announced = role.get('announced_starter')
    if announced:
        match = next((p for p in pool if p['gsis_id'] == announced), None)
        if match is None:
            return 'UNRESOLVED', None, 'announced_starter_not_on_roster', None, 'starter_not_on_roster'
        if not match['official_eligible']:
            return 'UNRESOLVED', None, 'announced_starter_ineligible', None, 'starter_officially_ineligible'
        return 'ASSIGNED', announced, 'announced_starter', {'depth_rank': match['depth_rank']}, None
    ranked = sorted((p for p in eligible if p['depth_rank'] is not None), key=lambda p: p['depth_rank'])
    unranked = sorted((p for p in eligible if p['depth_rank'] is None), key=lambda p: p['gsis_id'])
    if ranked:
        top = ranked[0]
        ranked_all = [p['depth_rank'] for p in pool if p['depth_rank'] is not None]
        ahead = sorted(p['gsis_id'] for p in pool if p['depth_rank'] is not None
                       and p['depth_rank'] < top['depth_rank'] and not p['official_eligible'])
        extra = {'depth_rank': top['depth_rank'], 'promoted': bool(ahead), 'excluded_ranked_ahead': ahead,
                 'first_depth_rank': min(ranked_all)}
        return 'ASSIGNED', top['gsis_id'], 'depth_rank', extra, None
    if len(unranked) == 1:
        return 'ASSIGNED', unranked[0]['gsis_id'], 'unique_candidate', {'depth_rank': None}, None
    if len(unranked) > 1:
        return 'UNRESOLVED', None, 'multiple_unranked_candidates', None, _block(role)
    squad = [p for p in pool if p['membership'] == 'PRACTICE_SQUAD']
    if len(squad) == 1:
        return 'PROJECTED', squad[0]['gsis_id'], 'sole_practice_squad_candidate', {'depth_rank': None}, None
    if len(squad) > 1:
        return 'UNRESOLVED', None, 'several_practice_squad_candidates', None, _block(role)
    return 'UNRESOLVED', None, 'no_candidate', None, _block(role)


def _block(role):
    if not role.get('required'):
        return None
    if role.get('kind') == 'PK':
        return 'unresolved_kicking_role'
    if role['role'] == 'QB1':
        return 'unresolved_QB1'
    return f"unresolved_{role['role']}"


def resolve_team(game_id, team, as_of, roster, events, roles, inactives=(), inactives_verified=False,
                 forecast_class='PROVISIONAL'):
    """One team's resolved roster for one game at one cutoff. Returns a dict with a content_hash.

    A roster row must carry observed_utc at or before the cutoff; a missing or later one raises. A signing for a player
    who is not on the roster adds him, when the event carries name and pos; any other transaction for an unknown player
    blocks the roster."""
    _check_inputs(as_of, events, forecast_class)
    used = _visible(events, as_of)
    blocks = set()
    known = {}
    for row in roster:
        if 'observed_utc' not in row:
            raise ValueError(f"roster row {row['gsis_id']} has no observed_utc")
        _check_timestamp(row['observed_utc'], f"roster row {row['gsis_id']} observed_utc")
        if row['observed_utc'] > as_of:
            raise ValueError(f"roster row {row['gsis_id']} was observed after the cutoff {as_of}; refuse, do not drop")
        known[row['gsis_id']] = row
    for event in used:
        if event['gsis_id'] in known:
            continue
        if event['kind'].startswith('signing_') and event.get('name') and event.get('pos'):
            known[event['gsis_id']] = {'gsis_id': event['gsis_id'], 'name': event['name'], 'pos': event['pos'],
                                       'membership': 'UNKNOWN', 'depth_rank': None, 'injury': None,
                                       'observed_utc': event['observed_utc']}
        else:
            blocks.add('transaction_for_unidentified_player')
    players = []
    by_id = {}
    for gsis in sorted(known):
        row = known[gsis]
        mine = [e for e in used if e['gsis_id'] == gsis]
        membership, applied, reasons = _membership(row, mine)
        if reasons:
            blocks.add('contradictory_membership')
        eligible, flags, reason = _eligibility(row, membership, inactives)
        player = {'gsis_id': gsis, 'name': row['name'], 'pos': row['pos'], 'depth_rank': row.get('depth_rank'),
                  'membership': membership, 'official_eligible': eligible, 'projected_participant': eligible,
                  'projection_status': None, 'flags': sorted(flags + reasons), 'exclusion_reason': reason,
                  'events_applied': applied}
        players.append(player)
        by_id[gsis] = player
    roles_out = []
    taken = {}
    for role in sorted(roles, key=lambda r: r['role']):
        group = role.get('group')
        status, gsis_id, basis, extra, block = _pick(role, players, taken.get(group, set()))
        if block:
            blocks.add(block)
        if gsis_id is not None and group is not None:
            taken.setdefault(group, set()).add(gsis_id)
        if status == 'PROJECTED':
            by_id[gsis_id]['projected_participant'] = True
            by_id[gsis_id]['projection_status'] = 'PROJECTED_ELEVATION'
            if forecast_class == 'GAMEDAY_FINAL':
                blocks.add('gameday_final_unverified_elevation')
        roles_out.append({'role': role['role'], 'kind': role.get('kind'), 'group': group,
                          'required': bool(role.get('required')), 'status': status, 'gsis_id': gsis_id,
                          'basis': basis, 'extra': extra or {}})
    if forecast_class == 'GAMEDAY_FINAL' and not inactives_verified:
        blocks.add('gameday_final_unverified_inactives')
    body = {'schema': SCHEMA, 'resolver_version': RESOLVER_VERSION, 'game_id': game_id, 'team': team,
            'as_of_utc': as_of, 'forecast_class': forecast_class, 'players': players, 'roles': roles_out,
            'blocks': sorted(blocks),
            'input_fingerprint': _digest({'roster': sorted(roster, key=lambda r: r['gsis_id']), 'events': used,
                                          'roles': sorted(roles, key=lambda r: r['role']),
                                          'inactives': sorted(inactives), 'inactives_verified': inactives_verified})}
    body['content_hash'] = _digest(body)
    return body


def check_matchup(results):
    """Blocks for a matchup: a player may not hold active membership with both teams."""
    seen = {}
    blocks = set()
    for result in results:
        for player in result['players']:
            if player['membership'] in ON_ROSTER:
                if player['gsis_id'] in seen and seen[player['gsis_id']] != result['team']:
                    blocks.add('double_membership')
                seen[player['gsis_id']] = result['team']
    return sorted(blocks)
