"""Current-state field-goal distance and the pinned historical eligibility ceiling."""
import math

SNAP_TO_KICK_OFFSET_YARDS = 17  # holder placement (7) plus the 10-yard end zone
MAX_HISTORICAL_KICK_DISTANCE_YARDS = 70
REFERENCE_FILE = 'docs/fixtures/e2/kick_results_2022_2025.csv'
REFERENCE_SHA256 = '193f2d2390c36a968b42da1e851eba9c0b0c79bb2822fbcaff4aa3d6d0ce0a93'


def _historical_snap_bucket(snap_yardline_100):
    for upper, label in ((10, '1-9'), (20, '10-19'), (30, '20-29'),
                         (40, '30-39'), (50, '40-49')):
        if snap_yardline_100 < upper:
            return label
    return '50+'


def _bucket_kick_distance_range(bucket):
    if bucket == '50+':
        return '67+'
    low, high = (int(part) for part in bucket.split('-'))
    return f'{low + SNAP_TO_KICK_OFFSET_YARDS}-{high + SNAP_TO_KICK_OFFSET_YARDS}'


def evaluate(snap_yardline_100):
    """Compute a kick's distance from the current snap spot, then apply the pinned historical ceiling."""
    # Half-distance penalty enforcement can leave the ball at a fractional
    # field position.  The original integer-only check incorrectly aborted
    # otherwise valid next-snap states after an accepted penalty.
    if (type(snap_yardline_100) not in (int, float)
            or not math.isfinite(snap_yardline_100)
            or not 0 < snap_yardline_100 < 100):
        raise ValueError(f'field-goal snap spot must be on the field (got {snap_yardline_100!r})')
    distance = snap_yardline_100 + SNAP_TO_KICK_OFFSET_YARDS
    bucket = _historical_snap_bucket(snap_yardline_100)
    return {
        'snap_yardline_100': snap_yardline_100,
        'kick_distance_yards': distance,
        'historical_ceiling_yards': MAX_HISTORICAL_KICK_DISTANCE_YARDS,
        'eligible': distance <= MAX_HISTORICAL_KICK_DISTANCE_YARDS,
        'historical_outcome_bucket': bucket,
        'historical_bucket_kick_distance_range_yards': _bucket_kick_distance_range(bucket),
        'outcome_probability_basis': 'pinned_2022_2025_historical_snap_yardline_bucket',
        'source_file': REFERENCE_FILE,
        'source_sha256': REFERENCE_SHA256,
    }
