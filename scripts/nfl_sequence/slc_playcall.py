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
import field_goal_feasibility as fg_feasibility  # noqa: E402
import playcall_model as pm  # noqa: E402
import formation_layer  # noqa: E402
import point_splits  # noqa: E402
import decision_layer  # noqa: E402
import streak_splits  # noqa: E402
import pre_event as pe  # noqa: E402
import run_playcall_eval as rpe  # noqa: E402

ARTIFACT_ID = 'slc_playcall_v1'
UNKNOWN = formation_layer.UNKNOWN
SCRIMMAGE_INTENTS = ('run', 'dropback')
# restore_sack_mass (ablation A): the observed per-cell sack rates, written by obs_sack_cells.py and pinned by sha256
OBS_SACK_CELLS_PATH = Path(__file__).resolve().parents[2] / 'docs/research/slc-scoring-realism-ablation-A/obs_sack_cells.json'
OBS_SACK_CELLS_SHA256 = '3010131cc898d1c534a1d023b7d6c31dba6fd94d2506eaf60bb952d61a2a31e8'
_OBS_SACK_CELLS = None
KICK_INTENT = 'kick'
LATERAL_ROW_FIELDS = ('lateral_receiver_player_id', 'lateral_receiving_yards',
                      'lateral_rusher_player_id', 'lateral_rushing_yards')
BLOCK_GROUPS = ('down_dist', 'field', 'score', 'clock', 'score_clock', 'down_field', 'team_down')
OUTCOME_BACKOFF_MIN_SUPPORT = {
    'exact_cell': 10,
    'down_field': 25,
    'down_distance': 25,
    'field_zone': 50,
    'league_intent': 50,
}


def _event_probability_stage(name, keys, weights):
    total = float(sum(weights))
    return {'stage': name, 'probabilities': {
        str(key[1]): round(float(weight) / total, 8) for key, weight in zip(keys, weights)
    } if total > 0 else {}, 'weight_total': round(total, 8)}


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
        return self.logit_of_buckets(int(down) - 1, pm.distance_bucket(int(togo)), pm.field_bucket(int(yl)),
                                     pm.score_bucket(int(score_diff)),
                                     pm.clock_bucket(int(quarter), None if clock is None else int(clock)), team)

    def logit_of_buckets(self, d, dist, field, score, clock_index, team=None):
        """The logit for a situation already in the frame's buckets (d is the down minus one)."""
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


def _obs_sack_cells():
    """The committed observed sack rates by cell. Refuses to load a file whose sha256 is not the pinned one."""
    global _OBS_SACK_CELLS
    if _OBS_SACK_CELLS is None:
        raw = OBS_SACK_CELLS_PATH.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != OBS_SACK_CELLS_SHA256:
            raise ValueError(f'obs_sack_cells.json sha256 {digest} is not the pinned {OBS_SACK_CELLS_SHA256}')
        _OBS_SACK_CELLS = json.loads(raw)['cells']
    return _OBS_SACK_CELLS


def sack_substitution_rate(entry):
    """q(cell) = max(0, (obs - r) / inc): the chance an incomplete pass in this cell becomes a sack under ablation A.

    r and inc are the simulator's own sack and incomplete shares for the cell, read from its outcome counts."""
    cell = _obs_sack_cells().get(str(entry['key']))
    if cell is None:
        raise ValueError(f'no observed sack rate for cell {entry["key"]}')
    dropbacks = sum(count for key, count in entry['base'].items() if key[0] == 'dropback')
    if dropbacks == 0:
        return 0.0
    sim_sack = entry['base'].get(('dropback', 'sack'), 0) / dropbacks
    sim_incomplete = entry['base'].get(('dropback', 'pass_incomplete'), 0) / dropbacks
    if sim_incomplete == 0:
        return 0.0
    return max(0.0, (cell['obs_sack_rate'] - sim_sack) / sim_incomplete)


def historical_cell_dropback_probability(base_counts):
    """Return the run/pass share in the current down-distance-field cell, excluding kick decisions."""
    runs = sum(count for (intent, _event), count in base_counts.items() if intent == 'run')
    dropbacks = sum(count for (intent, _event), count in base_counts.items() if intent == 'dropback')
    total = runs + dropbacks
    if total <= 0:
        raise e1.SamplingUnavailable('no_supported_scrimmage_intent_in_cell')
    return dropbacks / total


class PlayCallSampler:
    """Drive-policy slot: choose the play from the situation, then sample its outcome from the same cell.

    `side_teams` maps the engine's side labels ('A', 'B') to team codes, so the offense team can reach the layer.
    Every decision is kept in `decisions`, with the state before the play, the probability used and the historical row it drew.
    """

    def __init__(self, layer, side_teams=None):
        self.layer = layer
        self.score_clock_playcalling_enabled = True
        self.side_teams = dict(side_teams) if side_teams is not None else None
        self.decisions = []
        self.trace_outcome_probabilities = False
        self._cells = {}
        self.source_pool = None  # cutoff-filtered pool, supplied by e2_reference only for opted-in backoff
        self._backoff_index = None
        self._backoff_index_uses_lateral_filter = None
        self._backoff_lateral_rows_excluded = 0
        self.outcome_backoff_enabled = False
        self.allow_sparse_cells = False
        self.scramble_backoff_enabled = False
        self.scramble_bounds = None
        self.blocker_fixes = frozenset()
        self.fg_ordinary_cutoff = 60.0
        # research flag (kicker_field_goals, amendment 6): {'table': KickerTable, 'kickers': {side label: gsis_id}}, None off
        self.fg_kicker = None
        self.participant_chooser = None  # set per game by slc_engine: chooses the rusher or target before the outcome is drawn
        # a team_tendency.TeamTendencies from prior seasons: reweights the outcome drawn within the intent (None: no split)
        self.team_outcomes = None
        # Joint event and yardage strength model. Replaces team_outcomes when enabled.
        self.transition_strength = None
        # formation-conditioned outcome draws, on when the engine has formation labels and priors (formation_layer)
        self.formation_outcomes = False
        self.formation_priors = None
        self.player_shares = None  # prior-season player shares for the pre-event participant adapter (player_shares)
        # red-zone geometry: inside the 20, draw the outcome only from rows at the state's exact yard line when there are any
        self.exact_yardline = False
        # team score-state splits: log-odds shifts of the dropback rate by score bucket (point_splits), None when off
        self.point_shifts = None
        # win-loss streak splits: log-odds shifts by streak bucket, and each team's current bucket (streak_splits)
        self.streak_shifts = None
        self.current_streak = {}
        # league-wide streak effects: a league dropback shift by bucket (streak_splits.league_priors), and outcome lifts by bucket
        self.streak_league = None
        # decision model category A (target role) prior, used by the pre-event receiver choice (target_roles)
        self.role_table = None
        self.streak_outcomes = False
        # defensive coverage on dropbacks: the defense's prior shares (defense_layer) and the coverage-conditioned outcomes
        self.coverage_outcomes = False
        self.defense_priors = None
        # decision model categories A to N (decision_layer): the prior tables, and the outcome lifts and filters on the drawn labels
        self.decision_table = None
        self.decision_outcomes = False
        self.decision_filter = True  # False: the lifts shape the outcome, but the row is drawn from the whole cell (an experiment)
        # per-game Dirichlet target and carry shares (share_distributions), None when off: the receiver and rusher are drawn from them
        self.share_table = None
        # the playbook files as the pre-event prior for pass depth, pass location and run gap (playbook_prior), None when off
        self.playbook_table = None
        # QB-specific pre-event target-role and scramble choices, off unless explicitly loaded.
        self.qb_decision_table = None
        self.qb_run_role_style_enabled = False
        # Per-player event and joint yards/touchdown outcome profiles, off unless explicitly loaded.
        self.player_outcome_table = None
        self.player_outcome_roles = None
        # SLC V1.5 (season_layers): the log-odds offset of each (team, down minus one) toward the current season, applied to the
        # score-clock artifact's probability, and the manifest of every layer's current-season blend. None in V1.
        self.season_team_down = None
        self.season_blend_manifest = None
        self._current_team_outcome_fallbacks = []
        self._current_transition_fallbacks = []

    def _team(self, label):
        if self.side_teams is None:
            return None
        return self.side_teams.get(label)

    @staticmethod
    def _has_lateral(row):
        for field in LATERAL_ROW_FIELDS:
            value = row.get(field)
            if value is None or value == '':
                continue
            try:
                if np.isnan(value):
                    continue
            except (TypeError, ValueError):
                pass
            if value != 0:
                return True
        return False

    def _participant_source_rows(self, samples):
        """Keep only source outcomes whose player attribution this SLC path represents."""
        if self.participant_chooser is None:
            return list(samples), 0
        kept = [sample for sample in samples if not self._has_lateral(sample[1])]
        return kept, len(samples) - len(kept)

    def _entry(self, cell, cache=True):
        use_lateral_filter = self.participant_chooser is not None
        cache_key = (id(cell), use_lateral_filter)
        cached = self._cells.get(cache_key) if cache else None
        if cached is not None:
            return cached[1]
        samples, lateral_rows_excluded = self._participant_source_rows(cell)
        key = None
        by_key = defaultdict(list)
        for sample in samples:
            situation = e0.pool_key(int(sample[1]['down']), sample[1]['ydstogo'], sample[1]['yardline_100'])
            if key is None:
                key = situation
            elif situation != key:
                raise ValueError('a pool cell mixes situations; the play-call layer cannot be applied')
            by_key[(intent_of(sample[0], sample[1]), sample[0])].append(sample)
        base = Counter({k: len(v) for k, v in by_key.items()})
        by_formation = defaultdict(Counter)  # outcome-type counts by the play's published formation (UNKNOWN when none)
        by_coverage = defaultdict(Counter)  # and by the published coverage
        by_streak = defaultdict(Counter)  # and by the offense's streak going into the game
        by_label = defaultdict(Counter)  # and by each decision label ('A=WR'), when the rows carry labels (decision_layer)
        base_labelled = Counter()  # the outcome mix of the labelled rows alone: the charted seasons are a subset of the cell
        for sample in samples:
            outcome = (intent_of(sample[0], sample[1]), sample[0])
            by_formation[sample[1].get('formation', UNKNOWN)][outcome] += 1
            by_coverage[sample[1].get('coverage', UNKNOWN)][outcome] += 1
            if sample[1].get('streak') is not None:
                by_streak[sample[1]['streak']][outcome] += 1
            row_labels = {cat: value for cat, value in (sample[1].get('labels') or {}).items() if value is not None}
            if row_labels:
                base_labelled[outcome] += 1  # once per row, however many labels it carries
            for cat, value in row_labels.items():
                by_label[decision_layer.label_key(cat, value)][outcome] += 1
        entry = {'key': key, 'base': base, 'by_formation': dict(by_formation), 'by_coverage': dict(by_coverage),
                 'by_streak': dict(by_streak), 'by_label': dict(by_label), 'base_labelled': base_labelled,
                 'by_key': {k: sorted(v, key=lambda s: (s[1]['game_id'], s[1]['play_id'])) for k, v in by_key.items()},
                 'lateral_source_rows_excluded': lateral_rows_excluded}
        if cache:
            self._cells[cache_key] = (cell, entry)
        return entry

    def _outcome_rows(self, cell, called_intent, scramble, state=None):
        outcome_intent = 'run' if scramble else called_intent
        samples, _lateral_rows_excluded = self._participant_source_rows(cell)
        rows = [sample for sample in samples if intent_of(sample[0], sample[1]) == outcome_intent]
        if scramble:
            rows = [sample for sample in rows if sample[1].get('qb_scramble') == 1]
            if state is not None:
                rows, rejected = self._legal_scramble_rows(rows, state)
                self._last_scramble_rejected_bounds = rejected
        elif called_intent == 'run':
            rows = [sample for sample in rows if sample[1].get('qb_scramble') != 1]
            self._last_scramble_rejected_bounds = 0
        return rows

    def _legal_scramble_rows(self, rows, state):
        bounds = self.scramble_bounds or {}
        max_gain, max_loss = bounds.get('max_gain_yards'), bounds.get('max_loss_yards')
        legal, rejected = [], 0
        for sample in rows:
            yards = sample[1].get('yards_gained')
            if yards is None:
                rejected += 1
                continue
            yards = int(yards)
            resulting_yardline = int(state['yl']) - yards
            if ((max_gain is not None and yards > max_gain)
                    or (max_loss is not None and yards < -max_loss)
                    or resulting_yardline < 0 or resulting_yardline > 100):
                rejected += 1
            else:
                legal.append(sample)
        return legal, rejected

    def _backoff_candidates(self, state, called_intent, scramble, source_row_filter=None):
        """Find cutoff-safe outcomes without changing the selected play intent or scramble class."""
        if self.source_pool is None:
            return None, None
        target = e0.pool_key(int(state['down']), state['togo'], state['yl'])
        down, distance, field = target
        use_lateral_filter = self.participant_chooser is not None
        if (self._backoff_index is None
                or self._backoff_index_uses_lateral_filter != use_lateral_filter):
            index = {level: defaultdict(lambda: defaultdict(list)) for level in OUTCOME_BACKOFF_MIN_SUPPORT}
            lateral_rows_excluded = 0
            for source_cell in self.source_pool.values():
                samples, excluded = self._participant_source_rows(source_cell)
                lateral_rows_excluded += excluded
                for sample in samples:
                    event, row = sample[0], sample[1]
                    outcome_class = 'qb_scramble' if row.get('qb_scramble') == 1 else intent_of(event, row)
                    exact = e0.pool_key(int(row['down']), row['ydstogo'], row['yardline_100'])
                    row_down, row_distance, row_field = exact
                    keys = {'exact_cell': exact, 'down_field': (row_down, row_field),
                            'down_distance': (row_down, row_distance), 'field_zone': row_field,
                            'league_intent': None}
                    for level, key in keys.items():
                        index[level][outcome_class][key].append(sample)
            self._backoff_index = index
            self._backoff_index_uses_lateral_filter = use_lateral_filter
            self._backoff_lateral_rows_excluded = lateral_rows_excluded
        outcome_class = 'qb_scramble' if scramble else called_intent
        levels = (('exact_cell', target), ('down_field', (down, field)),
                  ('down_distance', (down, distance)), ('field_zone', field), ('league_intent', None))
        for level, key in levels:
            candidates = list(self._backoff_index[level][outcome_class].get(key, ()))
            if source_row_filter is not None:
                candidates = [sample for sample in candidates if source_row_filter(sample, state)]
            if scramble:
                candidates, rejected = self._legal_scramble_rows(candidates, state)
                self._last_scramble_rejected_bounds = rejected
            else:
                self._last_scramble_rejected_bounds = 0
            if len(candidates) >= OUTCOME_BACKOFF_MIN_SUPPORT[level]:
                return candidates, level
        return None, None

    def _dropback_probability(self, entry, state, team):
        if self.score_clock_playcalling_enabled:
            p = self.layer.p_dropback(state['down'], state['togo'], state['yl'], state['score_diff'], state['quarter'],
                                      state['clock'], team)
            if self.season_team_down is not None:
                p = point_splits.adjust(p, self.season_team_down.get((team, int(state['down']) - 1), 0.0))
            return p, 'score_clock_logistic_artifact'
        return (historical_cell_dropback_probability(entry['base']),
                'historical_down_distance_field_cell_rate')

    def sample(self, rng, cell, offense, defense, state=None):
        if state is None or any(state.get(k) is None for k in ('quarter', 'clock', 'down', 'togo', 'yl', 'score_diff')):
            raise e1.SamplingUnavailable('playcall_state_incomplete')
        fg_rule = None
        if self.fg_kicker is not None:
            import kicker_field_goals
            fg_rule = kicker_field_goals.RULE
        field_goal = state.get('field_goal_feasibility')
        if (not isinstance(field_goal, dict)
                or field_goal.get('snap_yardline_100') != int(state['yl']) or field_goal.get('rule') != fg_rule):
            field_goal = fg_feasibility.evaluate(int(state['yl']), rule=fg_rule)
        source_row_filter = state.get('_source_row_filter')
        entry = self._entry(cell, cache=not state.get('_source_cell_filtered', False))
        self._current_team_outcome_fallbacks = []
        self._current_transition_fallbacks = []
        # the kick decision's counts: the whole cell, or with the flag the cell's rows weighted by yard line near the snap
        kick_base = entry['base'] if fg_rule is None else kicker_field_goals.kernel_counts(entry, int(state['yl']))
        total = sum(kick_base.values())
        fg_rejected_distance = False
        fg_long_range_exception = False
        fg_allowed_events = None
        if 'long_field_goal_feasibility' in self.blocker_fixes:
            fg_allowed_events, fg_rejected_distance, fg_long_range_exception = self._field_goal_actions(entry, state)
            if not field_goal['eligible'] and 'field_goal_attempt' in fg_allowed_events:
                fg_allowed_events.discard('field_goal_attempt')
                fg_rejected_distance = True
                fg_long_range_exception = False
            kick_keys = [k for k in kick_base if k[0] == KICK_INTENT]
            rejected_keys = [key for key in kick_keys if key[1] not in fg_allowed_events]
            eligible_kick_keys = [key for key in kick_keys if key[1] in fg_allowed_events]
            feasible_total = total - sum(kick_base[key] for key in rejected_keys)
            kick_share = (sum(kick_base[key] for key in eligible_kick_keys) / feasible_total
                          if feasible_total else 0.0)
            kick_keys = eligible_kick_keys
        else:
            kick_keys = [k for k in kick_base if k[0] == KICK_INTENT
                         and (k[1] != 'field_goal_attempt' or field_goal['eligible'])]
            kick_share = sum(kick_base[k] for k in kick_keys) / total if total else 0.0
        team = self._team(offense)
        p, call_policy_source = self._dropback_probability(entry, state, team)
        split_fallbacks = []
        point_shift = 0.0
        if self.point_shifts is not None and team in self.layer.team_index:
            bucket = pm.score_bucket(state['score_diff'])
            if (int(self.layer.team_index[team]), int(bucket)) not in self.point_shifts['shift']:
                split_fallbacks.append('point_split_missing_bucket')
            point_shift = point_splits.shift_for(self.point_shifts, self.layer.team_index[team], bucket)
            p = point_splits.adjust(p, point_shift)  # the team's score-state deviation, in log-odds
        elif self.point_shifts is not None:
            split_fallbacks.append('point_split_unknown_team')
        streak_shift = 0.0
        if self.streak_shifts is not None and team in self.layer.team_index and team in self.current_streak:
            if (int(self.layer.team_index[team]), self.current_streak[team]) not in self.streak_shifts['shift']:
                split_fallbacks.append('team_streak_split_missing_bucket')
            streak_shift = streak_splits.shift_for(self.streak_shifts, self.layer.team_index[team], self.current_streak[team])
            p = point_splits.adjust(p, streak_shift)  # the team's win-loss streak deviation, in log-odds
        elif self.streak_shifts is not None:
            split_fallbacks.append('team_streak_split_missing_context')
        league_streak_shift = 0.0
        if self.streak_league is not None and team in self.current_streak:
            if (int(streak_splits.LEAGUE), self.current_streak[team]) not in self.streak_league['shift']:
                split_fallbacks.append('league_streak_split_missing_bucket')
            league_streak_shift = streak_splits.shift_for(self.streak_league, streak_splits.LEAGUE, self.current_streak[team])
            p = point_splits.adjust(p, league_streak_shift)  # the league's streak tendency, in log-odds
        elif self.streak_league is not None:
            split_fallbacks.append('league_streak_split_missing_context')
        if kick_keys and rng.random() < kick_share:
            intent, fallback = KICK_INTENT, ('kick decision: historical share of this situation cell (not yet modelled)'
                                             if fg_rule is None else
                                             'kick decision: historical share of this cell weighted by yard line')
        else:
            intent = 'dropback' if rng.random() < p else 'run'
            fallback = None
        called_intent = intent
        pre_event = self.participant_chooser(called_intent, offense, state) if self.participant_chooser is not None else None
        qb_decision = pre_event.get('qb_decision') if pre_event else None
        scramble = bool(qb_decision and qb_decision.get('action') == 'scramble')
        outcome_intent = 'run' if scramble else called_intent
        formation = pre_event.get('formation') if pre_event else None  # chosen before the outcome, from the situation alone
        coverage = pre_event.get('coverage') if pre_event else None  # a dropback decision: the defense's coverage
        if called_intent != 'dropback' or scramble:
            coverage = None
        use_formation = formation is not None and self.formation_outcomes
        use_coverage = coverage is not None and self.coverage_outcomes
        streak_bucket = self.current_streak.get(team) if self.streak_outcomes else None
        use_streak = streak_bucket is not None
        labels = pre_event.get('labels') if pre_event else None
        use_labels = bool(labels) and self.decision_outcomes
        use_player_outcomes = self.player_outcome_table is not None
        target = e0.pool_key(int(state['down']), state['togo'], state['yl'])
        exact_outcome_rows = None
        backoff_candidates, outcome_fallback = (None, None)
        backoff_transition_groups = None
        backoff_ess = None
        outcome_weight_fallback = None
        probability_trace = []
        if self.outcome_backoff_enabled and called_intent in SCRIMMAGE_INTENTS:
            exact_outcome_rows = self._outcome_rows(cell, called_intent, scramble, state)
            if len(exact_outcome_rows) < OUTCOME_BACKOFF_MIN_SUPPORT['exact_cell']:
                backoff_candidates, outcome_fallback = self._backoff_candidates(
                    state, called_intent, scramble, source_row_filter=source_row_filter)
        if backoff_candidates is not None:
            counts = Counter(sample[0] for sample in backoff_candidates)
            keys = sorted((outcome_intent, event) for event in counts)
            weights = [counts[key[1]] for key in keys]
            if self.trace_outcome_probabilities:
                probability_trace.append(_event_probability_stage('base_sparse_backoff', keys, weights))
            if self.team_outcomes is not None:
                weights = [weight * self._outcome_weight(key[1], offense, defense, entry['key'] or target)
                           for weight, key in zip(weights, keys)]
                if self.trace_outcome_probabilities:
                    probability_trace.append(_event_probability_stage('team_event_weights', keys, weights))
            if self.transition_strength is not None:
                backoff_transition_groups = {
                    key[1]: self._group_transition_rows(
                        [sample for sample in backoff_candidates if sample[0] == key[1]], key[1])
                    for key in keys
                }
                weights = [self._transition_group_weight(
                    backoff_transition_groups[key[1]], key[1], offense, defense)
                    for key in keys]
                if self.trace_outcome_probabilities:
                    probability_trace.append(_event_probability_stage('transition_strength', keys, weights))
            if use_player_outcomes:
                import player_outcomes
                weights = [weight * player_outcomes.event_weight(self.player_outcome_table, key[1], pre_event,
                                                                  enabled_roles=self.player_outcome_roles)
                           for weight, key in zip(weights, keys)]
                if self.trace_outcome_probabilities:
                    probability_trace.append(_event_probability_stage('player_event_weights', keys, weights))
            if not any(weight > 0 for weight in weights):
                # These are modifiers within an already-selected play intent. If every modifier rejects
                # its outcomes, retain that intent and fall back to the supported backoff distribution.
                weights = [counts[key[1]] for key in keys]
                outcome_weight_fallback = 'all_conditioned_weights_zero_within_selected_intent'
                if self.trace_outcome_probabilities:
                    probability_trace.append(_event_probability_stage('all_zero_weights_fallback', keys, weights))
            weight_total = sum(weights)
            if weight_total > 0:
                backoff_ess = 1.0 / sum(
                    count * ((weight / weight_total) / count) ** 2
                    for weight, key in zip(weights, keys)
                    for count in (counts[key[1]],) if count)
            if self.trace_outcome_probabilities:
                probability_trace.append(_event_probability_stage('final_event_draw', keys, weights))
            key = rng.choices(keys, weights=weights)[0]
            fallback_by_key = defaultdict(list)
            for sample in backoff_candidates:
                if sample[0] == key[1]:
                    fallback_by_key[key].append(sample)
        else:
            keys = sorted(k for k in entry['base'] if k[0] == outcome_intent
                          and (k[1] != 'field_goal_attempt' or field_goal['eligible'])
                          and (outcome_intent != KICK_INTENT or fg_allowed_events is None
                               or k[1] in fg_allowed_events))
            if exact_outcome_rows is not None:
                exact_counts = Counter(sample[0] for sample in exact_outcome_rows)
                keys = [key for key in keys if exact_counts[key[1]]]
            if not keys and self.outcome_backoff_enabled and called_intent in SCRIMMAGE_INTENTS:
                raise e1.SamplingUnavailable(f'no_supported_outcome_for_intent:{outcome_intent}:{entry["key"]}')
            if not keys:
                raise e1.SamplingUnavailable(f'playcall_no_{outcome_intent}_outcomes_in_cell:{entry["key"]}')
            fallback_by_key = None
        labels_matched = []
        labels_unmatched = []
        formation_fallback = None
        coverage_fallback = None
        streak_fallback = None
        weights = []
        baseline_weights = []
        choice_base = kick_base if outcome_intent == KICK_INTENT else entry['base']  # kick_base is entry['base'] flag off
        if fallback_by_key is None:
            stage_values = defaultdict(list)
            for k in keys:
                base_weight = (exact_counts[k[1]] if exact_outcome_rows is not None else choice_base[k])
                baseline_weights.append(base_weight)
                weight = base_weight
                if use_formation:  # lifts multiply: formation and coverage are treated as independent given the outcome
                    weight *= self._lift(entry, k, formation, 'by_formation')
                stage_values['formation'].append(weight)
                if use_coverage:
                    weight *= self._lift(entry, k, coverage, 'by_coverage')
                stage_values['coverage'].append(weight)
                if use_streak:  # the league's outcome mix for this streak state, relative to the cell
                    weight *= self._lift(entry, k, streak_bucket, 'by_streak')
                stage_values['league_streak'].append(weight)
                if use_labels:  # the drawn labels' lifts, averaged in log space: the categories overlap, so they do not compound
                    weight *= decision_layer.geometric_mean([self._label_lift(entry, k, decision_layer.label_key(c, v))
                                                             for c, v in labels.items() if v is not None])
                stage_values['decision_labels'].append(weight)
                if self.team_outcomes is not None:  # team splits weight which outcome type is drawn within the intent
                    weight *= self._outcome_weight(k[1], offense, defense, entry['key'])
                stage_values['team_event_weights'].append(weight)
                if self.transition_strength is not None:
                    groups = self._entry_transition_groups(entry, k)
                    transition_total = self._transition_group_weight(groups, k[1], offense, defense)
                    weight *= transition_total / len(entry['by_key'][k])
                stage_values['transition_strength'].append(weight)
                if use_player_outcomes:
                    import player_outcomes
                    weight *= player_outcomes.event_weight(self.player_outcome_table, k[1], pre_event,
                                                           enabled_roles=self.player_outcome_roles)
                stage_values['player_event_weights'].append(weight)
                weights.append(weight)
            if self.trace_outcome_probabilities:
                base = baseline_weights
                probability_trace.append(_event_probability_stage(
                    'base_exact_cell' if exact_outcome_rows is None else 'base_exact_outcome_rows', keys, base))
                for stage_name in ('formation', 'coverage', 'league_streak', 'decision_labels',
                                   'team_event_weights', 'transition_strength', 'player_event_weights'):
                    active = ((stage_name == 'formation' and use_formation)
                              or (stage_name == 'coverage' and use_coverage)
                              or (stage_name == 'league_streak' and use_streak)
                              or (stage_name == 'decision_labels' and use_labels)
                              or (stage_name == 'team_event_weights' and self.team_outcomes is not None)
                              or (stage_name == 'transition_strength' and self.transition_strength is not None)
                              or (stage_name == 'player_event_weights' and use_player_outcomes))
                    if active:
                        probability_trace.append(_event_probability_stage(
                            stage_name, keys, stage_values[stage_name]))
            if weights and not any(weight > 0 for weight in weights):
                # Team/label/player outcome evidence may be sparse or conflicting. It may adjust
                # outcomes, but it must not make a legal, already-chosen intent impossible to sample.
                weights = baseline_weights
                outcome_weight_fallback = 'all_conditioned_weights_zero_within_selected_intent'
                if self.trace_outcome_probabilities:
                    probability_trace.append(_event_probability_stage('all_zero_weights_fallback', keys, weights))
        if (self.team_outcomes is None and self.transition_strength is None and not use_formation and not use_coverage and not use_streak and not use_labels
                and not use_player_outcomes):
            if fallback_by_key is None:
                key = rng.choices(keys, weights=[choice_base[k] for k in keys])[0]  # the unchanged baseline draw
        elif fallback_by_key is None:
            key = rng.choices(keys, weights=weights)[0]
        event_before_restore_sack_mass = key[1] if fallback_by_key is None else None
        if self.trace_outcome_probabilities and fallback_by_key is None:
            probability_trace.append(_event_probability_stage(
                'pre_postdraw_adjustment_event_draw', keys, weights if weights else baseline_weights))
            if 'restore_sack_mass' in self.blocker_fixes:
                total = float(sum(weights))
                before = {str(k[1]): (float(w) / total if total else 0.0)
                          for k, w in zip(keys, weights)}
                q = sack_substitution_rate(entry)
                incomplete = before.get('pass_incomplete', 0.0)
                before['sack'] = before.get('sack', 0.0) + incomplete * q
                before['pass_incomplete'] = incomplete * (1.0 - q)
                probability_trace.append({'stage': 'restore_sack_mass', 'substitution_probability': round(q, 8),
                                          'probabilities': {k: round(v, 8) for k, v in before.items()}})
            else:
                probability_trace.append(_event_probability_stage(
                    'final_event_draw', keys, weights if weights else baseline_weights))
        if ('restore_sack_mass' in self.blocker_fixes and key == (outcome_intent, 'pass_incomplete') and not scramble
                and fallback_by_key is None and (outcome_intent, 'sack') in entry['by_key']
                and rng.random() < sack_substitution_rate(entry)):
            # ablation A: an incomplete pass becomes a sack at the cell's q, so the cell's sack rate reaches its observed rate
            key = (outcome_intent, 'sack')
        candidates = fallback_by_key[key] if fallback_by_key is not None else entry['by_key'][key]
        candidate_source = candidates
        if self.transition_strength is not None:
            if backoff_transition_groups is not None:
                candidate_transition_groups = backoff_transition_groups[key[1]]
            else:
                candidate_transition_groups = self._entry_transition_groups(entry, key)
        if self.qb_decision_table is not None:
            if scramble and fallback_by_key is None:
                candidates = [c for c in candidates if c[1].get('qb_scramble') == 1]
                if not candidates:
                    raise e1.SamplingUnavailable(f'qb_scramble_source_rows_missing:{entry["key"]}')
            elif called_intent == 'run' and fallback_by_key is None:
                candidates = [c for c in candidates if c[1].get('qb_scramble') != 1]
                if not candidates:
                    raise e1.SamplingUnavailable(f'non_scramble_run_source_rows_missing:{entry["key"]}')
        if use_formation:
            matched = [c for c in candidates if c[1].get('formation', UNKNOWN) == formation]
            if matched:
                candidates = matched
            else:
                formation_fallback = 'no_source_rows_for_chosen_formation'
        if use_coverage:
            matched = [c for c in candidates if c[1].get('coverage', UNKNOWN) == coverage]
            if matched:
                candidates = matched
            else:
                coverage_fallback = 'no_source_rows_for_chosen_coverage'
        if use_streak:
            matched = [c for c in candidates if c[1].get('streak') == streak_bucket]
            if matched:
                candidates = matched
            else:
                streak_fallback = 'no_source_rows_for_current_streak'
        if use_labels and self.decision_filter:  # the row takes each drawn label in category order, where the cell has such a row
            for cat in decision_layer.CATS:
                value = labels.get(cat)
                if value is None:
                    continue
                matched = [c for c in candidates if (c[1].get('labels') or {}).get(cat) == value]
                if matched:
                    candidates = matched
                    labels_matched.append(cat)
                else:
                    labels_unmatched.append(cat)
        qb_target_role_conditioned = False
        qb_target_role_fallback = None
        if (self.qb_decision_table is not None and called_intent == 'dropback' and not scramble and qb_decision
                and key[1] in ('pass_complete', 'pass_incomplete', 'interception')):
            import qb_decisions
            target_role = qb_decision.get('target_role')
            matched = [c for c in candidates
                       if qb_decisions.row_target_role(self.qb_decision_table, c[1]) == target_role]
            if matched:
                candidates = matched
                qb_target_role_conditioned = True
            else:
                qb_target_role_fallback = 'no_target_identity_match_in_event_cell'
        exact_yardline_conditioned = False
        exact_yardline_fallback = None
        if self.exact_yardline and state.get('yl') is not None and int(state['yl']) <= 20:
            exact = [c for c in candidates if c[1].get('yardline_100') is not None and int(c[1]['yardline_100']) == int(state['yl'])]
            if exact:
                candidates = exact  # a touchdown flag then comes from the same distance the state is at
                exact_yardline_conditioned = True
            else:
                exact_yardline_fallback = 'no_source_rows_at_exact_yardline'
        row_weights = None
        if use_player_outcomes:
            import player_outcomes
            row_weights = [player_outcomes.row_weight(
                self.player_outcome_table, key[1], candidate[1], pre_event, state,
                enabled_roles=self.player_outcome_roles) for candidate in candidates]
        if self.transition_strength is not None:
            if candidates is not candidate_source:
                candidate_transition_groups = self._group_transition_rows(candidates, key[1])
            transition_keys = list(candidate_transition_groups)
            transition_weights = self._transition_group_weights(
                candidate_transition_groups, key[1], offense, defense)
            if row_weights is not None:
                weights_by_identity = {id(candidate): weight for candidate, weight in zip(candidates, row_weights)}
                transition_weights = [weight * sum(weights_by_identity[id(candidate)] for candidate in
                                                   candidate_transition_groups[transition]) /
                                      len(candidate_transition_groups[transition])
                                      for transition, weight in zip(transition_keys, transition_weights)]
            chosen_transition = rng.choices(transition_keys, weights=transition_weights, k=1)[0]
            eligible = candidate_transition_groups[chosen_transition]
            if row_weights is not None:
                event, row, runoff, spot = rng.choices(
                    eligible, weights=[weights_by_identity[id(candidate)] for candidate in eligible], k=1)[0]
            else:
                event, row, runoff, spot = rng.choice(eligible)
        elif row_weights is not None:
            event, row, runoff, spot = rng.choices(candidates, weights=row_weights, k=1)[0]
        else:
            event, row, runoff, spot = rng.choice(candidates)
        if pre_event is not None:
            row = dict(row, pre_event=pre_event)  # the chosen participants travel with the outcome; the row itself is not changed
        decision_record = {
            'participants': pe.ids(pre_event),
            'formation': formation, 'personnel': pre_event.get('personnel') if pre_event else None,
            'formation_conditioned': bool(use_formation), 'coverage': coverage, 'coverage_conditioned': bool(use_coverage),
            'exact_yardline_conditioned': exact_yardline_conditioned,
            'exact_yardline_fallback': exact_yardline_fallback,
            'formation_fallback': formation_fallback, 'coverage_fallback': coverage_fallback,
            'streak_fallback': streak_fallback,
            'streak_outcome_conditioned': bool(use_streak),
            'labels': labels, 'labels_conditioned': bool(use_labels), 'labels_matched': labels_matched,
            'labels_unmatched': labels_unmatched,
            'decision_row_filter_applied': bool(use_labels and self.decision_filter),
            'team_outcome_split': self.team_outcomes is not None,
            'team_outcome_fallbacks': list(self._current_team_outcome_fallbacks),
            'team_transition_split': self.transition_strength is not None,
            'team_transition_fallbacks': sorted(set(self._current_transition_fallbacks)),
            'split_fallbacks': split_fallbacks,
            'outcome_weight_fallback': outcome_weight_fallback,
            'point_split_applied': self.point_shifts is not None and team in self.layer.team_index,
            'team_streak_split_applied': self.streak_shifts is not None and team in self.current_streak,
            'league_streak_split_applied': self.streak_league is not None and team in self.current_streak,
            'qb_action': qb_decision.get('action') if qb_decision else None,
            'qb_scramble_probability': qb_decision.get('scramble_probability') if qb_decision else None,
            'qb_scramble_fallback': qb_decision.get('scramble_fallback') if qb_decision else None,
            'qb_run_role_style': (pre_event or {}).get('qb_run_role_style'),
            'qb_target_role': qb_decision.get('target_role') if qb_decision else None,
            'qb_target_role_probabilities': qb_decision.get('target_role_probabilities') if qb_decision else None,
            'qb_target_role_draw_fallback': qb_decision.get('target_role_fallback') if qb_decision else None,
            'qb_target_role_history_n': qb_decision.get('target_role_history_n') if qb_decision else None,
            'qb_target_role_conditioned': qb_target_role_conditioned,
            'qb_target_role_fallback': qb_target_role_fallback,
            'decision_timing': 'pre_outcome_sample',
            'field_goal_feasibility': field_goal,
            'player_outcomes_conditioned': use_player_outcomes,
            'player_outcome_roles': (list(player_outcomes.normalize_roles(self.player_outcome_roles))
                                     if use_player_outcomes else []),
            'player_outcome_support': self._player_support(pre_event) if use_player_outcomes else None,
            'state': {'quarter': int(state['quarter']), 'clock': int(state['clock']), 'down': int(state['down']),
                      'togo': int(state['togo']), 'yardline_100': int(state['yl']),
                      'score_diff': int(state['score_diff']), 'offense': offense, 'defense': defense, 'team': team},
            'component': ARTIFACT_ID, 'artifact_sha256': self.layer.artifact['sha256'],
            'score_clock_playcalling_applied': self.score_clock_playcalling_enabled,
            'call_policy_source': call_policy_source,
            'p_dropback': round(p, 6), 'point_shift': round(point_shift, 6), 'streak_shift': round(streak_shift, 6),
            'streak_bucket': self.current_streak.get(team), 'league_streak_shift': round(league_streak_shift, 6),
            'kick_share': round(kick_share, 6),
            'intent': called_intent, 'outcome_intent': outcome_intent, 'event': event,
            'fallback': fallback, 'source': {'game_id': row['game_id'], 'play_id': row['play_id'], 'season': row['season']},
            'source_row_filter_policy': ('exclude_unmodeled_lateral_transfers'
                                         if self.participant_chooser is not None else 'none'),
            'lateral_source_rows_excluded_from_situation_cell': entry['lateral_source_rows_excluded'],
            'lateral_source_rows_excluded_from_backoff_pool': (
                self._backoff_lateral_rows_excluded if backoff_candidates is not None else None),
        }
        if self.blocker_fixes:
            decision_record['blocker_fixes'] = sorted(self.blocker_fixes)
        if self.trace_outcome_probabilities:
            decision_record['outcome_probability_trace'] = {
                'path': 'sparse_backoff' if backoff_candidates is not None else 'exact_cell',
                'intent': called_intent, 'outcome_intent': outcome_intent,
                'call_policy_source': call_policy_source, 'p_dropback': round(p, 8),
                'kick_share': round(kick_share, 8),
                'qb_action': qb_decision.get('action') if qb_decision else None,
                'qb_scramble_probability': qb_decision.get('scramble_probability') if qb_decision else None,
                'qb_scramble_fallback': qb_decision.get('scramble_fallback') if qb_decision else None,
                'formation': formation, 'coverage': coverage, 'participants': pe.ids(pre_event),
                'source_fallback': outcome_fallback, 'zero_weight_fallback': outcome_weight_fallback,
                'event_selected': event, 'event_before_restore_sack_mass': event_before_restore_sack_mass,
                'stages': probability_trace,
                'not_applied_on_path': ([
                    {'layer': name, 'reason': 'sparse_backoff event normalization omits this exact-cell lift'}
                    for name, active in (('formation', use_formation), ('coverage', use_coverage),
                                         ('league_streak', use_streak), ('decision_labels', use_labels))
                    if backoff_candidates is not None and active]),
                'row_filters_after_event_draw': {
                    'formation': formation_fallback, 'coverage': coverage_fallback,
                    'streak': streak_fallback, 'labels_matched': labels_matched,
                    'labels_unmatched': labels_unmatched,
                    'qb_target_role': qb_target_role_conditioned,
                    'qb_target_role_fallback': qb_target_role_fallback,
                    'exact_yardline': exact_yardline_conditioned,
                    'exact_yardline_fallback': exact_yardline_fallback,
                    'description': 'These filter source rows after event selection; they do not change event-class probabilities.'},
            }
        if self.outcome_backoff_enabled:
            decision_record.update(
                outcome_class='qb_scramble' if scramble else called_intent,
                outcome_fallback=outcome_fallback,
                outcome_fallback_support_n=(len(backoff_candidates) if backoff_candidates is not None else
                                            len(exact_outcome_rows) if exact_outcome_rows is not None else None),
                outcome_fallback_ess=backoff_ess,
                scramble_fallback_level=qb_decision.get('scramble_fallback') if qb_decision else None,
                scramble_support_level=qb_decision.get('scramble_support_level') if qb_decision else None,
                scramble_fallback_support_n=qb_decision.get('scramble_fallback_support_n') if qb_decision else None,
                scramble_rejected_bounds=self._last_scramble_rejected_bounds if scramble else 0,
                scramble_eligible_candidates=(len(backoff_candidates) if backoff_candidates is not None else
                                              len(exact_outcome_rows) if scramble and exact_outcome_rows is not None else 0),
            )
        if fg_rule is not None:
            kicker = self.fg_kicker['kickers'].get(offense)
            decision_record.update(fg_rule=fg_rule, fg_kick_kernel_yards=kicker_field_goals.KERNEL_YARDS,
                                   fg_kicker=kicker, fg_kicker_logit_offset=self.fg_kicker['table'].offset(kicker)[0])
        if 'long_field_goal_feasibility' in self.blocker_fixes and fg_rule is not None:
            decision_record.update(
                fg_rejected_distance=fg_rejected_distance,
                fg_long_range_exception=False,
                fg_rejection_reason='beyond_record_attempt' if fg_rejected_distance else None,
                fg_fallback_level=None,
            )
        elif 'long_field_goal_feasibility' in self.blocker_fixes:
            decision_record.update(
                fg_rejected_distance=fg_rejected_distance,
                fg_long_range_exception=bool(fg_long_range_exception and event == 'field_goal_attempt'),
                fg_rejection_reason=('beyond_observed_maximum' if fg_rejected_distance and
                                     min(99, int(state['yl']) + 7) + 10 > float(
                                         self.field_goal_distance_model['max_observed_attempt_yards'])
                                     else 'beyond_ordinary_cutoff' if fg_rejected_distance else None),
                fg_fallback_level=None,
            )
        self.decisions.append(decision_record)
        return event, row, runoff, spot

    def _player_support(self, pre_event):
        import player_outcomes
        table = self.player_outcome_table
        return {role: player_outcomes.support(table, model_role, (pre_event.get(role) or {}).get('gsis_id'))
                for role, model_role in (('passer', 'qb'), ('receiver', 'receiver'), ('rusher', 'rusher'))
                if (pre_event and pre_event.get(role)
                    and model_role in player_outcomes.normalize_roles(self.player_outcome_roles))}

    def _field_goal_actions(self, entry, state):
        kick_events = {key[1] for key in entry['base'] if key[0] == KICK_INTENT}
        if 'field_goal_attempt' not in kick_events:
            return kick_events, False, False
        if self.fg_kicker is not None:  # research flag: the record ceiling only; the yard-line kernel sets the share
            import kicker_field_goals
            allowed = fg_feasibility.evaluate(int(state['yl']), rule=kicker_field_goals.RULE)['eligible']
            eligible = {event for event in kick_events if event != 'field_goal_attempt' or allowed}
            return eligible, not allowed, False
        distance = min(99, int(state['yl']) + 7) + 10
        model = getattr(self, 'field_goal_distance_model', None)
        maximum = float(model['max_observed_attempt_yards']) if model else 0.0
        ordinary = float(self.fg_ordinary_cutoff)
        end_window = int(state['quarter']) in (2, 4) and int(state['clock']) <= 60
        desperation = int(state['quarter']) == 4 and int(state['clock']) <= 300 and int(state['score_diff']) <= -8
        exception = end_window or desperation
        allowed = distance <= maximum and (distance <= ordinary or exception)
        eligible = {event for event in kick_events if event != 'field_goal_attempt' or allowed}
        return eligible, not allowed, bool(allowed and distance > ordinary)

    def _field_goal_probability_result(self, distance, rng, offense=None):
        import measure_kick_outcomes as mk
        if self.fg_kicker is not None:  # research flag: the league curve plus the offense's kicker offset
            import kicker_field_goals
            kicker = self.fg_kicker['kickers'][offense]
            offset, attempts = self.fg_kicker['table'].offset(kicker)
            distribution = kicker_field_goals.distribution(self.field_goal_distance_model, distance, offset)
            distribution.update(kicker=kicker, kicker_earlier_attempts=attempts,
                                fallback_level='kicker_logit_offset' if attempts else 'league_curve_no_kicker_history')
        else:
            distribution = mk.field_goal_distribution(self.field_goal_distance_model, distance)
        draw = rng.random()
        result = ('made' if draw < distribution['made'] else
                  'blocked' if draw < distribution['made'] + distribution['blocked'] else 'missed')
        return result, distribution

    def _label_lift(self, entry, key, value):
        """P(outcome type | label) over the labelled rows, divided by those rows' own share of the outcome, shrunk to that share.
        A cell with no labelled rows, or with no labelled row of this outcome, has no lift (1.0)."""
        base = entry['base_labelled']
        total = sum(base.values())
        if not total or not base[key]:
            return 1.0
        base_share = base[key] / total
        counts = entry['by_label'].get(value, Counter())
        n_value = sum(counts.values())
        conditional = (counts[key] + formation_layer.PRIOR_STRENGTH * base_share) / (n_value + formation_layer.PRIOR_STRENGTH)
        return conditional / base_share

    def _lift(self, entry, key, value, table):
        """P(outcome type | value) divided by the cell's own share, for this cell, shrunk to the cell with the layer's strength."""
        base_share = entry['base'][key] / sum(entry['base'].values())
        counts = entry[table].get(value, Counter())
        n_value = sum(counts.values())
        conditional = (counts[key] + formation_layer.PRIOR_STRENGTH * base_share) / (n_value + formation_layer.PRIOR_STRENGTH)
        return conditional / base_share

    def _outcome_weight(self, event, offense, defense, cell):
        """Offense and defense event ratios for this cell, multiplied. A team with no prior-season sample adds no effect."""
        weight = 1.0
        for side, label in (('offense', offense), ('defense', defense)):
            team = self._team(label)
            if team is None:
                continue
            try:
                before = getattr(self.team_outcomes, 'fallback_count', 0)
                weight *= self.team_outcomes.ratio(side, team, cell, event)
                if getattr(self.team_outcomes, 'fallback_count', 0) > before:
                    self._current_team_outcome_fallbacks.append(f'no_prior_cell_event:{side}:{team}:{event}')
            except ValueError:  # no prior-season sample for this team
                self._current_team_outcome_fallbacks.append(
                    f'no_prior_sample:{side}:{team}:{event}'
                )
                continue
        return weight

    def _group_transition_rows(self, candidates, event):
        import transition_strength as ts
        groups = defaultdict(list)
        for candidate in candidates:
            row = candidate[1]
            cell = e0.pool_key(int(row['down']), row['ydstogo'], row['yardline_100'])
            groups[(cell, ts.transition_key(event, row))].append(candidate)
        return dict(groups)

    def _entry_transition_groups(self, entry, key):
        cache = entry.setdefault('_team_transition_groups', {})
        if key not in cache:
            cache[key] = self._group_transition_rows(entry['by_key'][key], key[1])
        return cache[key]

    def _transition_group_weights(self, groups, event, offense, defense):
        weights = []
        for (cell, transition), candidates in groups.items():
            weight = len(candidates)
            for side, label in (('offense', offense), ('defense', defense)):
                team = self._team(label)
                if team is None:
                    continue
                before = self.transition_strength.fallback_count
                try:
                    weight *= self.transition_strength.ratio_key(side, team, cell, transition)
                except ValueError:
                    self._current_transition_fallbacks.append(f'no_prior_sample:{side}:{team}')
                    continue
                if self.transition_strength.fallback_count > before:
                    self._current_transition_fallbacks.append(
                        f'no_prior_transition:{side}:{team}:{event}')
            weights.append(weight)
        return weights

    def _transition_group_weight(self, groups, event, offense, defense):
        return sum(self._transition_group_weights(groups, event, offense, defense))

    def describe(self):
        out = {'component': ARTIFACT_ID, 'artifact_sha256': self.layer.artifact['sha256'],
               'frame_sha256': self.layer.artifact['frame_sha256'], 'side_teams': self.side_teams,
               'reference_season': self.layer.artifact['reference_season']}
        if self.blocker_fixes:
            out['blocker_resolution'] = {
                'enabled_fixes': sorted(self.blocker_fixes),
                'outcome_backoff_min_support': OUTCOME_BACKOFF_MIN_SUPPORT if self.outcome_backoff_enabled else None,
                'fg_ordinary_cutoff_yards': self.fg_ordinary_cutoff,
                'fg_distance_model': getattr(self, 'field_goal_distance_model', None),
                'scramble_bounds': self.scramble_bounds,
            }
            extra_files = ('measure_kick_outcomes.py', 'build_blocked_kick_outcomes.py', 'reducer.py')
            out['blocker_resolution']['integration_code_sha256'] = {
                name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in extra_files
            }
        if getattr(self, 'qb_decision_manifest', None) is not None:
            out['qb_decision_model'] = self.qb_decision_manifest
        if getattr(self, 'player_outcome_manifest', None) is not None:
            out['player_outcome_model'] = self.player_outcome_manifest
        if getattr(self, 'share_model_manifest', None) is not None:
            out['player_share_distribution'] = self.share_model_manifest
        if getattr(self, 'season_blend_manifest', None) is not None:
            out['season_blend'] = self.season_blend_manifest
        if getattr(self, 'qb_decision_manifest', None) is not None or getattr(self, 'player_outcome_manifest', None) is not None:
            integration_files = ('clock_d.py', 'e1_drive.py', 'e2_reference.py', 'game_state.py', 'game_stats.py', 'pre_event.py',
                                 'qb_decisions.py', 'player_outcomes.py', 'run_slc_game.py',
                                 'paired_random_streams.py', 'simulate_pregame_batch.py',
                                 'slc_engine.py', 'slc_playcall.py')
            out['integration_code_sha256'] = {
                name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in integration_files
            }
        return out


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
