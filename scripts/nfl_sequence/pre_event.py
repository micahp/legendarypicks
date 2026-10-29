"""Participants chosen before the play's outcome is drawn (SLC v1, research, not adopted).

After the play-call layer picks the intent (run or dropback), this module picks who carries the ball or who is the target. The
choice depends on the pregame roster and usage shares only, and it is made before the outcome row is drawn. The outcome then
determines what happens to the chosen player (a completion, an incompletion, a sack, a rush), and the player is not re-chosen
after the outcome.

The outcome is not yet conditioned on the player. Yards and results still come from the historical row of the play's situation
cell. That is a known limit of this version: participant-conditioned outcomes are not built.

Every draw is seeded from the snapshot hash, the game seed and the decision index, so a replay with the same inputs is identical.
"""
import hashlib
import random

PASS_EVENTS = ('pass_complete', 'pass_incomplete', 'interception', 'sack')
TARGET_EVENTS = ('pass_complete', 'pass_incomplete', 'interception')  # a sack has no target


def _draw(seed_text):
    return random.Random(int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], 'big'))


def _qb1(players, team):
    starters = [p for p in players if p['pos_abb'] == 'QB' and p['pos_rank'] == 1]
    if len(starters) != 1:
        raise ValueError(f'pregame snapshot must have exactly one QB1 for {team}')
    return starters[0]


def _by_usage(players, usage, team, label, draw):
    shares = usage['shares']
    positions = [pos for pos, share in shares.items() if share > 0 and any(p['pos_abb'] == pos for p in players)]
    if not positions:
        raise ValueError(f'pregame snapshot has no eligible {label} positions for {team}')
    position = draw.choices(positions, weights=[shares[pos] for pos in positions], k=1)[0]
    eligible = sorted((p for p in players if p['pos_abb'] == position), key=lambda p: (p['pos_rank'], p['gsis_id']))
    return draw.choices(eligible, weights=[1 / p['pos_rank'] for p in eligible], k=1)[0]


def choose(snapshot, side, intent, seed, index):
    """{'passer': ..., 'receiver': ...} for a dropback, {'rusher': ...} for a run, None otherwise. Chosen before the outcome."""
    if intent not in ('run', 'dropback'):
        return None
    roster = snapshot['rosters'][side]
    team, players = roster['team'], roster['players']
    observed = snapshot['model_reference']['observed_reference']
    base = f"{snapshot['snapshot_sha256']}:{seed}:{index}"
    chosen = {'side': side, 'team': team}
    if intent == 'dropback':
        chosen['passer'] = _qb1(players, team)
        chosen['receiver'] = _by_usage(players, observed['receiver_position_usage'], team, 'receiver',
                                       _draw(f'{base}:receiver:position'))
    else:
        chosen['rusher'] = _by_usage(players, observed['runner_position_usage'], team, 'rusher',
                                     _draw(f'{base}:rusher:position'))
    return chosen


def chooser(snapshot, seed):
    """A callable for PlayCallSampler.participant_chooser: called once per scrimmage play, after the intent, before the outcome.
    The decision index counts those calls, so it is the same on every replay of the same game."""
    counter = {'index': 0}

    def pick(intent, offense):
        index = counter['index']
        counter['index'] += 1
        side = 'home' if offense == 'A' else 'away'
        return choose(snapshot, side, intent, seed, index)
    return pick


def ids(pre):
    """The chosen players' GSIS ids, for the decision record."""
    if pre is None:
        return None
    return {role: player['gsis_id'] for role, player in pre.items() if isinstance(player, dict)}
