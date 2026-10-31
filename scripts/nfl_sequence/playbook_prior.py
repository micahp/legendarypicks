"""The team playbook files as a pre-event input (research, off by default).

The playbook files (Gridiron Physics research build) record each team's observed plays with down, distance, field position and the
pass and run concepts. From the season before the cutoff, this module builds the same situational prior the decision layer builds
from the database, for three categories: pass depth (D), pass location (E) and run gap (C). The decision layer's draw uses it in place
of its own prior for those categories, where the playbook has a prior for the situation. Off by default: the playbook files and the
decision labels describe the same plays (playbook_crosscheck.py agrees on all 96 team-category pairs), so this is a question of
which source is used, and it is for review.
"""
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import decision_layer as dl
import nfl_team_codes
from playbook_crosscheck import PLAYBOOKS

BOOK_CATS = ('D', 'E', 'C')


def rows_of(playbook, season):
    """Labelled rows from one team-season playbook: pass depth and location on passes, run gap on runs."""
    team = nfl_team_codes.to_pbp_team_code(playbook['team_id'])
    out = []
    for play in playbook['offense']['observed_plays']:
        a = play['attributes']
        if not (a.get('down') and a.get('ydstogo') and a.get('yardline_100')):
            continue
        labels = {}
        if a.get('play_type') == 'pass':
            if a.get('pass_length') in ('short', 'deep'):
                labels['D'] = a['pass_length']
            if a.get('pass_location') in ('left', 'middle', 'right'):
                labels['E'] = a['pass_location']
        elif a.get('play_type') == 'run' and a.get('run_gap') in ('guard', 'tackle', 'end'):
            labels['C'] = a['run_gap']
        if not labels:
            continue
        cell = dl.cell_of(int(a['down']), int(a['ydstogo']), int(float(a['yardline_100'])))
        out.append({'season': int(season), 'team': team, 'cell': cell, 'labels': labels})
    return out


def load(cutoff, playbook_dir=PLAYBOOKS):
    """The playbook prior from the season before the cutoff, in the decision layer's table format. Fails loudly with no files."""
    season = int(cutoff) - 1
    paths = sorted(glob.glob(f'{playbook_dir}/*-{season}.json'))
    if not paths:
        raise ValueError(f'no playbook files for {season} in {playbook_dir}: the playbook input needs the season before the cutoff')
    rows = []
    for path in paths:
        rows.extend(rows_of(json.load(open(path)), season))
    return dl.fit(rows, prior_season=season)
