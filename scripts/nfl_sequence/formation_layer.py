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
import math
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
            'seasons': [int(s) for s in seasons], 'strength': PRIOR_STRENGTH,
            'personnel_first': personnel_first_priors(db, cutoff_season, participation)}


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


START = 'START'  # the previous personnel of a drive's first scrimmage play: there is none


def hurry(quarter, clock):
    """The last two minutes of the second or fourth quarter (`clock` is the quarter's seconds left)."""
    return int(quarter) in (2, 4) and int(clock) <= 120


def personnel_first_priors(db, cutoff_season, participation=None):
    """Counts for the personnel-first draw, from the seasons before the cutoff. Personnel is fitted on the situation and the
    previous personnel in the same drive, not on the call. Formation is fitted on the personnel. The call is fitted on both.

    personnel: by (hurry, down, distance bucket, previous personnel), backed off to (hurry, previous personnel), then the
    league; the offense's own (down, distance bucket) shares give it a lift over the league's.
    formation: by (personnel, down, bucket), backed off to the personnel; the offense's own cell shrinks to that.
    call: dropback and run counts by (personnel, formation, down, bucket), backed off to (personnel, formation), then the
    league; the offense's own cell shrinks to that. Also by (down, bucket), the base the personnel shift is taken from.

    A play with an UNKNOWN label adds no count where that label is a key or the outcome. The play after it in the drive
    has an unknown previous personnel and adds no personnel count."""
    if cutoff_season <= PARTICIPATION_FIRST:
        raise ValueError('no participation data before the cutoff season')
    seasons = range(PARTICIPATION_FIRST, cutoff_season)
    if participation is None:
        participation = load_participation(db, seasons)
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        marks = ','.join('?' * len(seasons))
        rows = con.execute(
            f"SELECT game_id, play_id, posteam, drive, qtr, game_seconds_remaining, down, ydstogo, play_type FROM nfl_pbp "
            f"WHERE season IN ({marks}) AND week <= 18 AND down BETWEEN 1 AND 4 AND ydstogo IS NOT NULL "
            f"AND play_type IN ('run', 'pass') ORDER BY game_id, play_id", list(seasons)).fetchall()
    finally:
        con.close()
    tables = {name: defaultdict(Counter) for name in (
        'personnel_cells', 'personnel_previous', 'personnel_situation', 'personnel_team',
        'formation_cells', 'formation_league', 'formation_team',
        'call_cells', 'call_league', 'call_team', 'call_situation', 'call_situation_team')}
    personnel_league, call_overall = Counter(), Counter()
    previous_of = {}  # (game_id, posteam, drive): the personnel of that drive's last scrimmage play so far
    for game_id, play_id, posteam, drive, quarter, game_seconds, down, togo, play_type in rows:
        call = intent_of_play_type(play_type)
        formation, personnel = participation.get((game_id, int(play_id)), (UNKNOWN, UNKNOWN))
        drive_key = (game_id, posteam, drive)
        previous = previous_of.get(drive_key, START)
        previous_of[drive_key] = personnel
        down, bucket = int(down), e0.ydstogo_bucket(togo)
        rush = quarter in (2, 4) and hurry(quarter, (game_seconds or 0) - (1800 if quarter == 2 else 0))
        if personnel == UNKNOWN:
            continue
        if previous != UNKNOWN:
            tables['personnel_cells'][(rush, down, bucket, previous)][personnel] += 1
            tables['personnel_previous'][(rush, previous)][personnel] += 1
        tables['personnel_situation'][(down, bucket)][personnel] += 1
        personnel_league[personnel] += 1
        if posteam:
            tables['personnel_team'][(posteam, down, bucket)][personnel] += 1
        tables['call_situation'][(down, bucket)][call] += 1
        call_overall[call] += 1
        if posteam:
            tables['call_situation_team'][(posteam, down, bucket)][call] += 1
        if formation == UNKNOWN:
            continue
        tables['formation_cells'][(personnel, down, bucket)][formation] += 1
        tables['formation_league'][personnel][formation] += 1
        tables['call_cells'][(personnel, formation, down, bucket)][call] += 1
        tables['call_league'][(personnel, formation)][call] += 1
        if posteam:
            tables['formation_team'][(posteam, personnel, down, bucket)][formation] += 1
            tables['call_team'][(posteam, personnel, formation, down, bucket)][call] += 1
    out = {name: dict(table) for name, table in tables.items()}
    out.update(personnel_league=personnel_league, call_overall=call_overall, strength=PRIOR_STRENGTH,
               seasons=[int(s) for s in seasons])
    return out


def _shrink(counts, base, strength):
    """counts shrunk to the distribution `base` with `strength` pseudo-counts, over known labels only, renormalised."""
    counts = counts or Counter()
    n = sum(counts.values())
    labels = (set(base) | set(counts)) - {UNKNOWN}
    out = {label: (counts.get(label, 0) + strength * base.get(label, 0.0)) / (n + strength) for label in labels}
    out = {label: share for label, share in out.items() if share > 0}
    total = sum(out.values())
    return {label: share / total for label, share in out.items()}


def _dropback_rate(counts, base_rate, strength):
    counts = counts or Counter()
    return (counts.get('dropback', 0) + strength * base_rate) / (sum(counts.values()) + strength)


def _logit(p):
    return math.log(p / (1.0 - p))


def _personnel_first_table(priors_table):
    table = priors_table.get('personnel_first')
    if table is None:
        raise ValueError('the formation priors have no personnel-first tables; rebuild them or turn personnel first off')
    return table


def personnel_distribution(priors_table, state, previous, team=None):
    """P(personnel | hurry, down, distance bucket, previous personnel in the drive, offense). It does not see the call."""
    table = _personnel_first_table(priors_table)
    strength = table['strength']
    down, bucket = int(state['down']), e0.ydstogo_bucket(state['togo'])
    rush = hurry(state['quarter'], state['clock'])
    league = _shrink(table['personnel_league'], {}, 0.0)
    shares = _shrink(table['personnel_cells'].get((rush, down, bucket, previous)),
                     _shrink(table['personnel_previous'].get((rush, previous)), league, strength), strength)
    if team is not None and (team, down, bucket) in table['personnel_team']:
        situation = _shrink(table['personnel_situation'].get((down, bucket)), league, strength)
        own = _shrink(table['personnel_team'][(team, down, bucket)], situation, strength)
        shares = _shrink({label: share * own.get(label, 0.0) / situation[label] for label, share in shares.items()
                          if situation.get(label)}, {}, 0.0)
    return shares


def formation_distribution(priors_table, state, personnel, team=None):
    """P(formation | personnel, down, distance bucket, offense)."""
    table = _personnel_first_table(priors_table)
    strength = table['strength']
    down, bucket = int(state['down']), e0.ydstogo_bucket(state['togo'])
    formations = _shrink(table['formation_cells'].get((personnel, down, bucket)),
                         _shrink(table['formation_league'].get(personnel), {}, 0.0), strength)
    if team is not None:
        formations = _shrink(table['formation_team'].get((team, personnel, down, bucket)), formations, strength)
    if not formations:  # a personnel with no formation on record: the league's formations
        formations = _shrink(sum(table['formation_league'].values(), Counter()), {}, 0.0)
    return formations


def dropback_given(priors_table, p_dropback, state, personnel, formation, team=None):
    """The play-call model's p_dropback, shifted in log-odds by how much this personnel and formation move the dropback
    rate in the cell: logit P(dropback | personnel, formation, cell) - logit P(dropback | cell), each for the offense,
    shrunk to the league. A certain call (p 0 or 1) is never changed."""
    if not 0.0 < p_dropback < 1.0:
        return p_dropback
    table = _personnel_first_table(priors_table)
    strength = table['strength']
    down, bucket = int(state['down']), e0.ydstogo_bucket(state['togo'])
    overall = _dropback_rate(table['call_overall'], 0.5, 0.0)
    base = _dropback_rate(table['call_situation'].get((down, bucket)), overall, strength)
    given = _dropback_rate(table['call_cells'].get((personnel, formation, down, bucket)),
                           _dropback_rate(table['call_league'].get((personnel, formation)), overall, strength), strength)
    if team is not None:
        base = _dropback_rate(table['call_situation_team'].get((team, down, bucket)), base, strength)
        given = _dropback_rate(table['call_team'].get((team, personnel, formation, down, bucket)), given, strength)
    return 1.0 / (1.0 + math.exp(-(_logit(p_dropback) + _logit(given) - _logit(base))))


def personnel_first(priors_table, p_dropback, state, previous, seed_text, team=None):
    """Personnel, then formation, then the call. Returns (personnel, formation, p_dropback given them).

    The personnel is drawn from the situation and the previous personnel in the drive (START on a drive's first play),
    with the offense's own lift. It does not see the call. The formation is drawn given the personnel. The call
    probability is dropback_given()."""
    rng = random.Random(int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], 'big'))
    personnel = _draw(rng, personnel_distribution(priors_table, state, previous, team))
    formation = _draw(rng, formation_distribution(priors_table, state, personnel, team))
    return personnel, formation, dropback_given(priors_table, p_dropback, state, personnel, formation, team)


def _draw(rng, probs):
    labels = sorted(label for label in probs if probs[label] > 0)
    return rng.choices(labels, weights=[probs[label] for label in labels], k=1)[0]


def attach(rows, participation):
    """Set row['formation'] and row['personnel'] on each play row from the participation join (UNKNOWN when unmatched)."""
    for row in rows:
        formation, personnel = participation.get((row['game_id'], int(row['play_id'])), (UNKNOWN, UNKNOWN))
        row['formation'], row['personnel'] = formation, personnel
    return rows
