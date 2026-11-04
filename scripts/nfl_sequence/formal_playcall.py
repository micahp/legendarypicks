"""Formal play classes: the offense's and defense's call as a formation, personnel, play type and concept (SLC v2, research).

The playbook files and the nflverse participation release record the same calls. A formal offensive play is:

    formation | personnel | play type | concept

- formation: SHOTGUN, UNDER CENTER or PISTOL. A blank formation is UNKNOWN and is kept, never filled.
- personnel: the offense's count of RB (with FB), TE and WR written as three digits, the playbook's convention (11 personnel
  is '113'). A line larger than five adds -OL6 or -OL7, so a six-lineman formation is kept as '112-OL6' and not dropped. A
  formation that lists a non-offensive position is INVALID and keeps its reason.
- play type: run or pass, from the play-by-play.
- concept: for a run, the gap (guard, tackle, end); for a pass, the depth (short, deep) and the route from the participation
  release. A pass with no route is UNKNOWN.

A formal defensive call is the defensive personnel (DL, LB and DB counts), the coverage type, the man or zone type and the
number of pass rushers.

Nothing here is estimated. The classes are read off the published records, and the classes of the published 2025 playbook
files are reproduced exactly (see test_formal_playcall.py). Cutoff rules belong to the caller: a table is fitted only from the
seasons the caller passes in.
"""
from collections import Counter

UNKNOWN = 'UNKNOWN'
INVALID = 'INVALID'
SPECIAL = 'SPECIAL'
SPECIAL_LABELS = {'P', 'K', 'LS'}
FORMATIONS = ('SHOTGUN', 'UNDER CENTER', 'PISTOL')
OL_LABELS = {'C', 'G', 'T', 'OL', 'OT', 'OG'}
RB_LABELS = {'RB', 'HB'}
DL_LABELS = {'DE', 'DT', 'NT', 'DL'}
LB_LABELS = {'LB', 'ILB', 'OLB', 'MLB'}
DB_LABELS = {'CB', 'S', 'SS', 'FS', 'DB'}
OFFENSE_GROUPS = ('QB', 'RB', 'FB', 'TE', 'WR', 'OL')
OFFENSE_SIZE = 11


def _parse(text):
    """'3 G, 1 QB, 2 WR' -> Counter({'G': 3, 'QB': 1, 'WR': 2}). Blank text is None (no personnel recorded)."""
    if not text or not text.strip():
        return None
    counts = Counter()
    for part in text.split(','):
        bits = part.strip().split(' ', 1)
        if len(bits) != 2 or not bits[0].isdigit():
            raise ValueError(f'unreadable personnel text: {text!r}')
        counts[bits[1].strip()] += int(bits[0])
    return counts


def formation_key(text):
    text = (text or '').strip().upper()
    return text if text in FORMATIONS else UNKNOWN


def offense_personnel(text):
    """Counts by offensive group, plus the list of labels that are not offensive positions."""
    raw = _parse(text)
    if raw is None:
        return None, []
    groups = Counter()
    other = []
    for label, n in raw.items():
        if label == 'QB':
            groups['QB'] += n
        elif label in RB_LABELS:
            groups['RB'] += n
        elif label == 'FB':
            groups['FB'] += n
        elif label == 'TE':
            groups['TE'] += n
        elif label == 'WR':
            groups['WR'] += n
        elif label in OL_LABELS:
            groups['OL'] += n
        else:
            other.append(label)
    return groups, other


def personnel_is_implicit(text):
    """True when the text leaves out the QB or the offensive line count, which the 2022 format does. The 2022 format names
    only the skill players, so one QB and five linemen are implied. Such a row is reconstructed, and the caller says so."""
    groups, _other = offense_personnel(text)
    return groups is not None and (groups['QB'] == 0 or groups['OL'] == 0)


def offense_personnel_code(text, implicit_qb_and_ol=False):
    """'113', '122' and so on, with '-OL6' or '-OL7' for a larger line. A punt-team or field-goal personnel (a punter, kicker or
    long snapper on the field) is SPECIAL, a real play such as a fake punt, and is not dropped. INVALID, with the reason, when
    the text names a defensive position or does not total eleven players. UNKNOWN when no personnel is recorded.

    implicit_qb_and_ol is for the 2022 format only: a missing QB count means one QB, and a missing OL count means five."""
    groups, other = offense_personnel(text)
    if groups is None:
        return UNKNOWN
    special = sorted(label for label in other if label in SPECIAL_LABELS)
    if special:
        return f'{SPECIAL}:{"/".join(special)}'
    if other:
        return f'{INVALID}:{"/".join(sorted(other))}'
    if implicit_qb_and_ol:
        if groups['QB'] == 0:
            groups['QB'] = 1
        if groups['OL'] == 0:
            groups['OL'] = 5
    total = sum(groups.values())
    if total != OFFENSE_SIZE:
        return f'{INVALID}:size{total}'
    code = f'{groups["RB"] + groups["FB"]}{groups["TE"]}{groups["WR"]}'
    if groups['OL'] != 5:
        code += f'-OL{groups["OL"]}'
    return code


def defense_personnel(text):
    """Counts of DL, LB and DB, plus labels that are not defensive positions (a kicker, punter or snapper, say)."""
    raw = _parse(text)
    if raw is None:
        return None, []
    groups = Counter()
    other = []
    for label, n in raw.items():
        if label in DL_LABELS:
            groups['DL'] += n
        elif label in LB_LABELS:
            groups['LB'] += n
        elif label in DB_LABELS:
            groups['DB'] += n
        else:
            other.append(label)
    return groups, other


def defense_personnel_code(text):
    """'DL4-LB2-DB5' style code (the nickel is DL4-LB2-DB5, the base is DL4-LB3-DB4)."""
    groups, other = defense_personnel(text)
    if groups is None:
        return UNKNOWN
    if other:
        return f'{INVALID}:{"/".join(sorted(other))}'
    return f'DL{groups["DL"]}-LB{groups["LB"]}-DB{groups["DB"]}'


def concept(play_type, run_gap, pass_length, route):
    """The play's concept. A run is named by its gap; a pass by its depth and route. A blank field is UNKNOWN."""
    if play_type == 'run':
        return f'run|{run_gap or UNKNOWN}'
    if play_type == 'pass':
        return f'pass|{pass_length or UNKNOWN}|{route or UNKNOWN}'
    return f'other|{play_type or UNKNOWN}'


def offense_class(formation_text, personnel_text, play_type, run_gap, pass_length, route):
    """The formal offensive play: (formation, personnel, play type, concept)."""
    return (formation_key(formation_text), offense_personnel_code(personnel_text), play_type or UNKNOWN,
            concept(play_type, run_gap, pass_length, route))


def defense_class(defense_personnel_text, coverage_type, man_zone_type, pass_rushers):
    """The formal defensive call: (personnel, coverage, man or zone, pass rushers)."""
    return (defense_personnel_code(defense_personnel_text), coverage_type or UNKNOWN, man_zone_type or UNKNOWN,
            str(pass_rushers) if pass_rushers not in (None, '') else UNKNOWN)


def is_valid(offense_code):
    return not offense_code.startswith(INVALID) and not offense_code.startswith(UNKNOWN)


def load_season(raw_dir, season, team=None):
    """Regular-season offensive plays of one season, joined to the participation release on (game_id, play_id).

    Each row carries the play-by-play fields and the participation fields. A play with no participation row is kept with
    blank participation fields, so the caller can count it. The team filter, when given, is the offense."""
    import csv
    import gzip
    from pathlib import Path
    raw = Path(raw_dir)
    part = {}
    with (raw / f'pbp_participation_{season}.csv').open(encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            part[(row['nflverse_game_id'], int(float(row['play_id'])))] = row
    out = []
    with gzip.open(raw / f'pbp_{season}.csv.gz', 'rt', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            if row['season_type'] != 'REG' or not row['posteam'] or not row['play_id']:
                continue
            if team is not None and row['posteam'] != team:
                continue
            key = (row['game_id'], int(float(row['play_id'])))
            p = part.get(key)
            personnel = p['offense_personnel'] if p else ''
            out.append({
                'season': season, 'game_id': row['game_id'], 'play_id': key[1], 'posteam': row['posteam'],
                'defteam': row['defteam'], 'week': int(row['week']), 'qtr': row['qtr'], 'down': row['down'],
                'ydstogo': row['ydstogo'], 'yardline_100': row['yardline_100'],
                'half_seconds_remaining': row['half_seconds_remaining'],
                'quarter_seconds_remaining': row['quarter_seconds_remaining'],
                'score_differential': row['score_differential'], 'play_type': row['play_type'],
                'run_gap': row['run_gap'], 'run_location': row['run_location'], 'pass_length': row['pass_length'],
                'pass_location': row['pass_location'], 'shotgun': row['shotgun'],
                'formation': p['offense_formation'] if p else '', 'personnel': personnel,
                'personnel_code': offense_personnel_code(personnel, implicit_qb_and_ol=(season == 2022)),
                'personnel_reconstructed': season == 2022 and personnel_is_implicit(personnel),
                'route': p['route'] if p else '', 'defense_personnel': p['defense_personnel'] if p else '',
                'coverage': p['defense_coverage_type'] if p else '', 'man_zone': p['defense_man_zone_type'] if p else '',
                'pass_rushers': p['number_of_pass_rushers'] if p else '', 'has_participation': p is not None,
            })
    return out
