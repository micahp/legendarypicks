"""The matched-cohort rules for the 2024 scoring comparison (research). See test_scoring_cohort.py for the rules, in words.

A game is in the cohort when one of its simulated seeds completed (regulation or overtime). Blocked seeds are excluded on the
simulated side, and the actual side is restricted to the same games. Possessions exclude clock terminals. Plays per possession count
run and pass events on both sides.
"""
from collections import Counter

COMPLETE = ('complete_regulation', 'complete_overtime')
CLOCK = ('halftime', 'end_of_regulation', 'end_of_overtime')
SCRIMMAGE = ('run', 'pass_complete', 'pass_incomplete', 'sack', 'interception', 'fumble_lost')


def cohort_games(lines):
    """Game ids with at least one completed simulated seed."""
    return {line['game_id'] for line in lines if line.get('status') in COMPLETE}


def complete_seeds(lines, cohort):
    """The completed seeds of the cohort games, in file order."""
    return [line for line in lines if line.get('game_id') in cohort and line.get('status') in COMPLETE]


def sim_terminal(terminal, points):
    """The simulated drive terminal on the same names as the actual side. A field-goal attempt is made when the drive scored three."""
    if terminal == 'field_goal_attempt':
        return 'field_goal' if points >= 3 else 'missed_field_goal'
    if terminal in CLOCK:
        return 'end_of_period'
    return terminal


def scrimmage_plays(drive):
    """Run and pass events in a simulated drive (kicks and clock events are not plays from scrimmage)."""
    return sum(1 for event in drive.get('events', []) if event in SCRIMMAGE)


def sim_team_games(seeds):
    """One row per simulated team-game: points, possessions, scrimmage plays per possession, and possession terminals."""
    out = []
    for line in seeds:
        for side in ('A', 'B'):
            drives = [d for d in line['drives'] if d['offense'] == side]
            possessions = [d for d in drives if d['terminal'] not in CLOCK]
            out.append({'game_id': line['game_id'], 'seed': line['seed'], 'side': side, 'points': line['points'][side],
                        'possessions': len(possessions),
                        'plays_per_possession': sum(scrimmage_plays(d) for d in possessions) / max(1, len(possessions)),
                        'terminals': Counter(sim_terminal(d['terminal'], d.get('points', 0)) for d in possessions)})
    return out
