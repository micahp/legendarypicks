"""Distinct evidence fields for one player in one matchup, and the contradictions between them.

Nothing here picks a winner silently. Each field keeps its source and its time, and the states are:

- roster: which team the player is on, per source, and whether the sources agree.
- injury: the latest RotoWire injury designation, and any later update that clears it.
- official_availability: player_game_availability for this game. Nothing stored means unknown, not active.
- projections: stored projections for this game, each checked against range rules. A failed check is listed, not fixed.
- starter: the latest starter claim about the player, with its class.

Unknown stays unknown. No state is ever set to 'active' because a source is silent.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

CLEAR = re.compile(
    r"good to go|"
    r"no (?:week \d+ )?injury designation|"
    r"does not carry an injury designation|"
    r"(?:not|no longer) (?:be )?(?:listed|on) (?:the )?injury report|"
    r"no longer (?:listed|on the injury report)|"
    r"fully cleared|cleared to play|cleared to return",
    re.IGNORECASE)

COUNT_EXACT = frozenset({'rec', 'tgt', 'att', 'cmp', 'int', 'sack', 'fum'})
COUNT_SUFFIX = ('_td', '_yds', '_att', '_rec', '_tgt', '_int', '_cmp', '_fum')
STARTER_CLASSES = ('starter_named', 'coach_confirmation_reported', 'starter_expected')


def _nonnegative(stat):
    return stat in COUNT_EXACT or stat.endswith(COUNT_SUFFIX)


def projection_problem(row):
    """Why a projection row cannot be right, or None. Rows with no range (point estimates) skip the range checks."""
    stat = (row.get('stat') or '').lower()
    mean, p10, p90 = row.get('mean'), row.get('p10'), row.get('p90')
    if mean is None:
        return 'no mean'
    if _nonnegative(stat):
        if mean < 0:
            return 'negative mean for a count or yardage stat'
        if p10 is not None and p10 < 0:
            return 'negative lower bound for a count or yardage stat'
    if stat.endswith('_td') and mean > 4:
        return 'touchdown mean above 4 is implausible for one game'
    if p10 is not None and p90 is not None:
        if p10 > p90:
            return 'p10 above p90'
        if not (p10 <= mean <= p90):
            return 'mean outside its p10 to p90 range'
    return None


DESIGNATION_WINDOW = timedelta(days=7)


def _when(text):
    return datetime.fromisoformat(text)


def injury_state(updates):
    """updates: dicts with update_id, published_utc, injury_status, headline, notes, analysis (oldest or newest first).

    Returns the latest non-empty designation and any later update whose text clears it. A later designation-free update
    that says nothing about injury does not clear anything.
    """
    ordered = sorted(updates, key=lambda u: u['published_utc'])
    designated = [u for u in ordered if u.get('injury_status')]
    if not designated:
        return {'state': 'no_designation_recorded', 'designation': None, 'designation_update_id': None,
                'designation_published_utc': None, 'clears': []}
    latest = designated[-1]
    latest_time = _when(latest['published_utc'])
    recent = [u for u in designated if latest_time - _when(u['published_utc']) <= DESIGNATION_WINDOW]
    values = {}
    for u in recent:
        values.setdefault(u['injury_status'].upper(), []).append(u)
    disagreements = [
        {'status': status, 'update_id': us[-1]['update_id'], 'published_utc': us[-1]['published_utc']}
        for status, us in sorted(values.items())] if len(values) > 1 else []
    clears = [
        {'update_id': u['update_id'], 'published_utc': u['published_utc'],
         'text': (u.get('headline') or '')[:200]}
        for u in ordered
        if u['published_utc'] > latest['published_utc']
        and CLEAR.search(' '.join(filter(None, [u.get('headline'), u.get('notes'), u.get('analysis')])))
    ]
    state = 'contradicted' if clears else ('designations_disagree' if disagreements else 'designation')
    return {'state': state, 'designation': latest['injury_status'],
            'designation_update_id': latest['update_id'], 'designation_published_utc': latest['published_utc'],
            'clears': clears, 'disagreements': disagreements}


def roster_state(matchup_teams, depth_team, roster_team, news_team, players_team):
    """Per-source team claims for one player, and whether they agree with the matchup.

    depth_team: team on the current depth chart, or None. roster_team: team on the latest published roster, or None.
    news_team: team on the latest stored update, or None. players_team: players.team, or None.
    """
    sources = {'depth_chart': depth_team, 'published_roster': roster_team, 'latest_news': news_team,
               'players_row': players_team}
    teams = set(matchup_teams)
    if depth_team in teams:
        state = 'current_depth_chart'
    elif roster_team in teams:
        state = 'stale_roster_only'
    else:
        state = 'not_on_matchup_roster'
    conflicts = []
    if news_team and news_team not in teams and state != 'not_on_matchup_roster':
        conflicts.append(f'latest news says {news_team}, roster says {depth_team or roster_team}')
    if news_team and news_team not in teams and state == 'not_on_matchup_roster':
        conflicts.append(f'latest news says {news_team}, not a matchup team')
    if conflicts:
        state = 'conflict'
    return {'state': state, 'sources': sources, 'conflicts': conflicts}


def starter_state(claims):
    """claims: dicts with claim_class, attribution, update_id, published_utc, span (any order)."""
    relevant = [c for c in claims if c['claim_class'] in STARTER_CLASSES]
    if not relevant:
        return {'state': 'none_recorded', 'latest': None}
    latest = max(relevant, key=lambda c: c['published_utc'])
    announced = any(c['claim_class'] in ('starter_named', 'coach_confirmation_reported') for c in relevant)
    return {'state': 'announced' if announced else 'expected', 'latest': latest}


def contradictions(record):
    """The conflicts in one player's record, as short strings. Empty list means no conflict was found."""
    out = []
    injury = record.get('injury') or {}
    if injury.get('state') == 'contradicted':
        for clear in injury['clears']:
            out.append(f"injury: status {injury['designation']} (published {injury['designation_published_utc']}) "
                       f"is followed by a clearing update ({clear['published_utc']}): {clear['text']}")
    if injury.get('state') == 'designations_disagree':
        seen = '; '.join(f"{d['status']} ({d['published_utc']})" for d in injury['disagreements'])
        out.append(f'injury: designations disagree within seven days: {seen}')
    roster = record.get('roster') or {}
    for conflict in roster.get('conflicts', []):
        out.append(f'roster: {conflict}')
    for problem in record.get('projection_problems', []):
        out.append(f'projection: {problem}')
    if record.get('projected_but_not_rostered'):
        out.append('projection: this player has a projection for the game but is on neither roster')
    return out
