#!/usr/bin/env python3
"""Model D, the E3 boundary-aware, event-driven conditional clock. Research candidate; the E2 default is unchanged.

Per generated play, D decides the clock from the play's own outcome and the state at the snap. It never reads the next
snap, a known final play, or a quarter-ending marker row of the play being generated.

1. Clock-stop class (`stop_class`), from the generated play and its legal consequence: score, kick, turnover, incomplete
   pass, sack, out of bounds in the final two minutes of a half (a stop), otherwise the clock runs.
2. Quarter end: a draw against a hazard fitted on training quarter ends, keyed by event, stop class and the quarter
   clock at the snap. When it fires, the play consumes the remaining quarter time. That is a legal transition: the
   quarter ends at this play. It is not a clamp of an interval drawn independently.
3. Otherwise the runoff is drawn from the uncensored runoffs of plays with the same key, conditioned on not ending the
   quarter (draws at or above the remaining time are rejected). Quarter-ending plays are censored, so they are not
   runoff samples.
4. The two-minute warning stops the clock at 2:00 in the second and fourth quarters. This is applied as a mandatory stop,
   not sampled. Its timing is not checked against the rulebook text, which is not in the repository.

Disclosed, not modelled: timeouts (their stoppage time stays inside the observed runoffs the pool is drawn from),
penalty stoppages (penalty plays are excluded by E1), kneels (not in the E1 event vocabulary), spikes (an incomplete
pass), kickoffs (E2's kickoff runoff still clamps at zero).

Fitting reads observed plays only. Its quarter-end counts use the marker rows that observed plays were followed by;
the simulation never reads them.
"""
import csv
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import e1_drive as e1

QUARTER_LENGTH = e1.QUARTER_LENGTH  # 900
LATE_CLOCK = 120  # the two-minute mark
LATE_QUARTERS = (2, 4)
BOUNDARY_CLOCKS = (0, 900, 1800, 2700)  # quarter-end marker rows carry the game clock at a boundary
BUCKETS = (15, 30, 60, 120, 900)  # quarter clock at the snap, upper edges
MIN_KEY = 50  # the E1 floor; a thinner key falls back to one coarser key, and no further
MAX_TRIES = 1000
EXTRAS = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'play_extras_2022_2025.csv'


def qsr_bucket(clock):
    clock = max(1, clock)
    return next(b for b in BUCKETS if clock <= b)


def stop_class(event, oob, late, terminal):
    """The legal clock-stop class of a generated play. Uses only the play's own outcome and the state at the snap."""
    if terminal in ('touchdown', 'safety'):
        return 'score'
    if event in e1.KICK_EVENTS:
        return 'kick'
    if event in ('interception', 'fumble_lost'):
        return 'turnover'
    if event == 'pass_incomplete':
        return 'incomplete'
    if event == 'sack':
        return 'sack'
    if oob and late:
        return 'oob_late'
    return 'clock_runs'


def is_marker(row):
    return row['play_type'] is None and row['game_seconds_remaining'] in BOUNDARY_CLOCKS


def ends_quarter(seq, i):
    """True when the quarter ends after play i of `seq`: the quarter's marker is the next row, or follows one non-play row
    (a penalty or no-play row, which the E1 vocabulary does not generate). A real play in between means it does not."""
    row = seq[i]
    for j in (i + 1, i + 2):
        if j >= len(seq):
            return False
        nxt = seq[j]
        if nxt['game_id'] != row['game_id'] or nxt['qtr'] != row['qtr']:
            return False
        if is_marker(nxt):
            return True
        if nxt['play_type'] in e1.PLAY_TYPES:
            return False
    return False


def quarter_clock(row):
    return row['game_seconds_remaining'] - (4 - row['qtr']) * QUARTER_LENGTH


def load_window(db, season_from, season_to, week_from, week_to):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        rows = [dict(zip(e1.COLUMNS, r)) for r in con.execute(
            f"SELECT {', '.join(e1.COLUMNS)} FROM nfl_pbp WHERE season BETWEEN ? AND ? AND week BETWEEN ? AND ? "
            "ORDER BY game_id, play_id", (season_from, season_to, week_from, week_to))]
    finally:
        con.close()
    return rows


def load_flags(path=EXTRAS):
    """(game_id, play_id) -> (out_of_bounds, timeout) from the rebuilt play-extras table (read only)."""
    flags = {}
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            flags[(r['game_id'], int(float(r['play_id'])))] = (int(r['out_of_bounds']), int(r['timeout']))
    return flags


class Model:
    """Fitted pools and hazards. Build with `fit`."""

    def __init__(self, pool, pool_stop, pool_all, hazard, hazard_bucket, flags, counts):
        self.pool, self.pool_stop, self.pool_all = pool, pool_stop, pool_all
        self.hazard, self.hazard_bucket = hazard, hazard_bucket
        self.flags = flags
        self.fit_counts = counts

    def p_end(self, event, stop, bucket):
        """Quarter-end probability for a play with this stop class at this quarter clock. The event is not a key here:
        per-event cells were too thin, and the event reaches the hazard through its stop class."""
        ended, n = self.hazard.get((stop, bucket), (0, 0))
        if n >= MIN_KEY:
            return ended / n, 'stop and clock'
        ended, n = self.hazard_bucket.get(bucket, (0, 0))
        if n >= MIN_KEY:
            return ended / n, 'clock only'
        return None, f'thin hazard cell {(stop, bucket)}'

    def runoffs(self, event, stop, late):
        for key, table, source in (((event, stop, late), self.pool, 'event, stop and late'),
                                   ((stop, late), self.pool_stop, 'stop and late'),
                                   (late, self.pool_all, 'late only')):
            sample = table.get(key, [])
            if len(sample) >= MIN_KEY:
                return sample, source
        return None, f'thin runoff cell {(event, stop, late)}'

    def for_game(self, seed, paired_random_streams=None):
        return BoundaryClock(self, seed, paired_random_streams=paired_random_streams)


def fit(rows, flags):
    """Training counts from observed plays. Plays followed by a quarter-ending marker are the hazard's events, and
    they are excluded from the runoff pool because their runoff is censored at the boundary."""
    counts = Counter()
    pool, pool_stop, pool_all = defaultdict(list), defaultdict(list), defaultdict(list)
    hazard, hazard_bucket = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    by_game = defaultdict(list)
    for r in rows:
        by_game[r['game_id']].append(r)
    for seq in by_game.values():
        for i, row in enumerate(seq):
            if row['qtr'] not in (1, 2, 3, 4) or is_marker(row):
                continue
            nxt = seq[i + 1] if i + 1 < len(seq) else None
            if nxt is None:
                counts['no next row'] += 1
                continue
            ended = ends_quarter(seq, i)
            if nxt['qtr'] != row['qtr'] and not ended:
                counts['quarter change without a marker row (excluded)'] += 1
                continue
            hit = e1.classify(row, nxt, counts)
            if hit is None:
                continue
            event, runoff, _ = hit
            qsr = quarter_clock(row)
            oob = flags.get((row['game_id'], int(row['play_id'])), (0, 0))[0]
            late = row['qtr'] in LATE_QUARTERS and qsr <= LATE_CLOCK
            terminal = 'touchdown' if row['touchdown'] == 1 else None
            stop = stop_class(event, oob, late, terminal)
            bucket = qsr_bucket(qsr)
            for table, key in ((hazard, (stop, bucket)), (hazard_bucket, bucket)):
                table[key][1] += 1
                table[key][0] += int(ended)
            if not ended:
                pool[(event, stop, late)].append(runoff)
                pool_stop[(stop, late)].append(runoff)
                pool_all[late].append(runoff)
            counts[f'plays fitted: {event}'] += 1
            counts[f'quarter-ending plays: {event}'] += int(ended)
    return Model(dict(pool), dict(pool_stop), dict(pool_all), {k: tuple(v) for k, v in hazard.items()},
                 {k: tuple(v) for k, v in hazard_bucket.items()}, flags, counts)


class BoundaryClock:
    """One game's draws. Its own random stream, so generated outcomes match the control under the same seed."""

    def __init__(self, model, seed, paired_random_streams=None):
        self.model = model
        self.rng = random.Random(seed * 7919 + 17)
        self.paired_random_streams = paired_random_streams
        self.counts = Counter()
        self.log = []

    def draw(self, row, event, terminal, quarter, qsr, *, drive_index=None, play_index=None):
        """(runoff, ends_quarter, refusal) for a generated play at quarter clock `qsr`.

        `refusal` is None, or the reason a key was thin; then runoff is None and the caller blocks the game.
        """
        late = quarter in LATE_QUARTERS and qsr <= LATE_CLOCK
        oob = self.model.flags.get((row['game_id'], int(row['play_id'])), (0, 0))[0]
        stop = stop_class(event, oob, late, terminal)
        bucket = qsr_bucket(qsr)
        p_end, source = self.model.p_end(event, stop, bucket)
        if p_end is None:
            return None, False, source
        self.counts[f'hazard key from {source}'] += 1
        if self.paired_random_streams is None:
            hazard_rng = runoff_rng = self.rng
        else:
            if type(drive_index) is not int or type(play_index) is not int:
                raise ValueError('paired clock draws require drive and game-wide play indices')
            hazard_rng = self.paired_random_streams.rng('clock_quarter_end_hazard', drive_index, play_index)
            runoff_rng = self.paired_random_streams.rng('clock_runoff', drive_index, play_index)
        if hazard_rng.random() < p_end:
            return self._record(event, stop, quarter, qsr, qsr, True, late)
        sample, source = self.model.runoffs(event, stop, late)
        if sample is None:
            return None, False, source
        self.counts[f'runoff key from {source}'] += 1
        for _ in range(MAX_TRIES):
            runoff = runoff_rng.choice(sample)
            if runoff < qsr:
                break
        else:
            self.counts['runoff pool has nothing below the remaining time: quarter ends'] += 1
            return self._record(event, stop, quarter, qsr, qsr, True, late)
        if quarter in LATE_QUARTERS and qsr > LATE_CLOCK and qsr - runoff < LATE_CLOCK:
            runoff = qsr - LATE_CLOCK
            self.counts['two-minute stop: runoff cut at 2:00'] += 1
        return self._record(event, stop, quarter, qsr, runoff, False, late)

    def _record(self, event, stop, quarter, qsr, runoff, ended, late):
        self.log.append({'event': event, 'stop': stop, 'quarter': quarter, 'qsr': qsr, 'runoff': runoff,
                         'ended': ended, 'late': late})
        return runoff, ended, None
