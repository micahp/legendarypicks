"""Assertions for V1 Complete play stages, separate from historical SLC tracing."""
from football_assertions import FootballAssertionError


STAGES = ('personnel', 'formation', 'call', 'snap', 'live_ball', 'whistle', 'next_snap')


def assert_play_order(stages):
    """Reject missing, repeated, or out-of-order stages with the first mismatch."""
    for index in range(max(len(stages), len(STAGES))):
        expected = STAGES[index] if index < len(STAGES) else None
        actual = stages[index] if index < len(stages) else None
        if expected != actual:
            raise FootballAssertionError('NONCAUSAL_INFORMATION', 'v1_complete_play_order', context={
                'index': index, 'expected': expected, 'actual': actual, 'stages': list(stages)})


def assert_no_historical_execution(event, context):
    """Fail closed when a trace encounters a historical whole-play execution path."""
    if event in ('historical_kickoff_selected', 'historical_outcome_selected', 'historical_overtime_drive_selected'):
        raise FootballAssertionError('UNSUPPORTED_RULE', 'v1_complete_historical_execution',
                                     context={'event': event, **context})
