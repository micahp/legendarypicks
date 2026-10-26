"""The two-point decision for the E2 game: P(go for two | situation) after a touchdown.

The table is fit from the situation fixture (build_try_situation.py): one row per eligible regular-season try. Each level is
shrunk toward the level above it, and the top level toward the league rate:

    p = (two_point_attempts + K * parent_rate) / (eligible_tries + K)

The first candidate is margin_period_opening with K = 25. Its levels are the opening-drive flag, then the flag within the
period (first half, Q3, Q4 above or at or below 5:00), then the exact post-touchdown margin within both. Opening drives only
happen in the first half in this window, so a period cell with no opening-drive tries takes the flag's own rate, not the
league's. A cell with no tries takes its parent's rate exactly. Only try selection is modelled here; the conversion-success
sampler is the published one, unchanged.
"""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE.parents[1] / 'docs' / 'fixtures' / 'e2' / 'try_situation_2022_2025.csv'
CANDIDATE = 'margin_period_opening'
K = 25
LEVELS = {
    'constant': [],
    'margin_period': [('period',), ('margin', 'period')],
    'margin_period_opening': [('opening_drive',), ('opening_drive', 'period'), ('margin', 'opening_drive', 'period')],
    'margin_period_first_td': [('first_td',), ('first_td', 'period'), ('margin', 'first_td', 'period')],
    'margin_period_opening_first_td': [('opening_drive',), ('opening_drive', 'first_td'),
                                       ('opening_drive', 'first_td', 'period'),
                                       ('margin', 'opening_drive', 'first_td', 'period')],
}


def period_of(quarter, clock):
    """The cell period: first half, Q3, Q4 with more than five minutes left, Q4 with five minutes or less. Overtime is OT."""
    if quarter in (1, 2):
        return 'H1'
    if quarter == 3:
        return 'Q3'
    if quarter == 4:
        return 'Q4_gt5' if clock > 300 else 'Q4_le5'
    return 'OT'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_rows(path=FIXTURE):
    """The fixture rows, typed. Refuses a file whose SHA-256 is not the one its sidecar manifest records."""
    path = Path(path)
    manifest = json.loads(Path(str(path) + '.manifest.json').read_text())
    if sha256(path) != manifest['output']['sha256']:
        raise ValueError(f'{path} does not match its manifest')
    rows = []
    with path.open(newline='') as f:
        for r in csv.DictReader(f):
            rows.append({
                'season': int(r['season']), 'season_type': r['season_type'], 'game_id': r['game_id'],
                'play_id': int(r['play_id']), 'kind': r['kind'], 'two': int(r['kind'] == 'two_point'),
                'made': r['made'], 'qtr': int(r['qtr']), 'clock': int(r['quarter_seconds_remaining']),
                'period': r['period'], 'margin': int(r['margin']), 'opening_drive': int(r['opening_drive']),
                'first_td': int(r['first_td']), 'defensive_td': int(r['defensive_td']),
            })
    return rows, sha256(path)


class TryPolicy:
    """P(two-point try) from fitted counts. `structure` picks the hierarchy; `k` is the shrinkage strength."""

    def __init__(self, rows, structure=CANDIDATE, k=K, source_sha256=None):
        if structure not in LEVELS:
            raise ValueError(f'unknown structure {structure!r}')
        fit = [r for r in rows if r['season_type'] == 'REG']
        if not fit:
            raise ValueError('no regular-season tries to fit')
        self.structure, self.k = structure, k
        self.fit_rows = len(fit)
        self.league_rate = sum(r['two'] for r in fit) / len(fit)
        self.source_sha256 = source_sha256
        self.levels = LEVELS[structure]
        self.counts = [Counter() for _ in self.levels]
        self.totals = [Counter() for _ in self.levels]
        for r in fit:
            for level, fields in enumerate(self.levels):
                key = tuple(r[f] for f in fields)
                self.counts[level][key] += r['two']
                self.totals[level][key] += 1

    @classmethod
    def from_fixture(cls, structure=CANDIDATE, k=K, path=FIXTURE):
        rows, sha = load_rows(path)
        return cls(rows, structure=structure, k=k, source_sha256=sha)

    def p_two(self, margin, quarter, clock, opening_drive, first_td):
        """The shrunk probability of a two-point try. Inputs are the post-touchdown margin, the quarter and the seconds left in
        it, and the two possession flags. Returns a float in (0, 1)."""
        situation = {'margin': margin, 'period': period_of(quarter, clock), 'opening_drive': int(bool(opening_drive)),
                     'first_td': int(bool(first_td))}
        p = self.league_rate
        for level, fields in enumerate(self.levels):
            key = tuple(situation[f] for f in fields)
            p = (self.counts[level][key] + self.k * p) / (self.totals[level][key] + self.k)
        return p

    def describe(self):
        return {'structure': self.structure, 'k': self.k, 'fit_rows': self.fit_rows,
                'league_rate': round(self.league_rate, 6), 'source_sha256': self.source_sha256}
