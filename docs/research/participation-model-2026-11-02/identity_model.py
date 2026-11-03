#!/usr/bin/env python3
"""Player identity model: which individual enters or leaves at each snap (research).

The substitution models in candidate_substitution.py choose how many players of each class move, and draw the players
at random by rate. This module asks which player. For each snap where a class's on-field players change, it ranks the
candidates in that class with a conditional logit and checks the ranking against the observed players.

Entrants: candidates are the team's class-c players who are not on the field at the previous snap. Features:
  log share of the team's class-c snaps (prior season plus the current season's earlier weeks), returned-this-game flag,
  log snaps since last on the field this game, and was on the field in the team's previous game.
Leavers: candidates are the class-c players on the field at the previous snap. Features: log share, log stint,
  just-entered flag.

Every feature uses only games before the snap's game. Training is on 2022 to 2024 (candidate pool: players seen before
with that class). Evaluation is on 2025 (candidate pool: ACT players whose role before that week is class c, from
cutoff_individual_eval.role_maps). The weights come only from the training seasons.

Usage: python3 identity_model.py --tables <scrimmage_participation.csv.gz> --raw-dir <pinned nflverse dir> \
           --roster-weekly <roster_weekly_2025.csv.gz> --out <json>
"""
import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import candidate_substitution as cs  # noqa: E402
import cutoff_individual_eval as cie  # noqa: E402
import diagnose_substitution_gap as dg  # noqa: E402
import lineup_fit as lf  # noqa: E402
import participation_labels as pl  # noqa: E402
import participation_field as pf  # noqa: E402
import participation_model as pm  # noqa: E402
import availability_gate_check as agc  # noqa: E402

CLASSES = pf.SKILL_CLASSES
EPS = 1e-3
ENTRANT_FEATURES = ('log_share', 'returned', 'log_gap', 'prev_game')
LEAVER_FEATURES = ('log_share', 'log_stint', 'just_entered')


def fit_logit(events, n_features, iterations=200, lr=2.0):
    """Conditional logit. events: list of (candidate feature rows, chosen indices). Returns weights."""
    theta = [0.0] * n_features
    total = sum(len(chosen) for _x, chosen in events) or 1
    for _ in range(iterations):
        grad = [0.0] * n_features
        for xs, chosen in events:
            scores = [sum(t * v for t, v in zip(theta, x)) for x in xs]
            m = max(scores)
            weights = [math.exp(s - m) for s in scores]
            z = sum(weights)
            probs = [w / z for w in weights]
            for j in chosen:  # each chosen player is one choice from the same candidate set
                for d in range(n_features):
                    grad[d] += xs[j][d] - sum(p * x[d] for p, x in zip(probs, xs))
        theta = [t + lr * g / total for t, g in zip(theta, grad)]
    return theta


def loglik(theta, events):
    total, n = 0.0, 0
    for xs, chosen in events:
        scores = [sum(t * v for t, v in zip(theta, x)) for x in xs]
        m = max(scores)
        logz = m + math.log(sum(math.exp(s - m) for s in scores))
        for j in chosen:
            total += scores[j] - logz
            n += 1
    return total / max(n, 1)


def topk_hits(scores, chosen):
    """How many chosen candidates fall in the top k by score, where k is the number chosen."""
    k = len(chosen)
    order = sorted(range(len(scores)), key=lambda j: (-scores[j], j))
    top = set(order[:k])
    return len(top & set(chosen)), top == set(chosen), k


def build_events(seqs, week_of, roles, act, pool_fn, share_fn, prev_game_fn, training, cutoff_pool_log):
    """Entrant and leaver events. Each event: (kind, class, candidates [{pid, x, baselines}], chosen indices)."""
    events = []
    for key, seq in sorted(seqs.items()):
        season, _game, team = key
        week = week_of[key]
        ids = [frozenset(pid for pid, _ in skill) for _g, _c, skill in seq]
        cls_at = [dict(skill) for _g, _c, skill in seq]
        stints = dg.stint_track(ids)
        last_on = {}
        prev_game = prev_game_fn(key)
        for i in range(1, len(seq)):
            prev, cur = ids[i - 1], ids[i]
            for pid in prev:
                last_on[pid] = i - 1
            for c in CLASSES:
                entrants = {p for p in cur - prev if cls_at[i].get(p) == c}
                if entrants:
                    pool = pool_fn(key, week, team, c, prev, training)
                    cutoff_pool_log['entrants'] += len(entrants)
                    if not entrants <= pool:  # an entrant the candidate pool cannot reach is counted, never added to it
                        cutoff_pool_log['entrants_outside_pool'] += len(entrants - pool)
                    cands, xs, base = [], [], []
                    for pid in sorted(pool):
                        share = share_fn(key, pid, c)
                        returned = pid in last_on and pid not in prev
                        gap = (i - 1 - last_on[pid] + 1) if returned else 0
                        x = [math.log(share + EPS), 1.0 if returned else 0.0, math.log(1 + gap) if returned else 0.0,
                             1.0 if pid in prev_game else 0.0]
                        cands.append(pid)
                        xs.append(x)
                        base.append({'recency': -gap if returned else -1e9, 'share': share})
                    chosen = [cands.index(p) for p in sorted(entrants) if p in cands]
                    events.append(('entrant', c, cands, xs, base, chosen))
                leavers = {p for p in prev - cur if cls_at[i - 1].get(p) == c}
                if leavers:
                    cands_prev = sorted(p for p in prev if cls_at[i - 1].get(p) == c)
                    xs, base = [], []
                    for pid in cands_prev:
                        share = share_fn(key, pid, c)
                        stint = stints[i - 1][pid]
                        xs.append([math.log(share + EPS), math.log(stint), 1.0 if stint == 1 else 0.0])
                        base.append({'stint': stint, 'share': share})
                    chosen = [cands_prev.index(p) for p in sorted(leavers)]
                    events.append(('leaver', c, cands_prev, xs, base, chosen))
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', type=Path, required=True)
    ap.add_argument('--raw-dir', type=Path, required=True)
    ap.add_argument('--roster-weekly', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()

    positions = pm.load_positions(args.raw_dir)
    fit_rows = pm.load_scrimmage(args.tables, cs.FIT_SEASONS)
    rows = pm.load_scrimmage(args.tables, cs.HOLDOUT)
    all_rows = fit_rows + rows
    seqs = lf.sequences(all_rows, positions, snap_labels=True)
    week_of = {(int(r['season']), r['game_id'], r['posteam']): int(r['week']) for r in all_rows}

    # Cumulative class counts before each game, within its season, plus the whole previous season.
    game_counts = {}
    for key, seq in seqs.items():
        counts = Counter()
        for _g, _c, skill in seq:
            for pid, c in skill:
                counts[(pid, c)] += 1
        game_counts[key] = counts
    season_totals = defaultdict(Counter)  # (season, team) -> Counter of class snaps
    season_players = defaultdict(Counter)  # (season, team) -> Counter of (pid, class) snaps
    for key, counts in game_counts.items():
        season, _g, team = key
        for (pid, c), n in counts.items():
            season_players[(season, team)][(pid, c)] += n
            season_totals[(season, team)][c] += n

    before = {}  # key -> (Counter of (pid, class) before the game, Counter of class totals before the game)
    for (season, team) in {(k[0], k[2]) for k in seqs}:
        games = sorted((week_of[k], k) for k in seqs if k[0] == season and k[2] == team)
        cum, tot = Counter(), Counter()
        for _w, k in games:
            before[k] = (Counter(cum), Counter(tot))
            cum.update(game_counts[k])
            for (pid, c), n in game_counts[k].items():
                tot[c] += n

    def share_fn(key, pid, c):
        season, _g, team = key
        cum, tot = before[key]
        prev_season = (season - 1, team)
        prev_players = season_players.get(prev_season, Counter())
        prev_totals = season_totals.get(prev_season, Counter())
        num = cum[(pid, c)] + prev_players[(pid, c)]
        den = tot[c] + prev_totals[c]
        return num / den if den else 0.0

    teams_order = sorted({(k[2], k[0], week_of[k], k) for k in seqs})
    prev_game_of = {}
    last_by_team = {}
    for team, season, _w, key in teams_order:
        prev_game_of[key] = last_by_team.get(team, set())
        last_by_team[team] = set(pid for pid, _ in [s for _g, _c, skill in seqs[key] for s in skill])

    def prev_game_fn(key):
        return prev_game_of[key]

    # Holdout roles and ACT pool, built from the cutoff-safe role maps.
    prior_counts = defaultdict(Counter)
    for row in fit_rows:
        if int(row['season']) == max(cs.FIT_SEASONS):
            for pid, label, _source in pl.aligned_labels(row):
                if label in lf.SKILL:
                    prior_counts[pid][label] += 1
    snap_evidence = []
    for row in rows:
        for pid, label, _source in pl.aligned_labels(row):
            if label in lf.SKILL:
                snap_evidence.append((int(row['week']), pid, label))
    roster_rows = cie.roster_evidence(args.roster_weekly)
    weeks = sorted({int(r['week']) for r in rows})
    roles = cie.role_maps(prior_counts, snap_evidence, roster_rows, weeks)
    act = defaultdict(set)
    for w, pid, team, status, _pos in roster_rows:
        if status == 'ACT':
            act[(w, team)].add(pid)

    def pool_fn(key, week, team, c, prev, training):
        if training:  # players seen with this class before this game, in the prior season or earlier this season
            season = key[0]
            cum, _tot = before[key]
            seen = {pid for (pid, cc), n in cum.items() if cc == c and n > 0}
            seen |= {pid for (pid, cc), n in season_players.get((season - 1, team), Counter()).items()
                     if cc == c and n > 0}
            return seen - prev
        role = roles[week]
        return {pid for pid in act[(week, team)] if pid in role and pf.SKILL[role[pid][0]] == c} - prev

    fit_seqs = {k: v for k, v in seqs.items() if k[0] in cs.FIT_SEASONS}
    hold_seqs = {k: v for k, v in seqs.items() if k[0] in cs.HOLDOUT}
    log_train, log_test = Counter(), Counter()
    train_events = build_events(fit_seqs, week_of, roles, act, pool_fn, share_fn, prev_game_fn, True, log_train)
    test_events = build_events(hold_seqs, week_of, roles, act, pool_fn, share_fn, prev_game_fn, False, log_test)

    result = {'fit_seasons': sorted(cs.FIT_SEASONS), 'holdout': sorted(cs.HOLDOUT),
              'leakage_check': 'share, returned, gap and previous-game features use only earlier games; '
                               'holdout roles are cutoff-safe; players.csv unused',
              'pool_coverage': {'train': dict(log_train), 'holdout': dict(log_test)}, 'kinds': {}}
    for kind, names, n_feat in (('entrant', ENTRANT_FEATURES, 4), ('leaver', LEAVER_FEATURES, 3)):
        # every 4th training event keeps the pure-Python fit to minutes; the holdout is scored in full
        train = [(e[3], e[5]) for i, e in enumerate(e for e in train_events if e[0] == kind and e[5]) if i % 4 == 0]
        theta = fit_logit(train, n_feat)
        test = [e for e in test_events if e[0] == kind and e[5]]
        per_class = {}
        totals = Counter()
        for c in CLASSES:
            sub = [e for e in test if e[1] == c]
            agg = Counter()
            for _k, _c, cands, xs, base, chosen in sub:
                scores = [sum(t * v for t, v in zip(theta, x)) for x in xs]
                hits, exact, k = topk_hits(scores, chosen)
                agg['events'] += 1
                agg['chosen'] += k
                agg['model_hits'] += hits
                agg['model_exact'] += int(exact)
                if kind == 'entrant':
                    for name, sc in (('recency', [b['recency'] for b in base]), ('share', [b['share'] for b in base])):
                        h, ex, _ = topk_hits(sc, chosen)
                        agg[f'{name}_hits'] += h
                        agg[f'{name}_exact'] += int(ex)
                    agg['random_hits'] += k * k / len(cands)
                else:
                    for name, sc in (('shortest_stint', [-b['stint'] for b in base]),
                                     ('lowest_share', [-b['share'] for b in base])):
                        h, ex, _ = topk_hits(sc, chosen)
                        agg[f'{name}_hits'] += h
                        agg[f'{name}_exact'] += int(ex)
                    agg['random_hits'] += k * k / len(cands)
            per_class[c] = {m: v for m, v in agg.items()}
            totals.update(agg)
        names_out = [name for name in totals if name.endswith('_hits') or name.endswith('_exact')]
        result['kinds'][kind] = {
            'features': list(names), 'weights': [round(t, 4) for t in theta],
            'train_loglik_per_choice': round(loglik(theta, train[:20000]), 4),
            'holdout': {'events': totals['events'], 'chosen': totals['chosen'],
                        'recall': {m[:-5]: round(totals[m] / max(totals['chosen'], 1), 4)
                                   for m in names_out if m.endswith('_hits')},
                        'exact_set_rate': {m[:-6]: round(totals[m] / max(totals['events'], 1), 4)
                                           for m in names_out if m.endswith('_exact')},
                        'per_class': per_class}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({k: {'recall': v['holdout']['recall'], 'exact': v['holdout']['exact_set_rate'],
                          'events': v['holdout']['events']} for k, v in result['kinds'].items()}, sort_keys=True))


if __name__ == '__main__':
    main()
