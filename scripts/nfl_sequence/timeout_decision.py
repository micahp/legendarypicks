"""Team timeout decision at the whistle (research flag, off by default).

After a play's result is applied, each team may call a timeout before the next snap. The chance is the historical rate
for the same situation in docs/fixtures/e2/timeout_decisions_2022_2025.csv (build_timeout_decisions.py): the period, the
quarter clock at the snap, whether the clock runs after the play, the team's score margin, its timeouts left and whether
it has the ball next. A key with too few team snaps backs off to a coarser key; every draw records the key it used.

A team with no timeouts left never calls one. The decision reads only the state at the whistle, never the sampled source
play, so the source play's own timeout (another game's coach) is not applied.
"""
import csv
import hashlib
import json
from pathlib import Path

import build_timeout_decisions as table

TABLE = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'timeout_decisions_2022_2025.csv'
MIN_SUPPORT = 40
# Coarser keys, in order: drop the score, then whether the clock runs, then the timeouts left.
BACKOFF = (
    ('full', table.KEY),
    ('no_score', ('period', 'clock', 'clock_state', 'timeouts_left', 'role')),
    ('no_score_clock_state', ('period', 'clock', 'timeouts_left', 'role')),
    ('period_clock_role', ('period', 'clock', 'role')),
)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class TimeoutModel:
    def __init__(self, cells, sha256):
        self.sha256 = sha256
        self.levels = {}
        for name, fields in BACKOFF:
            level = {}
            for key, (n, called) in cells.items():
                row = dict(zip(table.KEY, key))
                sub = tuple(row[f] for f in fields)
                acc = level.setdefault(sub, [0, 0])
                acc[0] += n
                acc[1] += called
            self.levels[name] = (fields, level)

    @classmethod
    def load(cls, path=TABLE):
        manifest = json.loads(Path(str(path) + '.manifest.json').read_text())
        sha = _sha256(path)
        if manifest['output']['sha256'] != sha:
            raise ValueError(f'timeout table {path} does not match its manifest (sha256 {sha})')
        cells = {}
        with open(path, newline='') as f:
            for r in csv.DictReader(f):
                cells[tuple(r[k] for k in table.KEY)] = (int(r['team_snaps']), int(r['timeouts_called']))
        return cls(cells, sha)

    def probability(self, key):
        """(p, level, support) for one team's key, a dict with the table's KEY fields."""
        for name, (fields, level) in self.levels.items():
            n, called = level.get(tuple(key[f] for f in fields), (0, 0))
            if n >= MIN_SUPPORT:
                return called / n, name, n
        raise ValueError(f'no timeout cell with at least {MIN_SUPPORT} team snaps for {key}')

    def decide(self, rng, *, quarter, snap_clock, clock_state, offense, defense, margin, timeouts_left):
        """Who calls a timeout at this whistle: 'offense', 'defense' or None, and the record of the draw.

        `margin` is the offense's score minus the defense's; `timeouts_left` maps 'offense'/'defense' to counts.
        One uniform draw decides, so at most one team calls a timeout here.
        """
        teams = {'offense': (offense, margin), 'defense': (defense, -margin)}
        record = {'model': 'timeout_decisions_2022_2025', 'table_sha256': self.sha256, 'teams': {}}
        bands = []
        for role, (team, team_margin) in teams.items():
            left = timeouts_left[role]
            if left <= 0:
                record['teams'][role] = {'team': team, 'timeouts_left': 0, 'p': 0.0, 'level': 'no_timeouts_left'}
                continue
            key = {'period': table.period(quarter), 'clock': table.clock_bucket(snap_clock), 'clock_state': clock_state,
                   'score': table.score_bucket(team_margin), 'timeouts_left': str(min(int(left), 3)), 'role': role}
            p, level, support = self.probability(key)
            record['teams'][role] = {'team': team, 'timeouts_left': left, 'key': key, 'p': round(p, 6),
                                     'level': level, 'support': support}
            bands.append((role, p))
        u = rng.random()
        caller, edge = None, 0.0
        for role, p in bands:
            edge += p
            if u < edge:
                caller = role
                break
        record['caller'] = caller
        return caller, record
