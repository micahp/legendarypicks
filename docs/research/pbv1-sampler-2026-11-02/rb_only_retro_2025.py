"""The RB-only retrospective fold, authorized by the owner on 2026-11-02.

Pre-registered in PBV1-SAMPLER-SPEC-2026-11-02.md (section 4, retrospective fold): fit 2022 to 2024, score 2025, K = 20,
game-clustered bootstrap with the spec's draws and seed. The target is `package_rb`, the RB-only SLC code, which the frozen
results scored on the development folds only. This fold is scored once. The script refuses to run when its output file
exists, and it writes only outputs/pbv1_rb_only_retro_2025.json. It does not rewrite pbv1_results.json.

Run from the repository root:
    python3 docs/research/pbv1-sampler-2026-11-02/rb_only_retro_2025.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pbv1_eval as ev  # noqa: E402
import pbv1_sampler as pb  # noqa: E402

OUT = os.path.join(HERE, 'outputs', 'pbv1_rb_only_retro_2025.json')


def main():
    if os.path.exists(OUT):
        raise SystemExit(f'{OUT} exists: this fold was already scored once and is not scored again')
    fold = next(f for f in ev.FOLDS if f['name'] == 'retro_2025')
    plays, excluded = ev.load_plays()
    row = ev.fold_metrics(plays, fold, ev.PRIMARY_K, 'package_rb')
    payload = {
        'spec': 'PBV1-SAMPLER-SPEC-2026-11-02.md section 4, retrospective fold, RB-only target (owner authorization 2026-11-02)',
        'scored_once': True,
        'fit_seasons': list(fold['train']),
        'score_season': fold['test'],
        'K': ev.PRIMARY_K,
        'target': 'package_rb',
        'bootstrap': {'draws': pb.BOOTSTRAP_DRAWS, 'seed': pb.BOOTSTRAP_SEED, 'unit': 'game'},
        'scrimmage_regular_season_plays': len(plays),
        'excluded': dict(excluded),
        'fold': row,
    }
    with open(OUT, 'x', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2)
    print(json.dumps({k: row[k] for k in ('test_plays', 'comparable_plays', 'mean_log_likelihood',
                                          'sampler_minus_b0', 'sampler_minus_b1', 'unsupported')}, indent=2))


if __name__ == '__main__':
    main()
