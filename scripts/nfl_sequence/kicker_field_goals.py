"""Field goals by the team's kicker: a research flag (amendment 6), off by default.

With the flag on (it needs the long_field_goal_feasibility blocker fix):
- Distance is the snap spot plus 18 and the ceiling is 76 yards, the longest attempt on record
  (field_goal_feasibility.RECORD_RULE). There is no 60-yard ordinary cutoff.
- Whether to kick, and a field goal against a punt, come from the situation cell's rows weighted by how near their yard line
  is to the snap spot (a normal kernel, KERNEL_YARDS), not the whole cell. On 2025 snaps with 2022 to 2024 pools this gives
  316, 159, 76, 14 and 2.5 expected attempts at 40-49, 50-54, 55-59, 60-64 and 65-69 yards against 325, 163, 91, 16 and 7
  observed; the cell share with the 60-yard cutoff gives 194, 111, 110, 54 and 11.
- The make probability is the league distance curve plus the kicker's logit offset (KickerTable): the posterior mode of
  his earlier kicks against the league curve, normal prior sd 0.3, seasons weighted 0.5 ** age. On 2022 to 2025, week over
  week, it beats the league curve by 0.0015 log loss [0.0002, 0.0028] (docs/research/fg-kicker-2026-11-04).
- The kicker is the team's one active K on the published weekly roster for the game's week; his offset uses only seasons
  before the game's season. A kicker with no earlier kick gets the league curve (offset 0).
"""
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import field_goal_feasibility as fg_feasibility

SCHEMA = 'kicker-fg-v1'
RULE = fg_feasibility.RECORD_RULE
KERNEL_YARDS = 2.0


class KickerTable:
    def __init__(self, data, sha256):
        if data.get('schema') != SCHEMA:
            raise ValueError(f"kicker table schema is {data.get('schema')!r}, expected {SCHEMA!r}")
        self.sha256 = sha256
        self.fit_seasons = sorted(data['fit_seasons'])
        self.sigma, self.recency = data['sigma'], data['recency']
        self.kickers = data['kickers']  # gsis_id -> {'offset', 'attempts', 'career_long'}
        self.assignments = {(int(s), int(w), team): pid for s, w, team, pid in data['assignments']}

    @classmethod
    def load(cls, path, expected_sha256):
        actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if actual != expected_sha256:
            raise ValueError(f'kicker table {path} has sha256 {actual}, expected {expected_sha256}')
        return cls(json.loads(Path(path).read_text()), actual)

    def kicker(self, season, week, team):
        """The team's active kicker for the week. Refuses when the roster has none."""
        pid = self.assignments.get((int(season), int(week), team))
        if pid is None:
            raise ValueError(f'kicker table has no active kicker for {team} in {season} week {week}')
        return pid

    def offset(self, pid):
        """(logit offset, earlier attempts). A kicker with no earlier kick has the league curve."""
        info = self.kickers.get(pid)
        return (0.0, 0) if info is None else (float(info['offset']), int(info['attempts']))


def kernel_counts(entry, snap_yardline_100):
    """The cell's outcome counts with each historical row weighted by a normal kernel in yard line around the snap spot."""
    out = Counter()
    for key, samples in entry['by_key'].items():
        out[key] = sum(math.exp(-0.5 * ((float(s[1]['yardline_100']) - snap_yardline_100) / KERNEL_YARDS) ** 2)
                       for s in samples)
    return out


def distribution(model, kick_distance, offset, *, block_shrinkage=30.0, kernel_bandwidth=5.0):
    """measure_kick_outcomes.field_goal_distribution with the kicker's logit offset and the record ceiling in place of the
    model's observed maximum."""
    import measure_kick_outcomes as mk
    distance = float(kick_distance)
    ceiling = fg_feasibility.RULES[RULE][1]
    if distance > ceiling:
        raise ValueError(f'field-goal distance {distance:g} exceeds the record ceiling {ceiling}')
    base = mk.field_goal_distribution(dict(model, max_observed_attempt_yards=ceiling), distance,
                                      block_shrinkage=block_shrinkage, kernel_bandwidth=kernel_bandwidth)
    z = model['intercept'] + model['distance_slope_per_10_yards'] * (distance - model['distance_center_yards']) / 10.0
    p_make = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z + offset))))
    p_block = min(base['blocked'], 1.0 - p_make)
    out = dict(base, made=p_make, blocked=p_block, missed=1.0 - p_make - p_block, conditional_make_probability=p_make,
               source='league_distance_curve_plus_kicker_offset', fallback_level='kicker_logit_offset',
               kicker_logit_offset=offset)
    return out
