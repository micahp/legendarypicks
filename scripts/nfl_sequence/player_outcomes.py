"""Player-conditioned SLC event and result distributions from cutoff-safe nflverse plays.

The existing SLC cell supplies the contextual outcome distribution. This model
reweights its event and result draws by each selected player's prior outcome
profile, shrunk toward the corresponding league distribution. It changes the
play outcome before game-state reduction. Player lines use the corresponding
nflverse passing, receiving or rushing yard field when present.
"""
import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

MODEL_VERSION = 'slc-player-outcomes-v1'
FIRST_SEASON = 2022
PRIOR_STRENGTH = 40.0
MIN_RATIO = 0.25
MAX_RATIO = 4.0

QB_EVENTS = ('pass_complete', 'pass_incomplete', 'interception', 'sack')
RECEIVER_EVENTS = ('pass_complete', 'pass_incomplete', 'interception')
RUSHER_EVENTS = ('run', 'fumble_lost')
EVENTS = {'qb': QB_EVENTS, 'receiver': RECEIVER_EVENTS, 'rusher': RUSHER_EVENTS}
ROLE_ORDER = ('qb', 'receiver', 'rusher')


def normalize_roles(roles=None):
    """Return active outcome roles in canonical order; None selects the full model."""
    if roles is None:
        return ROLE_ORDER
    selected = set(roles)
    unknown = selected - set(ROLE_ORDER)
    if unknown:
        raise ValueError(f'unknown player-outcome roles: {sorted(unknown)}')
    if not selected:
        raise ValueError('player-outcome role selection cannot be empty')
    return tuple(role for role in ROLE_ORDER if role in selected)


def _yards_bin(yards, role, event):
    value = float(yards)
    if role == 'qb' and event == 'sack':
        if value <= -8:
            return '<=-8'
        if value <= -4:
            return '-7:-4'
        if value < 0:
            return '-3:-1'
        return '0+'
    if role == 'rusher':
        if value <= 0:
            return '<=0'
        if value <= 3:
            return '1-3'
        if value <= 9:
            return '4-9'
        if value <= 19:
            return '10-19'
        return '20+'
    if value <= 0:
        return '<=0'
    if value <= 4:
        return '1-4'
    if value <= 9:
        return '5-9'
    if value <= 19:
        return '10-19'
    return '20+'


def _player_id(participants, role):
    person = (participants or {}).get(role)
    return person.get('gsis_id') if isinstance(person, dict) else person


def _fit_rows(rows, cutoff, seasons):
    event_counts = {role: defaultdict(Counter) for role in EVENTS}
    base_events = {role: Counter() for role in EVENTS}
    result_counts = {role: defaultdict(lambda: defaultdict(Counter)) for role in EVENTS}
    base_results = {role: defaultdict(Counter) for role in EVENTS}
    team_player_events = {role: defaultdict(Counter) for role in EVENTS}
    source = Counter()
    row_stats = {}

    def add(role, player, team, event, yards=None, touchdown=False):
        event_counts[role][player][event] += 1
        base_events[role][event] += 1
        team_player_events[role][(team, player)][event] += 1
        if yards is not None:
            label = f"{_yards_bin(yards, role, event)}|td={int(bool(touchdown))}"
            result_counts[role][player][event][label] += 1
            base_results[role][event][label] += 1

    for row in rows:
        season = int(row['season'])
        if season not in seasons:
            continue
        row_key = (row.get('game_id'), int(row['play_id']))
        if row_key in row_stats:
            raise ValueError(f'duplicate player-outcome source row: {row_key}')
        row_stats[row_key] = {
            'yards_gained': row.get('yards_gained'),
            'passing_yards': row.get('passing_yards'),
            'receiving_yards': row.get('receiving_yards'),
            'rushing_yards': row.get('rushing_yards'),
            'pass_touchdown': row.get('pass_touchdown'),
            'touchdown': row.get('touchdown'),
            'rush_touchdown': row.get('rush_touchdown'),
        }
        team = row.get('posteam')
        qb = row.get('passer_player_id')
        receiver = row.get('receiver_player_id')
        rusher = row.get('rusher_player_id')
        if row.get('qb_dropback') == 1 and row.get('qb_scramble') != 1:
            if qb is None:
                source['qb_dropbacks_missing_id'] += 1
            elif row.get('passer_position') != 'QB':
                source['non_qb_passers_excluded'] += 1
            else:
                source['qb_dropbacks_with_id'] += 1
                if row.get('sack') == 1:
                    add('qb', qb, team, 'sack', row.get('yards_gained'), False)
                elif row.get('interception') == 1:
                    add('qb', qb, team, 'interception')
                elif row.get('pass_attempt') == 1 and row.get('complete_pass') == 1:
                    source['qb_completions_missing_passing_yards'] += int(row.get('passing_yards') is None)
                    add('qb', qb, team, 'pass_complete', row.get('passing_yards'), row.get('pass_touchdown'))
                elif row.get('pass_attempt') == 1 and row.get('complete_pass') == 0:
                    add('qb', qb, team, 'pass_incomplete')
        if row.get('pass_attempt') == 1:
            if receiver is None:
                source['targets_missing_receiver_id'] += 1
            else:
                source['targets_with_receiver_id'] += 1
                if row.get('interception') == 1:
                    event = 'interception'
                elif row.get('complete_pass') == 1:
                    event = 'pass_complete'
                elif row.get('complete_pass') == 0:
                    event = 'pass_incomplete'
                else:
                    event = None
                if event:
                    if event == 'pass_complete':
                        source['completions_missing_receiving_yards'] += int(row.get('receiving_yards') is None)
                        add('receiver', receiver, team, event, row.get('receiving_yards'), row.get('touchdown'))
                    else:
                        add('receiver', receiver, team, event)
        if row.get('rush_attempt') == 1:
            if rusher is None:
                source['rushes_missing_rusher_id'] += 1
            else:
                source['rushes_with_rusher_id'] += 1
                event = 'fumble_lost' if row.get('fumble_lost') == 1 else 'run'
                source['rushes_missing_rushing_yards'] += int(row.get('rushing_yards') is None)
                add('rusher', rusher, team, event, row.get('rushing_yards'), row.get('rush_touchdown'))

    units = {role: len(event_counts[role]) for role in EVENTS}
    for role in EVENTS:
        event_counts[role] = dict(event_counts[role])
        result_counts[role] = {player: {event: Counter(outcomes) for event, outcomes in by_event.items()}
                               for player, by_event in result_counts[role].items()}
        team_player_events[role] = dict(team_player_events[role])
    serial = {
        'events': {role: sorted((str(pid), sorted(c.items())) for pid, c in values.items())
                   for role, values in event_counts.items()},
        'results': {role: sorted((str(pid), event, sorted(counts.items()))
                                 for pid, by_event in values.items() for event, counts in by_event.items())
                    for role, values in result_counts.items()},
        'base_events': {role: sorted(counts.items()) for role, counts in base_events.items()},
        'row_stats': sorted((game_id, play_id, sorted(values.items()))
                            for (game_id, play_id), values in row_stats.items()),
    }
    digest = hashlib.sha256(json.dumps(serial, separators=(',', ':'), sort_keys=True).encode()).hexdigest()
    return {
        'model_version': MODEL_VERSION, 'cutoff_season': int(cutoff), 'source_seasons': list(seasons),
        'event_counts': event_counts, 'base_events': base_events,
        'result_counts': result_counts, 'base_results': base_results,
        'team_player_events': team_player_events, 'row_stats': row_stats, 'sha256': digest,
        'source_counts': dict(source),
        'player_units': units,
        'transferred_player_units': {
            role: sum(1 for player in event_counts[role]
                      if len({team for team, pid in team_player_events[role] if pid == player}) > 1)
            for role in EVENTS
        },
    }


def load(db, cutoff_season):
    """Fit player outcome profiles on regular seasons before cutoff_season, never its season or later."""
    cutoff = int(cutoff_season)
    seasons = list(range(FIRST_SEASON, cutoff))
    if not seasons:
        raise ValueError(f'player outcome model needs data from {FIRST_SEASON} or later before cutoff {cutoff}')
    marks = ','.join('?' for _ in seasons)
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        duplicate_positions = con.execute(
            "SELECT nfl_gsis_id FROM players WHERE lower(league)='nfl' AND nfl_gsis_id IS NOT NULL "
            "GROUP BY nfl_gsis_id HAVING COUNT(DISTINCT COALESCE(position,'')) > 1 LIMIT 1").fetchone()
        if duplicate_positions:
            raise ValueError(f'conflicting NFL positions for GSIS id {duplicate_positions[0]}')
        rows = [dict(zip(('season', 'posteam', 'passer_player_id', 'passer_position', 'rusher_player_id', 'receiver_player_id',
                          'qb_dropback', 'qb_scramble', 'pass_attempt', 'rush_attempt', 'complete_pass', 'sack',
                          'interception', 'fumble_lost', 'yards_gained', 'passing_yards', 'receiving_yards',
                          'rushing_yards', 'pass_touchdown', 'touchdown', 'rush_touchdown', 'game_id', 'play_id'), row))
                for row in con.execute(
                    f"SELECT p.season,p.posteam,p.passer_player_id,q.position,p.rusher_player_id,p.receiver_player_id,"
                    f"p.qb_dropback,p.qb_scramble,"
                    f"pass_attempt,rush_attempt,complete_pass,sack,interception,fumble_lost,yards_gained,passing_yards,"
                    f"receiving_yards,rushing_yards,pass_touchdown,touchdown,rush_touchdown,game_id,play_id "
                    f"FROM nfl_pbp p LEFT JOIN (SELECT nfl_gsis_id,MIN(position) AS position FROM players "
                    f"WHERE lower(league)='nfl' GROUP BY nfl_gsis_id) q ON q.nfl_gsis_id=p.passer_player_id "
                    f"WHERE p.season IN ({marks}) AND p.week BETWEEN 1 AND 18 "
                    f"ORDER BY p.game_id,p.play_id", seasons)]
    finally:
        con.close()
    return _fit_rows(rows, cutoff, seasons)


def _base_distribution(counts, categories=None):
    categories = tuple(categories or counts)
    total = sum(counts.values())
    if total <= 0:
        return {category: 1.0 / len(categories) for category in categories} if categories else {}
    return {category: counts.get(category, 0) / total for category in categories}


def event_distribution(table, role, player, strength=PRIOR_STRENGTH):
    """Posterior event probabilities for one player, shrunk to the fitted role distribution."""
    if role not in EVENTS or not table['base_events'][role]:
        return {}
    categories = EVENTS[role]
    base = _base_distribution(table['base_events'][role], categories)
    own = table['event_counts'][role].get(player, Counter())
    n = sum(own.values())
    denominator = n + strength
    return {event: (own.get(event, 0) + strength * base[event]) / denominator
            for event in categories}


def event_ratio(table, role, player, event):
    if player is None or event not in EVENTS.get(role, ()):
        return 1.0
    base = _base_distribution(table['base_events'][role], EVENTS[role])
    if not base or base.get(event, 0) <= 0:
        return 1.0
    probability = event_distribution(table, role, player).get(event, base[event])
    return min(MAX_RATIO, max(MIN_RATIO, probability / base[event]))


def _result_ratio(table, role, player, event, label):
    if player is None:
        return 1.0
    base_counts = table['base_results'][role].get(event, Counter())
    if not base_counts:
        return 1.0
    base = _base_distribution(base_counts)
    if base.get(label, 0) <= 0:
        return 1.0
    own = table['result_counts'][role].get(player, {}).get(event, Counter())
    n = sum(own.values())
    probability = (own.get(label, 0) + PRIOR_STRENGTH * base[label]) / (n + PRIOR_STRENGTH)
    return min(MAX_RATIO, max(MIN_RATIO, probability / base[label]))


def _geometric_mean(ratios):
    ratios = [max(MIN_RATIO, min(MAX_RATIO, ratio)) for ratio in ratios if ratio > 0]
    return math.exp(sum(math.log(ratio) for ratio in ratios) / len(ratios)) if ratios else 1.0


def event_weight(table, event, participants, enabled_roles=None):
    """Likelihood-ratio adjustment for the selected participants' event probabilities."""
    ratios = []
    enabled = set(normalize_roles(enabled_roles))
    if 'qb' in enabled and event in QB_EVENTS:
        ratios.append(event_ratio(table, 'qb', _player_id(participants, 'passer'), event))
    if 'receiver' in enabled and event in RECEIVER_EVENTS:
        ratios.append(event_ratio(table, 'receiver', _player_id(participants, 'receiver'), event))
    if 'rusher' in enabled and event in RUSHER_EVENTS:
        ratios.append(event_ratio(table, 'rusher', _player_id(participants, 'rusher'), event))
    return _geometric_mean(ratios)


def row_weight(table, event, row, participants, state=None, enabled_roles=None):
    """Likelihood-ratio adjustment for participant-specific yards and touchdown outcomes."""
    enabled = set(normalize_roles(enabled_roles))
    roles = []
    if event == 'pass_complete':
        roles = [('qb', _player_id(participants, 'passer'), 'passing_yards'),
                 ('receiver', _player_id(participants, 'receiver'), 'receiving_yards')]
    elif event == 'sack':
        roles = [('qb', _player_id(participants, 'passer'), 'yards_gained')]
    elif event in ('run', 'fumble_lost'):
        roles = [('rusher', _player_id(participants, 'rusher'), 'rushing_yards')]
    ratios = []
    row_key = (row.get('game_id'), int(row['play_id'])) if row.get('play_id') is not None else None
    source_metrics = table.get('row_stats', {}).get(row_key) if row_key is not None else None
    for role, player, yard_field in roles:
        if role not in enabled:
            continue
        # The simulation transition is still based on yards_gained. Player distributions and emitted player lines use
        # nflverse's role-specific passing, receiving and rushing yard fields where those source values are present.
        yards = (source_metrics.get(yard_field) if source_metrics is not None
                 else row.get(yard_field, row.get('yards_gained')))
        if yards is None:
            continue
        transition_yards = row.get('yards_gained')
        if state is not None and event in ('run', 'pass_complete') and transition_yards is not None:
            touchdown = int(transition_yards) >= int(state['yl'])
        elif source_metrics is not None:
            td_field = 'pass_touchdown' if role == 'qb' else 'rush_touchdown' if role == 'rusher' else 'touchdown'
            touchdown = bool(source_metrics.get(td_field))
        else:
            touchdown = bool(row.get('touchdown'))
        label = f"{_yards_bin(yards, role, event)}|td={int(touchdown)}"
        ratios.append(_result_ratio(table, role, player, event, label))
    return _geometric_mean(ratios)


def support(table, role, player):
    return sum(table['event_counts'].get(role, {}).get(player, Counter()).values())


def manifest(table, git_commit, enabled_roles=None):
    return {
        'model_version': table['model_version'], 'source_seasons': table['source_seasons'],
        'cutoff_season': table['cutoff_season'], 'git_commit': git_commit,
        'source_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'source': 'nflverse nfl_pbp pass, rush, sack, completion and interception fields; participant keys are GSIS ids',
        'yardage_fields': {'game_state_transition': 'yards_gained', 'quarterback_completion': 'passing_yards',
                           'receiver_completion': 'receiving_yards', 'rusher_attempt': 'rushing_yards',
                           'quarterback_sack': 'yards_gained'},
        'yardage_fallback': 'a missing role-specific player yard field omits that result adjustment; emitted box-score yards use yards_gained when the source field is null',
        'source_sha256': table['sha256'], 'prior_strength_opportunities': PRIOR_STRENGTH,
        'enabled_roles': list(normalize_roles(enabled_roles)),
        'ratio_clip': [MIN_RATIO, MAX_RATIO], 'player_units': dict(table['player_units']),
        'transferred_player_units': dict(table['transferred_player_units']),
        'source_counts': dict(table['source_counts']),
        'transfer_rule': 'outcome observations are retained by stable player id; QB decision tendencies are separately keyed by team and QB',
        'conditioning': 'event type plus joint yards-bin and touchdown label; result sampled before state transition',
    }
