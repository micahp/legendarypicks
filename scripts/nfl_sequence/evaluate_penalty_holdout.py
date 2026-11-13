#!/usr/bin/env python3
"""Score a chronological penalty holdout by phase and probability model."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from penalty_fit import CATALOG, NO_FOUL, PenaltyModel
from penalty_train import opportunities_jsonl


def evaluate(rows, predictor):
    stats = defaultdict(lambda: {'n': 0, 'observed_fouls': 0, 'predicted_fouls': 0.,
                                 'log_loss': 0., 'multiclass_brier': 0., 'any_foul_brier': 0.})
    for row in rows:
        probs = predictor(row.context)
        for group in ('all', row.context.phase):
            out = stats[group]; out['n'] += 1
            actual = int(row.outcome != NO_FOUL); forecast = 1 - probs[NO_FOUL]
            out['observed_fouls'] += actual; out['predicted_fouls'] += forecast
            out['log_loss'] -= math.log(max(probs[row.outcome], 1e-15))
            out['multiclass_brier'] += sum((p - int(label == row.outcome))**2 for label, p in probs.items())
            out['any_foul_brier'] += (forecast - actual)**2
    for out in stats.values():
        n = out['n']; out['observed_rate'] = out['observed_fouls'] / n
        out['predicted_rate'] = out['predicted_fouls'] / n
        for key in ('log_loss', 'multiclass_brier', 'any_foul_brier'):
            out[key] /= n
    return dict(stats)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train', type=Path, required=True)
    parser.add_argument('--holdout', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    team = PenaltyModel.from_json(args.model.read_text())
    context = PenaltyModel(train_before_utc=team.train_before_utc, source_sha256=team.source_sha256,
                           context_strength=team.context_strength, team_strength=team.team_strength,
                           team_effects=False).fit(opportunities_jsonl(args.train))
    rows = list(opportunities_jsonl(args.holdout))
    # Validate held-out chronology, labels and categories before custom scoring.
    team.score(rows)
    def league(ctx):
        counts = context.context_counts[ctx.keys()[0]]
        labels = CATALOG[ctx.phase]
        denominator = sum(counts.values()) + len(labels)
        return {key: (counts[key] + 1.) / denominator for key in labels}
    result = {'league': evaluate(rows, league), 'context_only': evaluate(rows, context.predict),
              'team_adjusted': evaluate(rows, team.predict)}
    with args.out.open('x') as out:
        out.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, indent=2, sort_keys=True))

if __name__ == '__main__':
    main()
