"""Chronological held-out check of the two-point decision: Brier score and log loss on actual regular-season tries.

Two folds, each fit on earlier seasons only: fit 2022-2023 and test 2024, then fit 2022-2024 and test 2025. The outcome is the
decision: 1 if the team went for two, 0 for the extra point. Reads the committed situation fixture. Usage:
python3 evaluate_try_policy.py
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import try_policy as tp  # noqa: E402

FOLDS = [((2022, 2023), 2024), ((2022, 2023, 2024), 2025)]
MODELS = [
    ('constant league rate', 'constant', 25),
    ('margin x period', 'margin_period', 25),
    ('candidate: margin x period x opening, K=25', 'margin_period_opening', 25),
    ('margin x period x first TD, K=25', 'margin_period_first_td', 25),
    ('margin x period x opening x first TD, K=25', 'margin_period_opening_first_td', 25),
    ('candidate, K=5', 'margin_period_opening', 5),
    ('candidate, K=10', 'margin_period_opening', 10),
    ('candidate, K=50', 'margin_period_opening', 50),
    ('candidate, K=100', 'margin_period_opening', 100),
]


def score(policy, rows):
    brier = logloss = prob = 0.0
    for r in rows:
        p = policy.p_two(r['margin'], r['qtr'], r['clock'], r['opening_drive'], r['first_td'])
        y = r['two']
        brier += (p - y) ** 2
        logloss -= y * math.log(p) + (1 - y) * math.log(1 - p)
        prob += p
    n = len(rows)
    return brier / n, logloss / n, prob / n


def main():
    rows, _ = tp.load_rows()
    rows = [r for r in rows if r['season_type'] == 'REG']
    for train_seasons, test_season in FOLDS:
        train = [r for r in rows if r['season'] in train_seasons]
        test = [r for r in rows if r['season'] == test_season]
        opening = [r for r in test if r['opening_drive'] == 1]
        print(f'fit {train_seasons[0]}-{train_seasons[-1]} ({len(train)} tries), test {test_season} ({len(test)} tries, '
              f'{sum(r["two"] for r in test)} two-point, {100 * sum(r["two"] for r in test) / len(test):.1f}%)')
        print(f'  {"model":44s} {"Brier":>8s} {"log loss":>9s} {"mean p":>7s} {"Brier opening":>14s}')
        for name, structure, k in MODELS:
            policy = tp.TryPolicy(train, structure=structure, k=k)
            brier, logloss, mean_p = score(policy, test)
            brier_open, _, _ = score(policy, opening)
            print(f'  {name:44s} {brier:8.5f} {logloss:9.5f} {mean_p:7.4f} {brier_open:14.5f}')
        print()


if __name__ == '__main__':
    main()
