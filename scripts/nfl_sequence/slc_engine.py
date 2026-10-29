"""The SLC v1 configuration, shared by the single-game runner and the batch runner (research, not adopted).

One place decides what an SLC game is: a pregame snapshot, a historical pool cut to the weeks before that game, and the frozen
score-clock play-call layer as the drive policy. The play-call artifact must have been fitted only on seasons before the game's
season. The runners call these functions rather than set the configuration themselves, so they cannot disagree about it.
A game without a snapshot is refused: the first-piece path has no pregame missed-kick return and no roster, so it would be a
different model under the SLC name.
"""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e2_reference as er  # noqa: E402
import game_state as gs  # noqa: E402
import slc_playcall as slc  # noqa: E402

MODEL_ID = 'slc_v1_incomplete'


def require_snapshot(snapshot):
    if not isinstance(snapshot, dict) or 'schedule' not in snapshot or 'rosters' not in snapshot:
        raise ValueError('SLC v1 needs a pregame snapshot; the first-piece path without one is not an SLC game')
    return snapshot


def side_teams(snapshot):
    """Offense side A is the home team and B the away team, as in the engine's team_identity (game_state.py)."""
    schedule = require_snapshot(snapshot)['schedule']
    return {'A': schedule['home_team'], 'B': schedule['away_team']}


def check_artifact_cutoff(artifact, season):
    """The layer may use only seasons before the game's season, and its recency reference is that season."""
    fit = sorted(int(s) for s in artifact['fit_seasons'])
    if int(artifact['reference_season']) != int(season):
        raise ValueError(f"play-call artifact reference season {artifact['reference_season']} is not the game season {season}")
    if not fit or fit[-1] >= int(season):
        raise ValueError(f"play-call artifact is fitted through {fit[-1] if fit else None}; a {season} game needs a fit "
                         f"that ends before {season}")


def load_reference(db, snapshot, artifact_path):
    """(Reference, excluded_kickoffs) for one snapshot. The play pool holds only prior seasons: no outcome from the game's own
    season is used, so a 2026 forecast draws on 2022 to 2025 and not on the 2026 results before it."""
    schedule = require_snapshot(snapshot)['schedule']
    season = int(schedule['season'])
    check_artifact_cutoff(json.loads(Path(artifact_path).read_text()), season)
    return er.load(db, eligible_before=(season, 1), playcall_artifact=str(artifact_path),
                   playcall_teams=side_teams(snapshot))


def is_slc(ref):
    return isinstance(getattr(ref, 'contextual_sampler', None), slc.PlayCallSampler)


def play(seed, ref, snapshot):
    """One SLC game. Returns (record, decisions): the engine record and this game's play-call decisions, in order."""
    if not is_slc(ref):
        raise ValueError('the reference was not loaded with the SLC play-call layer')
    sampler = ref.contextual_sampler
    sampler.decisions.clear()
    record = gs.play_game(seed, ref, pregame_snapshot=copy.deepcopy(require_snapshot(snapshot)))
    decisions = list(sampler.decisions)
    sampler.decisions.clear()
    return record, decisions


def summary(decisions):
    return {'decisions': len(decisions),
            'scrimmage': sum(d['intent'] != 'kick' for d in decisions),
            'dropback': sum(d['intent'] == 'dropback' for d in decisions),
            'run': sum(d['intent'] == 'run' for d in decisions),
            'kick_fallback': sum(d['intent'] == 'kick' for d in decisions)}


def describe(ref):
    """The layer's manifest for a batch payload: None for the S0 control."""
    if not is_slc(ref):
        return None
    sampler = ref.contextual_sampler
    artifact = sampler.layer.artifact
    return {'model_id': MODEL_ID, 'artifact_id': artifact['artifact_id'], 'artifact_sha256': artifact['sha256'],
            'fit_seasons': sorted(int(s) for s in artifact['fit_seasons']),
            'reference_season': int(artifact['reference_season']), 'side_teams': sampler.describe().get('side_teams')}
