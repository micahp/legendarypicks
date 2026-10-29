"""SLC model, layer 1: the score-by-clock play-call model, connected to the drive engine (research, not adopted).

Each scrimmage play is chosen before its outcome is sampled. The frozen hierarchical play-call model gives the probability that
the offense calls a dropback from the current situation: down, distance, field position, score difference, quarter, clock and
offense team. The sampler then draws the play type from that probability and draws the outcome from historical plays of that
type in the same situation cell. Kick decisions are not modelled yet: they use the cell's historical share, and that is recorded
as a fallback on every decision.

The layer uses frozen coefficients only. Season effects are not applied: the model never fits a season it has not seen, so the
effect for a future season is zero. An unknown offense team adds no team effect.

Usage:
  python3 slc_playcall.py freeze --cache NPZ --report JSON --out JSON
"""
import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e0_single_play as e0  # noqa: E402
import e1_drive as e1  # noqa: E402
import playcall_model as pm  # noqa: E402
import formation_layer  # noqa: E402
import pre_event as pe  # noqa: E402
import run_playcall_eval as rpe  # noqa: E402

ARTIFACT_ID = 'slc_playcall_v1'
UNKNOWN = formation_layer.UNKNOWN
SCRIMMAGE_INTENTS = ('run', 'dropback')
KICK_INTENT = 'kick'
BLOCK_GROUPS = ('down_dist', 'field', 'score', 'clock', 'score_clock', 'down_field', 'team_down')


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze(frame, penalties, tau, reference_season):
    """Fit the full model on every primary play in the frame, and return the frozen artifact.

    The recency weights are taken relative to `reference_season` (the season being forecast). No play from that season is used.
    """
    a = frame.a
    primary = ~a['flagged']
    rows = rpe.rows_for(a['season'], primary, sorted(set(int(s) for s in a['season'])), primary=True)
    if any(int(s) >= reference_season for s in a['season'][rows]):
        raise ValueError(f'the frozen model may use seasons before {reference_season} only')
    design = pm.Design(frame)
    prep = pm.prepare(design, rows, pm.GROUP_NAMES)
    weights = pm.recency_weights(a['season'][rows], reference_season, tau)
    beta, nit = pm.fit_prepared(design, prep, a['y'][rows].astype(float), weights, penalties)
    groups = design.col_group[prep['cols']]
    blocks = {}
    for g in BLOCK_GROUPS:
        code = pm.GROUP_CODE[g]
        blocks[g] = [float(v) for v in beta[groups == code]]
    intercept = float(beta[groups == 0][0])
    teams = [code for code, _ in sorted(frame.teams.items(), key=lambda item: item[1])]
    artifact = {
        'artifact_id': ARTIFACT_ID, 'reference_season': int(reference_season), 'recency_tau': tau,
        'fit_seasons': sorted(set(int(s) for s in a['season'][rows])), 'primary_plays_only': True,
        'penalties': penalties, 'fit_iterations': nit, 'plays': int(len(rows)),
        'frame_sha256': pm.frame_content_hash(frame), 'teams': teams, 'intercept': intercept, 'blocks': blocks,
        'bucket_maps': {'down_dist': 'down*6 + distance bucket', 'field': 'field bucket', 'score': 'score bucket',
                        'clock': 'clock bucket', 'score_clock': 'score bucket*8 + clock bucket',
                        'down_field': 'down*5 + field bucket', 'team_down': 'team index*4 + down'},
        'season_effect': 'not applied: a future season has no fitted effect',
    }
    artifact['sha256'] = _sha(artifact)
    return artifact


class PlayCallLayer:
    """Frozen play-call probabilities. `p_dropback` needs only the situation and the offense team."""

    def __init__(self, artifact):
        if artifact.get('artifact_id') != ARTIFACT_ID:
            raise ValueError(f'not a {ARTIFACT_ID} artifact')
        expected = _sha({k: v for k, v in artifact.items() if k != 'sha256'})
        if artifact.get('sha256') != expected:
            raise ValueError('play-call artifact hash does not match its contents')
        self.artifact = artifact
        self.team_index = {code: i for i, code in enumerate(artifact['teams'])}
        self.blocks = {g: np.asarray(v, dtype=float) for g, v in artifact['blocks'].items()}
        self.intercept = artifact['intercept']

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def logit(self, down, togo, yl, score_diff, quarter, clock, team=None):
        d = int(down) - 1
        dist = pm.distance_bucket(int(togo))
        field = pm.field_bucket(int(yl))
        score = pm.score_bucket(int(score_diff))
        clock_index = pm.clock_bucket(int(quarter), None if clock is None else int(clock))
        eta = self.intercept
        eta += self.blocks['down_dist'][d * len(pm.DISTANCE_BUCKETS) + dist]
        eta += self.blocks['field'][field]
        eta += self.blocks['score'][score]
        eta += self.blocks['clock'][clock_index]
        eta += self.blocks['score_clock'][score * len(pm.CLOCK_BUCKETS) + clock_index]
        eta += self.blocks['down_field'][d * len(pm.FIELD_BUCKETS) + field]
        if team is not None and team in self.team_index:
            eta += self.blocks['team_down'][self.team_index[team] * pm.DOWN_COUNT + d]
        return float(eta)

    def p_dropback(self, down, togo, yl, score_diff, quarter, clock, team=None):
        return float(pm.expit(self.logit(down, togo, yl, score_diff, quarter, clock, team)))


def intent_of(event, row):
    """The play type a historical row was. Kicks are their own intent; the rest follow the row's play type."""
    if event in e1.KICK_EVENTS:
        return KICK_INTENT
    return 'run' if row['play_type'] == 'run' else 'dropback'


class PlayCallSampler:
    """Drive-policy slot: choose the play from the situation, then sample its outcome from the same cell.

    `side_teams` maps the engine's side labels ('A', 'B') to team codes, so the offense team can reach the layer.
    Every decision is kept in `decisions`, with the state before the play, the probability used and the historical row it drew.
    """

    def __init__(self, layer, side_teams=None):
        self.layer = layer
        self.side_teams = dict(side_teams) if side_teams is not None else None
        self.decisions = []
        self._cells = {}
        self.participant_chooser = None  # set per game by slc_engine: chooses the rusher or target before the outcome is drawn
        # a team_tendency.TeamTendencies from prior seasons: reweights the outcome drawn within the intent (None: no split)
        self.team_outcomes = None
        # formation-conditioned outcome draws, on when the engine has formation labels and priors (formation_layer)
        self.formation_outcomes = False
        self.formation_priors = None

    def _team(self, label):
        if self.side_teams is None:
            return None
        return self.side_teams.get(label)

    def _entry(self, cell):
        cached = self._cells.get(id(cell))
        if cached is not None:
            return cached[1]
        key = None
        by_key = defaultdict(list)
        for sample in cell:
            situation = (int(sample[1]['down']), e0.ydstogo_bucket(sample[1]['ydstogo']),
                         e0.yardline_bucket(sample[1]['yardline_100']))
            if key is None:
                key = situation
            elif situation != key:
                raise ValueError('a pool cell mixes situations; the play-call layer cannot be applied')
            by_key[(intent_of(sample[0], sample[1]), sample[0])].append(sample)
        base = Counter({k: len(v) for k, v in by_key.items()})
        by_formation = defaultdict(Counter)  # outcome-type counts by the play's published formation (UNKNOWN when none)
        for sample in cell:
            by_formation[sample[1].get('formation', UNKNOWN)][(intent_of(sample[0], sample[1]), sample[0])] += 1
        entry = {'key': key, 'base': base, 'by_formation': dict(by_formation),
                 'by_key': {k: sorted(v, key=lambda s: (s[1]['game_id'], s[1]['play_id'])) for k, v in by_key.items()}}
        self._cells[id(cell)] = (cell, entry)
        return entry

    def sample(self, rng, cell, offense, defense, state=None):
        if state is None or any(state.get(k) is None for k in ('quarter', 'clock', 'down', 'togo', 'yl', 'score_diff')):
            raise e1.SamplingUnavailable('playcall_state_incomplete')
        entry = self._entry(cell)
        total = sum(entry['base'].values())
        kick_keys = [k for k in entry['base'] if k[0] == KICK_INTENT]
        kick_share = sum(entry['base'][k] for k in kick_keys) / total
        team = self._team(offense)
        p = self.layer.p_dropback(state['down'], state['togo'], state['yl'], state['score_diff'], state['quarter'],
                                  state['clock'], team)
        if kick_keys and rng.random() < kick_share:
            intent, fallback = KICK_INTENT, 'kick decision: historical share of this situation cell (not yet modelled)'
        else:
            intent = 'dropback' if rng.random() < p else 'run'
            fallback = None
        keys = sorted(k for k in entry['base'] if k[0] == intent)
        if not keys:
            raise e1.SamplingUnavailable(f'playcall_no_{intent}_outcomes_in_cell:{entry["key"]}')
        pre_event = self.participant_chooser(intent, offense, state) if self.participant_chooser is not None else None
        formation = pre_event.get('formation') if pre_event else None  # chosen before the outcome, from the situation alone
        weights = []
        for k in keys:
            weight = entry['base'][k]
            if formation is not None and self.formation_outcomes:
                weight = self._formation_weight(entry, k, formation) * total
            if self.team_outcomes is not None:  # team splits weight which outcome type is drawn within the intent
                weight *= self._outcome_weight(k[1], offense, defense, entry['key'])
            weights.append(weight)
        if self.team_outcomes is None and formation is None:
            key = rng.choices(keys, weights=[entry['base'][k] for k in keys])[0]  # the unchanged baseline draw
        else:
            key = rng.choices(keys, weights=weights)[0]
        candidates = entry['by_key'][key]
        if formation is not None and self.formation_outcomes:
            matched = [c for c in candidates if c[1].get('formation', UNKNOWN) == formation]
            candidates = matched or candidates  # no row with this formation in the cell: the cell's rows
        event, row, runoff, spot = rng.choice(candidates)
        if pre_event is not None:
            row = dict(row, pre_event=pre_event)  # the chosen participants travel with the outcome; the row itself is not changed
        self.decisions.append({
            'participants': pe.ids(pre_event),
            'formation': formation, 'personnel': pre_event.get('personnel') if pre_event else None,
            'formation_conditioned': bool(formation is not None and self.formation_outcomes),
            'team_outcome_split': self.team_outcomes is not None,
            'state': {'quarter': int(state['quarter']), 'clock': int(state['clock']), 'down': int(state['down']),
                      'togo': int(state['togo']), 'yardline_100': int(state['yl']),
                      'score_diff': int(state['score_diff']), 'offense': offense, 'defense': defense, 'team': team},
            'component': ARTIFACT_ID, 'artifact_sha256': self.layer.artifact['sha256'],
            'p_dropback': round(p, 6), 'kick_share': round(kick_share, 6), 'intent': intent, 'event': event,
            'fallback': fallback, 'source': {'game_id': row['game_id'], 'play_id': row['play_id'], 'season': row['season']},
        })
        return event, row, runoff, spot

    def _formation_weight(self, entry, key, formation):
        """P(outcome type | formation) for this cell, shrunk to the cell's own share with the formation layer's strength."""
        base_share = entry['base'][key] / sum(entry['base'].values())
        counts = entry['by_formation'].get(formation, Counter())
        n_formation = sum(counts.values())
        return (counts[key] + formation_layer.PRIOR_STRENGTH * base_share) / (n_formation + formation_layer.PRIOR_STRENGTH)

    def _outcome_weight(self, event, offense, defense, cell):
        """Offense and defense event ratios for this cell, multiplied. A team with no prior-season sample adds no effect."""
        weight = 1.0
        for side, label in (('offense', offense), ('defense', defense)):
            team = self._team(label)
            if team is None:
                continue
            try:
                weight *= self.team_outcomes.ratio(side, team, cell, event)
            except ValueError:  # no prior-season sample for this team
                continue
        return weight

    def describe(self):
        return {'component': ARTIFACT_ID, 'artifact_sha256': self.layer.artifact['sha256'],
                'frame_sha256': self.layer.artifact['frame_sha256'], 'side_teams': self.side_teams,
                'reference_season': self.layer.artifact['reference_season']}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='command', required=True)
    fr = sub.add_parser('freeze')
    fr.add_argument('--cache', type=Path, required=True)
    fr.add_argument('--report', type=Path, required=True)
    fr.add_argument('--out', type=Path, required=True)
    fr.add_argument('--reference-season', type=int, default=2026)
    fr.add_argument('--last-season', type=int, default=2025, help='last fitted season; a cutoff fit for a game season S uses S-1')
    args = ap.parse_args(argv)
    if args.command == 'freeze':
        report = json.loads(args.report.read_text())
        frame = pm.load_frame_cached(args.cache, range(2010, args.last_season + 1), include_flagged=True)
        artifact = freeze(frame, report['chosen_penalties'], report['chosen_recency_tau'], args.reference_season)
        args.out.write_text(json.dumps(artifact, indent=1, sort_keys=True) + '\n')
        print(json.dumps({'artifact_id': artifact['artifact_id'], 'sha256': artifact['sha256'], 'plays': artifact['plays'],
                          'intercept': artifact['intercept']}))


if __name__ == '__main__':
    main()
