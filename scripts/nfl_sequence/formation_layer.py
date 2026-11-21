"""Pre-event formation and personnel decisions, and formation-conditioned outcome weights (SLC v1, research, not adopted).

The offense chooses a formation and a personnel grouping before the play, from the situation. This module gives that choice a
cutoff-safe prior: counts from the play-by-play and the participation release of seasons before the cutoff, by intent (dropback or
run) and by down and distance, shrunk to the league prior for the same intent. An unknown formation or personnel stays a labelled
UNKNOWN category. It is never filled in.

The outcome conditioning uses the same counts: the probability of each outcome type, given the formation, shrunk to the cell.

Coverage: participation is available for 2016 to 2025 and is joined on (game_id, play_id). About 7 percent of plays have no
participation row, and they are UNKNOWN.
"""
import hashlib
import random
import sqlite3
from collections import Counter, defaultdict

import e0_single_play as e0

PRIOR_STRENGTH = 25.0  # pseudo-plays of the league prior added to each situation; fixed before use, not tuned
FORMATIONS = ('SHOTGUN', 'UNDER CENTER', 'PISTOL')
UNKNOWN = 'UNKNOWN'
PARTICIPATION_FIRST = 2016


def personnel_code(text):
    """The offense personnel as RB and TE counts, for example '11' (1 RB, 1 TE, so 3 WR) or '12'. Unknown text is UNKNOWN."""
    if not text:
        return UNKNOWN
    counts = Counter()
    for part in text.split(','):
        number, _, position = part.strip().partition(' ')
        if not number.isdigit():
            return UNKNOWN
        counts[position] += int(number)
    return f"{counts.get('RB', 0)}{counts.get('TE', 0)}"


def load_participation(db, seasons):
    """{(game_id, play_id): (formation, personnel_code)} for the given seasons. Labels are kept as published."""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        seasons = sorted(int(s) for s in seasons)
        marks = ','.join('?' * len(seasons))
        out = {}
        for game_id, play_id, formation, personnel in con.execute(
                f"SELECT nflverse_game_id, play_id, offense_formation, offense_personnel FROM nfl_hist_participation "
                f"WHERE season IN ({marks})", seasons):
            if play_id is None:
                continue
            label = formation if formation in FORMATIONS else UNKNOWN
            out[(game_id, int(play_id))] = (label, personnel_code(personnel))
    finally:
        con.close()
    return out


def intent_of_play_type(play_type):
    if play_type == 'pass':
        return 'dropback'
    if play_type == 'run':
        return 'run'
    return None


def priors(db, cutoff_season):
    """The formation and personnel priors for seasons before the cutoff. Keys: (intent, down, distance bucket)."""
    if cutoff_season <= PARTICIPATION_FIRST:
        raise ValueError('no participation data before the cutoff season')
    seasons = range(PARTICIPATION_FIRST, cutoff_season)
    participation = load_participation(db, seasons)
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        marks = ','.join('?' * len(seasons))
        rows = con.execute(
            f"SELECT game_id, play_id, down, ydstogo, play_type, posteam FROM nfl_pbp WHERE season IN ({marks}) AND week <= 18 "
            f"AND down BETWEEN 1 AND 4 AND ydstogo IS NOT NULL", list(seasons)).fetchall()
    finally:
        con.close()
    cells = defaultdict(lambda: {'formation': Counter(), 'personnel': Counter()})
    league = defaultdict(lambda: {'formation': Counter(), 'personnel': Counter()})
    team_cells = defaultdict(lambda: {'formation': Counter(), 'personnel': Counter()})  # the offense's own tendencies
    for game_id, play_id, down, togo, play_type, posteam in rows:
        intent = intent_of_play_type(play_type)
        if intent is None:
            continue
        formation, personnel = participation.get((game_id, int(play_id)), (UNKNOWN, UNKNOWN))
        key = (intent, int(down), e0.ydstogo_bucket(togo))
        for table in (cells[key], league[intent]):
            table['formation'][formation] += 1
            table['personnel'][personnel] += 1
        if posteam:
            team_table = team_cells[(posteam,) + key]
            team_table['formation'][formation] += 1
            team_table['personnel'][personnel] += 1
    return {'cells': dict(cells), 'league': dict(league), 'team_cells': dict(team_cells),
            'seasons': [int(s) for s in seasons], 'strength': PRIOR_STRENGTH}


def distribution(priors_table, intent, down, togo, field, team=None):
    """The distribution over labels of `field` for this situation. With a team, the team's own tendencies in the situation,
    shrunk to the league-cell distribution with the same strength; a team with no history in the situation gets the league cell."""
    base = _cell_distribution(priors_table, intent, down, togo, field)
    if team is None:
        return base
    own = priors_table.get('team_cells', {}).get((team, intent, int(down), e0.ydstogo_bucket(togo)), {}).get(field, Counter())
    own_total = sum(own.values())
    if not own_total:
        return base
    strength = priors_table['strength']
    labels = set(base) | set(own)
    out = {label: (own[label] + strength * base.get(label, 0.0)) / (own_total + strength) for label in labels}
    total = sum(out.values())
    return {label: share / total for label, share in out.items()}


def _cell_distribution(priors_table, intent, down, togo, field):
    league = priors_table['league'][intent][field]
    league_total = sum(league.values())
    cell = priors_table['cells'].get((intent, int(down), e0.ydstogo_bucket(togo)), {}).get(field, Counter())
    cell_total = sum(cell.values())
    strength = priors_table['strength']
    labels = sorted(set(league) | set(cell))
    out = {}
    for label in labels:
        league_share = league[label] / league_total if league_total else 0.0
        out[label] = (cell[label] + strength * league_share) / (cell_total + strength)
    total = sum(out.values())
    return {label: share / total for label, share in out.items()}


def choose(priors_table, intent, down, togo, seed_text, team=None):
    """(formation, personnel) for this play, drawn before the outcome from a seeded stream.

    The decision is among known labels only: UNKNOWN is a data label (a play with no published formation), and no offense
    chooses it. The known-label shares are renormalised, so the decision is not diluted by missing data."""
    rng = random.Random(int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], 'big'))
    result = {}
    for field in ('formation', 'personnel'):
        shares = {label: share for label, share in distribution(priors_table, intent, down, togo, field, team).items()
                  if label != UNKNOWN and share > 0}
        labels = sorted(shares)
        total = sum(shares[label] for label in labels)
        result[field] = rng.choices(labels, weights=[shares[label] / total for label in labels], k=1)[0]
    return result['formation'], result['personnel']


CALLS = ('run', 'dropback')


def _known_shares(priors_table, call, down, togo, field, team):
    """The known labels' shares for one call, renormalised (the same rule as choose)."""
    shares = {label: share for label, share in distribution(priors_table, call, down, togo, field, team).items()
              if label != UNKNOWN and share > 0}
    total = sum(shares.values())
    return {label: share / total for label, share in shares.items()} if total else {}


def draft(priors_table, p_dropback, down, togo, seed_text, team=None):
    """Personnel first, then formation, then the call: the same joint law as choose() after the call.

    choose() draws formation and personnel from their own distributions given the call, so given the call they are
    independent: P(call) P(personnel | call) P(formation | call). This draws the personnel from its marginal over the call,
    the formation from its posterior given that personnel, and returns P(dropback | personnel, formation). The caller draws
    the call from that probability. Only the order of the draws changes. Returns (personnel, formation, p_dropback)."""
    weights = {'run': 1.0 - p_dropback, 'dropback': p_dropback}
    shares = {field: {call: _known_shares(priors_table, call, down, togo, field, team) for call in CALLS}
              for field in ('personnel', 'formation')}
    rng = random.Random(int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], 'big'))
    personnel = _draw(rng, _mixture(weights, shares['personnel']))
    call_given_personnel = {call: weights[call] * shares['personnel'][call].get(personnel, 0.0) for call in CALLS}
    total = sum(call_given_personnel.values())
    formation = _draw(rng, _mixture({call: call_given_personnel[call] / total for call in CALLS}, shares['formation']))
    joint = {call: weights[call] * shares['personnel'][call].get(personnel, 0.0) * shares['formation'][call].get(formation, 0.0)
             for call in CALLS}
    return personnel, formation, joint['dropback'] / sum(joint.values())


def _mixture(mass, shares_by_call):
    """sum over calls of mass[call] * shares[call][label], as a distribution over labels."""
    out = Counter()
    for call, weight in mass.items():
        for label, share in shares_by_call[call].items():
            out[label] += weight * share
    return out


def _draw(rng, probs):
    labels = sorted(label for label in probs if probs[label] > 0)
    return rng.choices(labels, weights=[probs[label] for label in labels], k=1)[0]


def attach(rows, participation):
    """Set row['formation'] and row['personnel'] on each play row from the participation join (UNKNOWN when unmatched)."""
    for row in rows:
        formation, personnel = participation.get((row['game_id'], int(row['play_id'])), (UNKNOWN, UNKNOWN))
        row['formation'], row['personnel'] = formation, personnel
    return rows
