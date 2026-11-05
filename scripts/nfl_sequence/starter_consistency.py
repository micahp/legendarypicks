"""Check starters announced in the news evidence against the snapshot's depth-chart starters.

The snapshot names a starter by depth rank 1 at a position. A coach-announced starter in the news (starter_named or
coach_confirmation_reported) is compared with that rank-1 player. Only positions with a single starter are checked
(QB). A position with several starters, such as WR, cannot be checked against rank 1 alone, so it is counted as not
checked rather than as agreement.

Rules:
- An announced starter that differs from the rank-1 player stops the run (conflicts).
- An expected starter (starter_expected) that differs is reported, not refused (notes).
- A check that cannot be made (no rank-1 player for the position) is counted as unverified, never as agreement.
- Two rank-1 players at one team and position is a malformed snapshot, and the check fails loudly.

Nothing here changes the snapshot or any workload input. It only reads them.
"""
from __future__ import annotations

from collections import Counter

ANNOUNCED = ('starter_named', 'coach_confirmation_reported')
EXPECTED = ('starter_expected',)
SINGLE_STARTER_POSITIONS = frozenset({'QB'})


def depth_rank_one(snapshot):
    """{(team, pos_abb): player} for depth rank 1. Raises if one team and position has two rank-1 players."""
    out = {}
    for side in ('away', 'home'):
        roster = snapshot['rosters'][side]
        for player in roster['players']:
            if player.get('pos_rank') != 1 or not player.get('pos_abb'):
                continue
            key = (roster['team'], player['pos_abb'])
            if key in out:
                raise ValueError(f'snapshot has two depth rank 1 players for {key}; refusing to pick one')
            out[key] = player
    return out


def _has_starter_flags(snapshot):
    return any('starter' in player for side in ('away', 'home') for player in snapshot['rosters'][side]['players'])


def starters(snapshot):
    """({(team, pos_abb): player}, source). Uses the pinned starter flags when the overlay is applied, else depth rank 1.

    The source is recorded so a preview cannot be mistaken for the pinned roster. A position with two flagged starters
    cannot be a single-starter position, so it fails loudly.
    """
    if not _has_starter_flags(snapshot):
        return depth_rank_one(snapshot), 'depth rank 1 (preview)'
    out = {}
    for side in ('away', 'home'):
        roster = snapshot['rosters'][side]
        for player in roster['players']:
            if not player.get('starter') or not player.get('pos_abb'):
                continue
            key = (roster['team'], player['pos_abb'])
            if key in out and player['pos_abb'] in SINGLE_STARTER_POSITIONS:
                raise ValueError(f'roster flags two starters for {key}; a single-starter position cannot have two')
            out.setdefault(key, player)
    return out, 'pinned starter flag'


def check(snapshot, items):
    """Compare announced and expected starters in the evidence items with depth rank 1.

    Returns {'counts': {...}, 'conflicts': [...], 'notes': [...]}. Every count is reported, including zeros.
    """
    lookup, source = starters(snapshot)
    counts = Counter({'announced checked': 0, 'announced agrees': 0, 'announced differs': 0,
                      'announced unverified': 0, 'announced not checked (multi-starter position)': 0,
                      'expected checked': 0, 'expected agrees': 0, 'expected differs': 0,
                      'expected unverified': 0, 'expected not checked (multi-starter position)': 0})
    conflicts, notes = [], []
    for item in items:
        classes = {c['class'] for c in item['classes']}
        kind = 'announced' if classes & set(ANNOUNCED) else 'expected' if classes & set(EXPECTED) else None
        if kind is None:
            continue
        player = item['player']
        position = player.get('position')
        if position not in SINGLE_STARTER_POSITIONS:
            counts[f'{kind} not checked (multi-starter position)'] += 1
            continue
        counts[f'{kind} checked'] += 1
        starter = lookup.get((item['team'], position))
        if starter is None:
            counts[f'{kind} unverified'] += 1
            notes.append({'kind': kind, 'update_id': item.get('update_id'), 'team': item['team'], 'position': position,
                          'reason': 'no depth rank 1 for this team and position'})
            continue
        if starter['gsis_id'] == player['gsis_id']:
            counts[f'{kind} agrees'] += 1
            continue
        counts[f'{kind} differs'] += 1
        record = {'kind': kind, 'update_id': item.get('update_id'), 'team': item['team'], 'position': position,
                  'announced_gsis_id': player['gsis_id'], 'announced_name': player.get('name'),
                  'depth_rank_one_gsis_id': starter['gsis_id'], 'depth_rank_one_name': starter.get('player_name')}
        (conflicts if kind == 'announced' else notes).append(record)
    return {'counts': dict(counts), 'conflicts': conflicts, 'notes': notes, 'starter_source': source}


def summary_line(result):
    counts = result['counts']
    keys = ('announced checked', 'announced agrees', 'announced differs', 'announced unverified',
            'expected checked', 'expected agrees', 'expected differs', 'expected unverified')
    values = {k: counts.get(k, 0) for k in keys}
    return ('starter consistency against {source}: announced {announced checked} checked, {announced agrees} agree, '
            '{announced differs} differ, {announced unverified} unverified; expected {expected checked} checked, '
            '{expected agrees} agree, {expected differs} differ, {expected unverified} unverified').format(
        source=result['starter_source'], **values)
