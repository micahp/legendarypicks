"""Current-state field-goal distance and the pinned historical eligibility ceiling."""

SNAP_TO_KICK_OFFSET_YARDS = 17  # holder placement (7) plus the 10-yard end zone
MAX_HISTORICAL_KICK_DISTANCE_YARDS = 70
REFERENCE_FILE = 'docs/fixtures/e2/kick_results_2022_2025.csv'
REFERENCE_SHA256 = '193f2d2390c36a968b42da1e851eba9c0b0c79bb2822fbcaff4aa3d6d0ce0a93'
# Research rule (kicker_field_goals, amendment 6): the published kick_distance is the snap spot plus 18 on 87% of
# 2022-2025 attempts, and the ceiling is the longest attempt on record, 76 yards (2008_04_SD_OAK, play-by-play).
RECORD_RULE = 'record_76_offset_18'
RULES = {None: (SNAP_TO_KICK_OFFSET_YARDS, MAX_HISTORICAL_KICK_DISTANCE_YARDS), RECORD_RULE: (18, 76)}


def _historical_snap_bucket(snap_yardline_100):
    for upper, label in ((10, '1-9'), (20, '10-19'), (30, '20-29'),
                         (40, '30-39'), (50, '40-49')):
        if snap_yardline_100 < upper:
            return label
    return '50+'


def _bucket_kick_distance_range(bucket, offset=SNAP_TO_KICK_OFFSET_YARDS):
    if bucket == '50+':
        return f'{50 + offset}+'
    low, high = (int(part) for part in bucket.split('-'))
    return f'{low + offset}-{high + offset}'


def evaluate(snap_yardline_100, rule=None):
    """Compute a kick's distance from the current snap spot, then apply the ceiling. rule None is the pinned rule (17 and
    70); RECORD_RULE is the research rule, and the result then names it."""
    if rule not in RULES:
        raise ValueError(f'unknown field-goal feasibility rule {rule!r}')
    if type(snap_yardline_100) is not int or not 1 <= snap_yardline_100 <= 99:
        raise ValueError(f'field-goal snap spot must be on the field (got {snap_yardline_100!r})')
    offset, ceiling = RULES[rule]
    distance = snap_yardline_100 + offset
    bucket = _historical_snap_bucket(snap_yardline_100)
    out = {
        'snap_yardline_100': snap_yardline_100,
        'kick_distance_yards': distance,
        'historical_ceiling_yards': ceiling,
        'eligible': distance <= ceiling,
        'historical_outcome_bucket': bucket,
        'historical_bucket_kick_distance_range_yards': _bucket_kick_distance_range(bucket, offset),
        'outcome_probability_basis': 'pinned_2022_2025_historical_snap_yardline_bucket',
        'source_file': REFERENCE_FILE,
        'source_sha256': REFERENCE_SHA256,
    }
    if rule is not None:
        out['rule'] = rule
    return out
