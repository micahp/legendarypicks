"""Snap-to-snap game clock from the pinned snap clock table (build_snap_clock.py).

A run or pass uses the clock as follows. The live ball is drawn from the real snap-to-whistle times for that kind
of play. The clock rules then decide whether the clock runs after the whistle. It stops after an incompletion, after a
timeout, and after an out-of-bounds play in the last 2:00 of Q2 or the last 5:00 of Q4. If the clock runs, the offense
first decides its tempo (no-huddle or huddle) from the window and the score. Then the dead-ball seconds are drawn for that
tempo. The two-minute warning stops the clock at 2:00 in Q2 and Q4.
"""
import hashlib
import json
from pathlib import Path

import build_snap_clock as table

PATH = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'snap_clock_2022_2025.json'
CLOCK_EVENTS = ('run', 'pass_complete', 'pass_incomplete', 'sack')
MIN_LIVE = 200
MIN_DEAD = 50
MIN_TEMPO = 100


def _draw(rng, histogram):
    values = [float(k) for k in histogram]
    return rng.choices(values, weights=list(histogram.values()))[0]


def _merge(histograms):
    out = {}
    for h in histograms:
        for k, n in h.items():
            out[k] = out.get(k, 0) + n
    return out


def _side(score):
    return score.split('_')[0]  # leading, trailing or tied


class SnapClock:
    def __init__(self, data, sha256):
        self.data, self.sha256 = data, sha256

    @classmethod
    def load(cls, path=PATH):
        raw = Path(path).read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        manifest = json.loads(Path(str(path) + '.manifest.json').read_text())
        if manifest['output_sha256'] != sha:
            raise ValueError(f'snap clock table {path} does not match its manifest')
        return cls(json.loads(raw), sha)

    def live(self, rng, kind):
        histogram = self.data['live_seconds'].get(kind, {})
        if sum(histogram.values()) < MIN_LIVE:
            raise ValueError(f'too few live-ball times for {kind}')
        return _draw(rng, histogram)

    def no_huddle_p(self, win, score):
        cells = self.data['no_huddle']
        for keys in ([f'{win}|{score}'], [k for k in cells if k.startswith(f'{win}|{_side(score)}')],
                     [k for k in cells if k.startswith(f'{win}|')]):
            snaps = sum(cells[k]['snaps'] for k in keys if k in cells)
            if snaps >= MIN_TEMPO:
                return sum(cells[k]['no_huddle'] for k in keys if k in cells) / snaps
        raise ValueError(f'too few tempo observations for {win} {score}')

    def dead(self, rng, win, score, tempo):
        cells = self.data['dead_seconds']
        for level, keys in (('cell', [f'{win}|{score}|{tempo}']),
                            ('score_side', [k for k in cells if k.startswith(f'{win}|{_side(score)}') and k.endswith(tempo)]),
                            ('window', [k for k in cells if k.startswith(f'{win}|') and k.endswith(f'|{tempo}')]),
                            ('other_window', [f'other|{score}|{tempo}'])):
            histogram = _merge(cells[k] for k in keys if k in cells)
            if sum(histogram.values()) >= MIN_DEAD:
                return _draw(rng, histogram), level
        raise ValueError(f'too few dead-ball times for {win} {score} {tempo}')

    def runoff(self, rng, *, quarter, qsr, event, out_of_bounds, timeout_called, margin):
        """(runoff seconds, record) for one run or pass whose offense keeps the ball in the same quarter."""
        if event not in CLOCK_EVENTS:
            raise ValueError(f'the snap clock covers {CLOCK_EVENTS}, not {event}')
        win, score = table.window(quarter, qsr), table.score_bucket(margin)
        live = self.live(rng, event)
        record = {'live_seconds': live, 'window': win}
        if event == 'pass_incomplete':
            dead, record['stop'] = 0.0, 'incomplete_pass'
        elif timeout_called:
            dead, record['stop'] = 0.0, 'timeout'
        elif out_of_bounds and win != 'other':
            dead, record['stop'] = 0.0, 'out_of_bounds_late'
        elif out_of_bounds:
            dead, record['stop'] = _draw(rng, self.data['oob_ready_dead_seconds']['other']), 'out_of_bounds_ready'
        else:
            tempo = 'no_huddle' if rng.random() < self.no_huddle_p(win, score) else 'huddle'
            dead, record['dead_level'] = self.dead(rng, win, score, tempo)
            record['tempo'] = tempo
        if quarter in (2, 4) and qsr > 120:
            if qsr - live <= 120:
                dead, record['two_minute_warning'] = 0.0, 'after_the_down'
            elif qsr - live - dead < 120:
                dead, record['two_minute_warning'] = qsr - live - 120, 'clock_stopped_at_2:00'
        record['dead_seconds'] = dead
        return int(round(live + dead)), record
