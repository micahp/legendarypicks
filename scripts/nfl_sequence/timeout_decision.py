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


LATE_CLOCK = 120
MIN_RUNOFF_SUPPORT = 20


def team_timeout_keys(extras_path):
    """(game_id, play_id) of every team timeout row in the play-extras table."""
    keys = set()
    with open(extras_path, newline='') as f:
        for r in csv.DictReader(f):
            if r['timeout'] == '1' and r['timeout_team']:
                keys.add((r['game_id'], int(float(r['play_id']))))
    return keys


def rows_followed_by_timeout(rows, timeout_keys):
    """{(game_id, play_id): runoff} for each row whose next row in its game is a team timeout.

    nflverse stamps a timeout row with the clock of the snap before it, so that play's time sits between the timeout
    row and the next snap: the runoff is taken through any timeout rows to the next row in the same quarter. A row
    with no such next row in its quarter maps to None.
    """
    followed = {}
    for i, here in enumerate(rows[:-1]):
        nxt = rows[i + 1]
        if nxt['game_id'] != here['game_id'] or (nxt['game_id'], int(nxt['play_id'])) not in timeout_keys:
            continue
        j = i + 1
        while j < len(rows) and rows[j]['game_id'] == here['game_id'] and (rows[j]['game_id'], int(rows[j]['play_id'])) in timeout_keys:
            j += 1
        runoff = None
        if (j < len(rows) and rows[j]['game_id'] == here['game_id'] and rows[j]['qtr'] == here['qtr']
                and here['game_seconds_remaining'] is not None and rows[j]['game_seconds_remaining'] is not None):
            runoff = int(round(here['game_seconds_remaining'] - rows[j]['game_seconds_remaining']))
        followed[(here['game_id'], int(here['play_id']))] = runoff
    return followed


def _late(row):
    """Late in a half: the second or fourth quarter with two minutes or less. game_seconds_remaining counts the game."""
    seconds = row.get('game_seconds_remaining')
    return row.get('qtr') in (2, 4) and seconds is not None and seconds % 900 <= LATE_CLOCK


class RunoffSplit:
    """The sampled play's runoff, made to agree with the timeout decision.

    A source row followed by a timeout has a pool runoff of about zero (the timeout row repeats its snap clock); its
    runoff here is the time through the timeout to the next snap. A row followed by the next snap keeps its pool runoff.
    When the decision and the source row agree, the row's own runoff is used. When they differ, the runoff is drawn from
    rows of the same event and timeout status in the same cell, else league-wide by event and late clock.
    """

    def __init__(self, pool, followed):
        self.followed = followed
        self.by_cell, self.by_event = {}, {}
        for cell, samples in pool.items():
            for event, row, runoff, _spot in samples:
                status = (row['game_id'], int(row['play_id'])) in followed
                if status:
                    runoff = followed[(row['game_id'], int(row['play_id']))]
                    if runoff is None:
                        continue
                self.by_cell.setdefault((cell, event, status), []).append(runoff)
                self.by_event.setdefault((event, status, _late(row)), []).append(runoff)

    def follows(self, row):
        return (row['game_id'], int(row['play_id'])) in self.followed

    def runoff(self, rng, cell, event, row, runoff, called, late):
        """(runoff, source) for the play, given whether a timeout was called at its whistle."""
        if self.follows(row) == bool(called):
            if called:
                through = self.followed[(row['game_id'], int(row['play_id']))]
                if through is not None:
                    return through, 'source_row_through_timeout'
            else:
                return runoff, 'source_row'
        sample = self.by_cell.get((cell, event, bool(called)), [])
        if len(sample) >= MIN_RUNOFF_SUPPORT:
            return rng.choice(sample), 'cell_event_timeout_status'
        sample = self.by_event.get((event, bool(called), bool(late)), [])
        if len(sample) >= MIN_RUNOFF_SUPPORT:
            return rng.choice(sample), 'event_timeout_status_late'
        raise ValueError(f'no runoff with timeout status {bool(called)} for {event} (cell {cell}, late {late})')
