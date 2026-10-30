"""Structured evidence for deterministic football realism assertion failures."""
from __future__ import annotations

import ast
import re


SCHEMA = 'lp.nfl.football-realism-assertion-failure.v1'
FAILURE_CLASSES = frozenset({
    'ILLEGAL_STATE', 'NONCAUSAL_INFORMATION', 'STAT_ACCOUNTING',
    'UNSUPPORTED_RULE', 'DISTRIBUTION_WARNING',
})

_PLAY_INDEX = re.compile(r'\bplay(?:_index)?[\s:=#]+(\d+)\b', re.IGNORECASE)
_DRIVE_INDEX = re.compile(r'\bdrive\s+(\d+)\b', re.IGNORECASE)


class FootballAssertionError(AssertionError):
    """A hard football assertion with machine-readable failure evidence."""

    def __init__(self, failure_class, message, *, context=None):
        if failure_class not in FAILURE_CLASSES:
            raise ValueError(f'unknown football assertion failure class: {failure_class!r}')
        self.failure_class = failure_class
        self.context = dict(context or {})
        self.violated_assertion = str(message)
        self.context.setdefault('violated_assertion', self.violated_assertion)
        super().__init__(f'{failure_class}: {message}; context={self.context!r}')


def classify_failure(error, *, default='ILLEGAL_STATE'):
    """Map known validator failures to the suite taxonomy; callers may pass an explicit class."""
    typed_class = getattr(error, 'failure_class', None)
    if typed_class in FAILURE_CLASSES:
        return typed_class
    if default not in FAILURE_CLASSES:
        raise ValueError(f'unknown football assertion failure class: {default!r}')
    message = str(error).lower()
    if 'stat_accounting' in message or 'player/team stats do not reconcile' in message \
            or 'player/team accounting mismatch' in message:
        return 'STAT_ACCOUNTING'
    if 'noncausal_information' in message:
        return 'NONCAUSAL_INFORMATION'
    if 'distribution_warning' in message:
        return 'DISTRIBUTION_WARNING'
    if any(term in message for term in (
        'unsupported rule', 'unsupported_rules', 'unmodelled', 'unmodeled',
        'not modelled', 'not modeled', 'no observations for',
    )):
        return 'UNSUPPORTED_RULE'
    return default


def _embedded_context(message):
    marker = 'context='
    position = message.find(marker)
    if position < 0:
        return {}
    raw = message[position + len(marker):].strip()
    try:
        context = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return {}
    return context if isinstance(context, dict) else {}


def _json_safe(value):
    """Normalize assertion context to values accepted by the JSONL batch ledger."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    item = getattr(value, 'item', None)
    if callable(item):
        try:
            return _json_safe(item())
        except (TypeError, ValueError):
            pass
    return repr(value)


def failure_envelope(error, *, seed, game_id='unknown', record=None, decisions=None,
                     source_artifact_hashes=None, failure_class=None):
    """Build a JSON-serializable failure record with the closest available play evidence."""
    if isinstance(error, BaseException):
        error_type = type(error).__name__
        message = str(error)
    else:
        error_type = 'AssertionError'
        message = str(error)
    category = failure_class or classify_failure(error)
    if category not in FAILURE_CLASSES:
        raise ValueError(f'unknown football assertion failure class: {category!r}')

    embedded = getattr(error, 'context', None)
    if not isinstance(embedded, dict):
        embedded = _embedded_context(message)
    snapshot = (record or {}).get('pregame_snapshot') or {}
    embedded_game = embedded.get('game_id')
    snapshot_game = (snapshot.get('schedule') or {}).get('game_id')
    resolved_game = next((value for value in (embedded_game, snapshot_game, game_id)
                          if value and value != 'unknown'), 'unknown')
    play_index = embedded.get('play_index')
    if type(play_index) is not int:
        match = _PLAY_INDEX.search(message)
        play_index = int(match.group(1)) if match else None

    plays = [play for drive in (record or {}).get('drives', []) for play in drive.get('plays', [])]
    if play_index is None:
        drive_match = _DRIVE_INDEX.search(message)
        if drive_match:
            drive_index = int(drive_match.group(1))
            drive = next((item for item in (record or {}).get('drives', [])
                          if item.get('index') == drive_index), None)
            drive_plays = (drive or {}).get('plays') or []
            if drive_plays:
                matching = drive_plays[-1]
                play_index = matching.get('sequence')
                if type(play_index) is not int:
                    play_index = next((i for i, play in enumerate(plays, 1) if play is matching), None)
    matching_play = next((play for play in plays if play.get('sequence') == play_index), None)
    if matching_play is None and play_index is not None and 1 <= play_index <= len(plays):
        matching_play = plays[play_index - 1]

    decision = embedded.get('decision')
    if decision in (None, 'unavailable') and play_index is not None and decisions and play_index <= len(decisions):
        decision = decisions[play_index - 1]
    state_before = embedded.get('state_before')
    if state_before is None:
        state_before = matching_play.get('state_before', 'unavailable') if matching_play else 'unavailable'
    outcome = embedded.get('outcome')
    if outcome is None:
        if matching_play:
            outcome = {'event_type': matching_play.get('event_type'), **(matching_play.get('outcome') or {})}
        else:
            outcome = {'error_type': error_type, 'message': message}
    state_after = embedded.get('state_after')
    if state_after is None:
        state_after = matching_play.get('state_after', 'unavailable') if matching_play else 'unavailable'

    hashes = dict(source_artifact_hashes or {})
    hashes.update(embedded.get('source_artifact_hashes') or {})
    snapshot_hash = snapshot.get('snapshot_sha256')
    if snapshot_hash:
        hashes.setdefault('snapshot.snapshot_sha256', snapshot_hash)

    return _json_safe({
        'schema': SCHEMA,
        'failure_class': category,
        'error_type': error_type,
        'game_id': resolved_game,
        'seed': seed,
        'play_index': play_index,
        'state_before': state_before,
        'decision': decision if decision is not None else 'unavailable',
        'outcome': outcome,
        'state_after': state_after,
        'violated_assertion': (embedded.get('violated_assertion')
                               or getattr(error, 'violated_assertion', None) or message),
        'source_artifact_hashes': hashes,
    })


def unresolved_transition_envelope(record, *, seed, game_id='unknown', source_artifact_hashes=None):
    """Describe a fail-closed unsupported transition without treating a blocked game as a valid result."""
    blocked = (record or {}).get('blocked_attempt') or {}
    partial = blocked.get('plays_before_block') or []
    completed_plays = sum(len(drive.get('plays') or []) for drive in (record or {}).get('drives', []))
    play_index = completed_plays + len(partial) + 1
    state_before = (partial[-1].get('state_after') if partial else None) or blocked.get('state_at_drive_start') or 'unavailable'
    blocker = blocked.get('blocker') or (record or {}).get('blocker') or 'unresolved'
    return _json_safe({
        'schema': SCHEMA,
        'failure_class': 'UNSUPPORTED_RULE',
        'status': 'unresolved',
        'game_id': game_id,
        'seed': seed,
        'play_index': play_index,
        'state_before': state_before,
        'decision': {'type': 'resolve_unmodelled_transition', 'drive_index': blocked.get('drive_index')},
        'outcome': {'status': 'unresolved', 'blocker': blocker},
        'state_after': {'status': 'unresolved', 'blocker': blocker},
        'violated_assertion': f'unsupported football transition remains unresolved: {blocker}',
        'source_artifact_hashes': dict(source_artifact_hashes or {}),
    })
