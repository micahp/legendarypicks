#!/usr/bin/env python3
"""The winning coach's kick-or-receive decision in overtime, estimated from the observed coin-toss table.

Source: docs/fixtures/e2/overtime_coin_toss_2023_2026.csv (toss winner, the choice, and the first receiver for each game,
with its source). The coin toss itself is a seeded fair draw in the engine; only the choice after winning it is modelled here.

Estimation window (replay-safe): 2025 regular season, 14 games. A Beta(1, 1) prior gives the posterior mean for the
probability of kicking:

    p_kick = (kicks + 1) / (games + 2)

Chronological check: the 2026 regular-season rows (through Week 7) are scored against the fitted rate, the 50/50 neutral
baseline, and the always-receive control, by log-loss. They are not used to fit the rate.

The 2023 Super Bowl and the 2025 playoff rows are kept in the source table and excluded here: they are not regular-season
decisions under the current overtime rules.

Run with the parquet environment (stdlib only):
    /root/.venvs/nfl-parquet/bin/python scripts/nfl_sequence/build_overtime_choice_model.py
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / 'docs/fixtures/e2/overtime_coin_toss_2023_2026.csv'
DEFAULT_OUT = REPO / 'docs/fixtures/e2/overtime_choice_model_2025.csv'
FIT_SEASONS = ('2025',)
CHECK_SEASONS = ('2026',)
PRIOR_A, PRIOR_B = 1, 1


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def wilson(successes, n, z=1.959964):
    if n == 0:
        return None, None
    p = successes / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - half) / denom, (centre + half) / denom


def log_loss(p, outcomes):
    total = 0.0
    for kick in outcomes:
        q = min(max(p, 1e-9), 1 - 1e-9)
        total += -(math.log(q) if kick else math.log(1 - q))
    return total / len(outcomes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    rows = [r for r in csv.DictReader(SOURCE.open()) if r['game_type'] == 'REG']
    fit = [1 if r['toss_choice'] == 'kick' else 0 for r in rows if r['season'] in FIT_SEASONS]
    check = [1 if r['toss_choice'] == 'kick' else 0 for r in rows if r['season'] in CHECK_SEASONS]
    kicks, games = sum(fit), len(fit)
    p_kick = (kicks + PRIOR_A) / (games + PRIOR_A + PRIOR_B)
    low, high = wilson(kicks, games)
    results = {
        'fitted_p_kick': p_kick,
        'check_log_loss': {'fitted': log_loss(p_kick, check), 'neutral_50_50': log_loss(0.5, check),
                           'always_receive_control': log_loss(0.0, check)},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, 'w', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(['fit_season', 'game_type', 'games', 'kicks', 'prior_a', 'prior_b', 'p_kick',
                    'observed_kick_rate_wilson95_low', 'observed_kick_rate_wilson95_high'])
        w.writerow(['2025', 'REG', games, kicks, PRIOR_A, PRIOR_B, f'{p_kick:.6f}', f'{low:.6f}', f'{high:.6f}'])
    manifest = {
        'generator': str(Path(__file__).resolve().relative_to(REPO)), 'generator_sha256': sha256(__file__),
        'source': str(SOURCE.relative_to(REPO)), 'source_sha256': sha256(SOURCE),
        'fit_window': {'seasons': list(FIT_SEASONS), 'game_type': 'REG', 'games': games, 'kicks': kicks},
        'prior': {'a': PRIOR_A, 'b': PRIOR_B, 'form': 'Beta(a, b) posterior mean (kicks + a) / (games + a + b)'},
        'p_kick': round(p_kick, 6),
        'observed_kick_rate_wilson95': [round(low, 6), round(high, 6)],
        'chronological_check': {'seasons': list(CHECK_SEASONS), 'game_type': 'REG', 'games': len(check),
                                'kicks': sum(check), 'log_loss': {k: round(v, 6) for k, v in results['check_log_loss'].items()}},
        'excluded': 'the 2023 Super Bowl and the 2025 playoff rows: not regular-season decisions under the current rules',
        'engine_assumptions': [
            'the coin toss is a seeded fair draw; the toss winner is the only team whose decision is modelled',
            'the kick-or-receive decision is a seeded Bernoulli draw with p_kick; kick gives the other team the first possession',
            'replays before 2026-10-25 use this 2025-only fit; the 2026 rows are a check, not a fit input',
            'the always-receive and always-kick arms are labelled controls, not models',
        ],
        'output': {'path': str(args.out.relative_to(REPO)), 'sha256': sha256(args.out)},
    }
    args.out.with_suffix(args.out.suffix + '.manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'games_fit': games, 'kicks_fit': kicks, 'p_kick': round(p_kick, 4),
                      'check_log_loss': manifest['chronological_check']['log_loss']}, indent=2))


if __name__ == '__main__':
    main()
