"""Fitted, cutoff-safe play-call table: a hierarchical distribution over formal calls, by team and situation (SLC v2, research).

A formal offensive call is decided in four steps, and each step is conditioned on the ones before it:

    P  personnel code           from the team and the situation
    F  formation                from the team, the situation and P          (2023 onward; the 2022 label is unreliable)
    R  play family, run or pass from the team, the situation, P and F
    C  concept                  run gap, or pass depth and location, from the family and P

Special-teams plays (a fake punt is a run with punt-team personnel) get their own personnel category, SPECIAL, and no further
steps. Kneels, spikes and no-plays are not calls and are excluded from the call data.

Each step is a hierarchical smoothed distribution. A context with few plays is pulled toward a broader context, and the
broadest context is the league. A prediction is a fallback when its finest context had no training plays. The smoothing
constant K is fixed before any evaluation and is not tuned.

Only seasons before the forecast season are used to fit, so each evaluation is out of sample in time. The concept step uses
only the play-by-play run gap and pass depth and location, which the historical records identify. The 2025 route and
protection labels in the detailed playbook files are not used for fitting and are kept apart.
"""
import math
import random
from collections import Counter, defaultdict

import formal_playcall as fp

K = 20.0  # pseudo-plays of the parent distribution. Fixed in advance, not tuned.
MIN_SUPPORT = 5  # a joint call with fewer training plays than this is not legal
FORMATION_FIRST_SEASON = 2023  # the 2022 formation labels use another vocabulary and are blank on 41 percent of plays
NA = 'NA'  # a feature that is not known or not trained: it is a context value of its own, never a real label
OTHER = 'OTHER'  # the catch-all outcome for a category the training data never saw

# Context specifications, from the finest to the coarsest. A specification lists the features it conditions on. 'team' is the
# offense. The situation is down, dist (distance), field, score and time.
SPEC = {
    # A team context keeps the situation it is in. Each team context backs off to the league context with the same
    # situation, never to a team average over all situations, which would wash out the situation.
    'P': [('team', 'down', 'dist', 'field', 'score', 'time'), ('team', 'down', 'dist', 'field'), ('team', 'down', 'dist'),
          ('down', 'dist', 'field', 'score', 'time'), ('down', 'dist', 'field'), ('down', 'dist'), ()],
    'P_league': [('down', 'dist', 'field', 'score', 'time'), ('down', 'dist', 'field'), ('down', 'dist'), ()],
    'F': [('team', 'P', 'down', 'dist'), ('team', 'P'), ('P', 'down', 'dist'), ('P',), ()],
    'F_league': [('P', 'down', 'dist'), ('P',), ()],
    'R': [('team', 'P', 'F', 'down', 'dist', 'field', 'score', 'time'), ('team', 'P', 'F', 'down', 'dist'),
          ('team', 'P', 'F'), ('P', 'F', 'down', 'dist'), ('P', 'F'), ()],
    'R_league': [('P', 'F', 'down', 'dist', 'field', 'score', 'time'), ('P', 'F', 'down', 'dist'), ('P', 'F'), ()],
    'C': [('team', 'R', 'P', 'down', 'dist'), ('team', 'R', 'P'), ('R', 'P', 'down', 'dist'), ('R', 'P'), ()],
    'C_league': [('R', 'P', 'down', 'dist'), ('R', 'P'), ()],
    # the family only, for comparison with PlayCallLayer, which has no personnel or formation input
    'R0': [('team', 'down', 'dist', 'field', 'score', 'time'), ('team', 'down', 'dist', 'field'), ('team', 'down', 'dist'),
           ('down', 'dist', 'field', 'score', 'time'), ('down', 'dist', 'field'), ('down', 'dist'), ()],
    'R0_league': [('down', 'dist', 'field', 'score', 'time'), ('down', 'dist', 'field'), ('down', 'dist'), ()],
    # the team rate with no situation: the simpler baseline the table must beat
    'P_rate': [('team',), ()],
    'F_rate': [('team', 'P'), ('P',), ()],
    'R_rate': [('team', 'P', 'F'), ('P', 'F'), ()],
    'C_rate': [('team', 'R', 'P'), ('R', 'P'), ()],
}
# which spec each step uses, per model
MODEL_SPECS = {
    'table': {'P': 'P', 'F': 'F', 'R': 'R', 'C': 'C'},
    'league': {'P': 'P_league', 'F': 'F_league', 'R': 'R_league', 'C': 'C_league'},
    'rate': {'P': 'P_rate', 'F': 'F_rate', 'R': 'R_rate', 'C': 'C_rate'},
    'family_only': {'R': 'R0'},
    'family_only_league': {'R': 'R0_league'},
}


def bucket_down(down):
    return str(down) if str(down) in ('1', '2', '3', '4') else 'UNK'


def bucket_dist(togo):
    try:
        y = int(float(togo))
    except ValueError:
        return 'UNK'
    if y <= 3:
        return '1-3'
    if y <= 6:
        return '4-6'
    if y <= 9:
        return '7-9'
    if y == 10:
        return '10'
    return '11+'


def bucket_field(yardline_100):
    try:
        y = int(float(yardline_100))
    except ValueError:
        return 'UNK'
    for hi, name in ((10, '1-10'), (20, '11-20'), (35, '21-35'), (50, '36-50'), (65, '51-65'), (80, '66-80')):
        if y <= hi:
            return name
    return '81-99'


def bucket_score(diff):
    try:
        d = int(float(diff))
    except ValueError:
        return 'UNK'
    if d <= -9:
        return '<=-9'
    for lo, hi, name in ((-8, -4, '-8..-4'), (-3, -1, '-3..-1'), (0, 0, '0'), (1, 3, '1..3'), (4, 8, '4..8')):
        if lo <= d <= hi:
            return name
    return '>=9'


def bucket_time(qtr, half_seconds):
    q = str(qtr)
    if q == '5':
        return 'ot'
    if q in ('2', '4'):
        try:
            if int(float(half_seconds)) <= 120:
                return 'two_min'
        except ValueError:
            pass
    return {'1': 'q1', '2': 'q2', '3': 'q3', '4': 'q4'}.get(q, 'UNK')


def concept_of(family, run_gap, pass_length, pass_location):
    if family == 'run':
        return f'run|{run_gap or fp.UNKNOWN}'
    return f'pass|{pass_length or fp.UNKNOWN}|{pass_location or fp.UNKNOWN}'


def records(raw_dir, seasons):
    """(records, excluded). One record per offensive call (run or pass) and one per special-teams play, from the joined
    nflverse release. excluded counts the run and pass plays left out, by reason, so none is dropped silently."""
    out = []
    excluded = Counter()
    for season in seasons:
        for row in fp.load_season(raw_dir, season):
            if row['play_type'] not in ('run', 'pass'):
                excluded[f'not_a_call:{row["play_type"] or "blank"}'] += 1
                continue  # kneels, spikes, no-plays and kicks are not calls
            code = row['personnel_code']
            if code.startswith(fp.INVALID) or code == fp.UNKNOWN:
                excluded[f'{season}:{code.split(":")[0]}'] += 1
                continue
            if code.startswith(fp.SPECIAL):
                p, family = 'SPECIAL', None
            else:
                p, family = code, row['play_type']
            if season < FORMATION_FIRST_SEASON:
                formation = NA
            else:
                formation = fp.formation_key(row['formation'])
            rec = {
                'season': season, 'game_id': row['game_id'], 'play_id': row['play_id'], 'team': row['posteam'],
                'defteam': row['defteam'], 'down': bucket_down(row['down']), 'dist': bucket_dist(row['ydstogo']),
                'field': bucket_field(row['yardline_100']), 'score': bucket_score(row['score_differential']),
                'time': bucket_time(row['qtr'], row['half_seconds_remaining']), 'P': p, 'F': formation,
                'R': family or NA, 'C': NA, 'reconstructed': row['personnel_reconstructed'],
            }
            rec.update({'raw_down': row['down'], 'raw_togo': row['ydstogo'], 'raw_yl': row['yardline_100'],
                        'raw_score': row['score_differential'], 'raw_qtr': row['qtr'],
                        'raw_qsec': row['quarter_seconds_remaining']})
            if family is not None:
                rec['C'] = concept_of(family, row['run_gap'], row['pass_length'], row['pass_location'])
            out.append(rec)
    return out, excluded


def _context(feats, names):
    return tuple(feats.get(name, NA) for name in names)


class Table:
    """Counts by spec and context, and the smoothed distribution read from them.

    Counts are keyed by the spec name, so two specs that share a level never share a count. Categories are kept per decision
    level, so a level's outcome set is the same in every spec that predicts it."""

    def __init__(self):
        self.counts = defaultdict(Counter)  # (spec name, index, context) -> Counter of outcomes
        self.categories = defaultdict(set)  # decision level -> outcomes seen in training
        self.has_formation = False

    def add(self, level, spec, feats, outcome):
        self.categories[level].add(outcome)
        for i, names in enumerate(SPEC[spec]):
            self.counts[(spec, i, _context(feats, names))][outcome] += 1

    def categories_of(self, level):
        return sorted(self.categories[level]) + [OTHER]

    def dist(self, level, spec, feats):
        """(probabilities over categories, finest context index with data or None). An index above zero, or None, is a fallback."""
        cats = self.categories_of(level)
        p = {c: 1.0 / len(cats) for c in cats}
        finest = None
        for i in reversed(range(len(SPEC[spec]))):
            cnt = self.counts.get((spec, i, _context(feats, SPEC[spec][i])))
            n = sum(cnt.values()) if cnt else 0
            if n:
                for c in cats:
                    p[c] = (cnt.get(c, 0) + K * p[c]) / (n + K)
                finest = i
        return p, finest


def fit(train):
    """A table fitted on the training records. Formation is learned only when some training record has a formation label."""
    table = Table()
    table.has_formation = any(r['F'] not in (NA, fp.UNKNOWN) for r in train)
    for r in train:
        feats = dict(r, F=r['F'] if table.has_formation else NA)
        if r['P'] == 'SPECIAL':
            table.add('P', 'P', feats, 'SPECIAL')
            table.add('P', 'P_league', feats, 'SPECIAL')
            continue
        table.add('P', 'P', feats, r['P'])
        table.add('P', 'P_league', feats, r['P'])
        table.add('P', 'P_rate', feats, r['P'])
        if table.has_formation and r['F'] != NA:
            table.add('F', 'F', feats, r['F'])
            table.add('F', 'F_league', feats, r['F'])
            table.add('F', 'F_rate', feats, r['F'])
        table.add('R', 'R', feats, r['R'])
        table.add('R', 'R_league', feats, r['R'])
        table.add('R', 'R_rate', feats, r['R'])
        table.add('R', 'R0', feats, r['R'])
        table.add('R', 'R0_league', feats, r['R'])
        table.add('C', 'C', feats, r['C'])
        table.add('C', 'C_league', feats, r['C'])
        table.add('C', 'C_rate', feats, r['C'])
    return table


def model_features(table, r, team_aware=True):
    """The record's features as the table sees them. Formation is NA when the table learned none, and the team is NA for a
    league-only model."""
    feats = dict(r, F=r['F'] if table.has_formation else NA)
    if not team_aware:
        feats['team'] = NA
    return feats


def _fb(outcome, dist):
    return outcome if outcome in dist else OTHER


def score_record(table, r, model='table'):
    """Conditional log loss of each step for one record, and whether each step fell back. A special-teams record has only P.

    Steps are conditioned on the record's own earlier steps, so the sum of the step losses is the joint log loss."""
    specs = MODEL_SPECS[model]
    team_aware = model in ('table', 'rate', 'family_only')
    feats = model_features(table, r, team_aware)
    out = {'fallback': {}, 'loss': {}}
    if 'P' in specs:
        p, finest = table.dist('P', specs['P'], feats)
        out['loss']['P'] = -math.log(p[_fb(r['P'], p)])
        out['fallback']['P'] = finest != 0
        if r['P'] == 'SPECIAL':
            return out
        feats = dict(feats, P=r['P'])
    if 'F' in specs and table.has_formation and r['F'] != NA:
        p, finest = table.dist('F', specs['F'], feats)
        out['loss']['F'] = -math.log(p[_fb(r['F'], p)])
        out['fallback']['F'] = finest != 0
        feats = dict(feats, F=r['F'])
    p, finest = table.dist('R', specs['R'], feats)
    out['loss']['R'] = -math.log(p[_fb(r['R'], p)])
    out['fallback']['R'] = finest != 0
    out['pass_prob'] = p.get('pass', 0.0)
    if 'C' in specs:
        feats = dict(feats, R=r['R'])
        p, finest = table.dist('C', specs['C'], feats)
        out['loss']['C'] = -math.log(p[_fb(r['C'], p)])
        out['fallback']['C'] = finest != 0
    return out


def _draw(dist, rng):
    x = rng.random()
    acc = 0.0
    keys = sorted(dist)
    for k in keys:
        acc += dist[k]
        if x < acc:
            return k
    return keys[-1]


class Support:
    """Training plays per partial call, for the compatibility mask. A step's outcome is allowed only when the league has run
    the call up to that step at least MIN_SUPPORT times, so a sampled call is one the league has actually made."""

    def __init__(self, train):
        self.by_p = Counter()
        self.by_pf = Counter()
        self.by_pfr = Counter()
        self.by_pfrc = Counter()
        self.has_formation = any(r['F'] not in (NA, fp.UNKNOWN) for r in train)
        for r in train:
            if r['P'] == 'SPECIAL' or r['R'] == NA:
                continue
            f = r['F'] if self.has_formation else NA
            self.by_p[r['P']] += 1
            self.by_pf[(r['P'], f)] += 1
            self.by_pfr[(r['P'], f, r['R'])] += 1
            self.by_pfrc[(r['P'], f, r['R'], r['C'])] += 1
        self.masked = Counter()  # steps where no outcome could be kept, which must stay zero for a legal draw
        # A prefix is extendable when some complete call through it has MIN_SUPPORT plays. A step keeps only extendable
        # outcomes, so a draw never reaches a step with no legal completion.
        self.complete = {k: v for k, v in self.by_pfrc.items() if v >= MIN_SUPPORT}
        self.extendable = {'P': {(k[0],) for k in self.complete}, 'F': {(k[0], k[1]) for k in self.complete},
                           'R': {(k[0], k[1], k[2]) for k in self.complete}}

    def allowed(self, step, dist, prefix):
        """Keep the outcomes that stay legal after this prefix: a supported outcome, or one that extends to a supported call."""
        keep = {}
        for k, v in dist.items():
            if k == OTHER:
                continue
            if step == 'C':
                ok = self.complete.get(prefix + (k,), 0) >= MIN_SUPPORT
            else:
                ok = prefix + (k,) in self.extendable[step]
            if ok:
                keep[k] = v
        if not keep:
            self.masked[step] += 1
            return {k: 0.0 for k in dist}  # no legal outcome: the caller must see this, and it is counted
        total = sum(keep.values())
        return {k: v / total for k, v in keep.items()}


def sample_call(table, team, situation, rng, model='table', support=None):
    """One formal call drawn step by step, each step conditioned on the steps before it. With a Support, each step is masked to
    the outcomes the league has run with the call so far, so the sampled call is compatible with its personnel and formation."""
    specs = MODEL_SPECS[model]
    team_aware = model in ('table', 'rate', 'family_only')
    feats = {'team': team if team_aware else NA, 'F': NA, **situation}
    call = {}
    if 'P' in specs:
        p, _f = table.dist('P', specs['P'], feats)
        if support is not None:
            p = support.allowed('P', p, ())
        call['P'] = _draw(p, rng)
        if call['P'] == 'SPECIAL':
            return call
        feats['P'] = call['P']
    if 'F' in specs and table.has_formation:
        p, _f = table.dist('F', specs['F'], feats)
        if support is not None:
            p = support.allowed('F', p, (call['P'],))
        call['F'] = _draw(p, rng)
        feats['F'] = call['F']
    prefix_r = (call['P'], feats.get('F', NA))
    p, _f = table.dist('R', specs['R'], feats)
    if support is not None:
        p = support.allowed('R', p, prefix_r)
    call['R'] = _draw(p, rng)
    if 'C' in specs:
        feats['R'] = call['R']
        p, _f = table.dist('C', specs['C'], feats)
        if support is not None:
            p = support.allowed('C', p, prefix_r + (call['R'],))
        call['C'] = _draw(p, rng)
    return call


def is_legal(support, call):
    """A sampled call is legal when every step it took had league support, and its joint call has at least MIN_SUPPORT plays."""
    if 'R' not in call:
        return call.get('P') == 'SPECIAL'
    f = call.get('F', NA)
    if support.has_formation and 'F' not in call:
        return False
    if support.by_pfrc.get((call['P'], f, call['R'], call.get('C')), 0) < MIN_SUPPORT:
        return False
    return True


def rng_for(seed_text):
    return random.Random(seed_text)
