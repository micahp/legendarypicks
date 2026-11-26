"""Game-clock transitions from the pinned snap clock table (build_snap_clock.py).

A run or pass uses the clock as follows. The live ball is drawn from the real snap-to-whistle times for that kind
of play. The clock rules then decide whether the clock runs after the whistle. It stops after an incompletion, after a
timeout, and after an out-of-bounds play in the last 2:00 of Q2 or the last 5:00 of Q4. If the clock runs, the offense
first decides its tempo (no-huddle or huddle) from the window and the score. Then the dead-ball game-clock seconds are
drawn for that tempo. After a possession change, the game clock starts on the next snap, so no dead-ball runoff is
charged. Play-clock and wall-clock time to the next snap are separate.
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
        data = json.loads(raw)
        if data.get('schema') != 'lp-e2-snap-clock-3':
            raise ValueError(f'snap clock table {path} has unsupported schema {data.get("schema")!r}')
        if not data.get('possession_change_no_huddle'):
            raise ValueError(f'snap clock table {path} lacks possession-change timing')
        semantics = data.get('timing_semantics', {})
        if (semantics.get('dead_interval_max_seconds') != 40
                or semantics.get('possession_change_dead_seconds') != 0
                or semantics.get('wall_time_to_next_snap') != 'not modeled'
                or semantics.get('play_clock') != 'not modeled'):
            raise ValueError(f'snap clock table {path} lacks separated timing semantics')
        for key, histogram in data.get('dead_seconds', {}).items():
            if any(not 0 <= float(seconds) <= 40 for seconds in histogram):
                raise ValueError(f'snap clock table {path} has illegal same-possession dead interval in {key}')
        return cls(data, sha)

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

    def possession_change_no_huddle_p(self, win, score):
        cells = self.data.get('possession_change_no_huddle', {})
        keys = ([f'{win}|{score}'], [k for k in cells if k.startswith(f'{win}|{_side(score)}')],
                [k for k in cells if k.startswith(f'{win}|')])
        for level, group in zip(('cell', 'score_side', 'window'), keys):
            snaps = sum(cells[k]['snaps'] for k in group if k in cells)
            if snaps >= MIN_TEMPO:
                return sum(cells[k]['no_huddle'] for k in group if k in cells) / snaps, level
        snaps = sum(cell['snaps'] for cell in cells.values())
        if snaps < MIN_TEMPO:
            raise ValueError('too few possession-change tempo observations')
        no_huddle = sum(cell['no_huddle'] for cell in cells.values())
        return no_huddle / snaps, 'all_possession_changes'

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

    def runoff_after_live(self, rng, *, quarter, qsr, event, live_seconds, out_of_bounds,
                          timeout_called, margin, possession_change=False):
        """Apply clock rules and next-snap timing to an already measured live-ball duration."""
        if not isinstance(live_seconds, (int, float)) or live_seconds < 0:
            raise ValueError('live-ball duration must be nonnegative')
        if event not in CLOCK_EVENTS and not possession_change:
            raise ValueError(f'the snap clock does not cover {event}')
        win, score = table.window(quarter, qsr), table.score_bucket(margin)
        record = {'live_seconds': live_seconds, 'window': win}
        if timeout_called:
            dead, record['stop'] = 0.0, 'timeout'
        elif possession_change:
            p_no_huddle, record['tempo_level'] = self.possession_change_no_huddle_p(win, score)
            tempo = 'no_huddle' if rng.random() < p_no_huddle else 'huddle'
            dead, record['dead_level'] = 0.0, 'clock_starts_on_next_snap'
            record['tempo'] = tempo
            record['stop'] = 'clock_starts_on_next_snap'
        elif event == 'pass_incomplete':
            dead, record['stop'] = 0.0, 'incomplete_pass'
        elif out_of_bounds and win != 'other':
            dead, record['stop'] = 0.0, 'out_of_bounds_late'
        elif out_of_bounds:
            dead, record['stop'] = _draw(rng, self.data['oob_ready_dead_seconds']['other']), 'out_of_bounds_ready'
        else:
            p_no_huddle = self.no_huddle_p(win, score)
            tempo = 'no_huddle' if rng.random() < p_no_huddle else 'huddle'
            dead, record['dead_level'] = self.dead(rng, win, score, tempo)
            record['tempo'] = tempo
        if quarter in (2, 4) and qsr > 120:
            if qsr - live_seconds <= 120:
                dead, record['two_minute_warning'] = 0.0, 'after_the_down'
            elif qsr - live_seconds - dead < 120:
                dead, record['two_minute_warning'] = qsr - live_seconds - 120, 'clock_stopped_at_2:00'
        record['dead_seconds'] = dead
        record['game_clock_live_seconds'] = live_seconds
        record['game_clock_dead_seconds'] = dead
        record['game_clock_runoff_seconds'] = int(round(live_seconds + dead))
        record['wall_time_to_next_snap'] = None
        record['play_clock_seconds'] = None
        return record['game_clock_runoff_seconds'], record

    def runoff(self, rng, *, quarter, qsr, event, out_of_bounds, timeout_called, margin):
        """(runoff seconds, record) for one run or pass whose offense keeps the ball in the same quarter."""
        if event not in CLOCK_EVENTS:
            raise ValueError(f'the snap clock covers {CLOCK_EVENTS}, not {event}')
        live = self.live(rng, event)
        return self.runoff_after_live(rng, quarter=quarter, qsr=qsr, event=event,
            live_seconds=live, out_of_bounds=out_of_bounds, timeout_called=timeout_called,
            margin=margin)
