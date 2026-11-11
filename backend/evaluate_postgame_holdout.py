"""Offline evaluation of a pinned postgame corpus, with no tuning or network."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import time

from postgame_story_engine import generate_recap
from postgame_story_audit import audit
from postgame_rubric import grade_postgame

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'docs/research/postgame-content-demo-2026-11-10'


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--corpus', type=Path, default=DEFAULT / 'heldout-fixtures.jsonl')
    parser.add_argument('--output', type=Path, default=DEFAULT)
    args = parser.parse_args()
    freeze = json.loads((DEFAULT / 'heldout-freeze.json').read_text())
    for name, expected in freeze['sha256'].items():
        if hashlib.sha256((ROOT / 'backend' / name).read_bytes()).hexdigest() != expected:
            raise SystemExit('frozen code has changed: ' + name)
    raw = args.corpus.read_bytes(); bundles = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if Counter(b['game']['league'] for b in bundles) != {'nba': 50, 'nfl': 50}:
        raise SystemExit('corpus must contain exactly 50 games per sport')
    if len({(b['game']['league'], b['game']['game_id']) for b in bundles}) != 100:
        raise SystemExit('duplicate game in corpus')
    results = []
    for bundle in bundles:
        start = time.perf_counter_ns(); recap = generate_recap(bundle); elapsed = (time.perf_counter_ns() - start) / 1e6
        independent = audit(bundle, recap); grade = grade_postgame(bundle, recap)
        kinds = {s.get('kind') for s in bundle.get('sources', [])}
        selected = next((c for c in recap['candidates'] if c['angle_id'] == recap['selected']), {})
        results.append({'league': bundle['game']['league'], 'game_id': bundle['game']['game_id'],
                        'input_sha256': recap['input_sha256'], 'as_of_utc': bundle['as_of_utc'],
                        'headline': recap['headline'], 'lede': recap['lede'], 'paragraphs': recap['paragraphs'],
                        'selected': recap['selected'], 'selected_type': selected.get('candidate_type'),
                        'candidates': recap['candidates'], 'claims': recap['claims'], 'gate': recap['gate'],
                        'independent_audit': independent, 'rubric': grade, 'render_ms': elapsed,
                        'coverage': {'scoreboard': bool(bundle.get('sources')), 'final_boxscore': 'final_boxscore' in kinds,
                                     'publisher_pbp_crosschecked': 'final_pbp' in kinds,
                                     'pregame_lock': bool(bundle.get('pregame_model_locks')),
                                     'rights_cleared_video': False},
                        'capture_issue': bundle.get('capture_issue')})
    output = args.output; output.mkdir(parents=True, exist_ok=True)
    (output / 'heldout-v03-results.jsonl').write_text(''.join(json.dumps(r, sort_keys=True, ensure_ascii=False) + '\n' for r in results))
    summary = {}
    for league in ('nfl', 'nba'):
        rows = [r for r in results if r['league'] == league]; times = sorted(r['render_ms'] for r in rows)
        grades = {name: [r['rubric']['dimensions'][name]['score'] for r in rows if r['rubric']['dimensions'][name]['score'] is not None]
                  for name in ('facts', 'hook', 'specificity', 'voice', 'sequence', 'clarity')}
        headlines = [r['headline'] for r in rows if r['headline']]
        lengths = [len(' '.join([r['lede']] + r['paragraphs']).split()) for r in rows if r['lede']]
        summary[league] = {'games': len(rows), 'gates': dict(Counter(r['gate'] for r in rows)),
             'games_all_mechanical_checks_pass': sum(all(r['independent_audit'].values()) for r in rows),
             'claims_in_passing_games': sum(len(r['claims']) for r in rows if all(r['independent_audit'].values())),
             'claims_in_blocked_games': sum(len(r['claims']) for r in rows if not all(r['independent_audit'].values())),
             'selected_angle_counts': dict(Counter(r['selected_type'] or 'none' for r in rows)),
             'narrative_beyond_result': sum(r['selected_type'] not in (None, 'fallback') for r in rows),
             'nonempty_headlines': len(headlines), 'duplicate_headlines': len(headlines) - len(set(headlines)),
             'mean_story_words': round(statistics.mean(lengths), 2) if lengths else None,
             'templates': dict(Counter(r['selected'] and r['selected'].split(':')[0] or 'none' for r in rows)),
             'source_coverage': {k: sum(r['coverage'][k] for r in rows) for k in rows[0]['coverage']},
             'rubric_dimension_means': {k: round(statistics.mean(v), 1) if v else None for k, v in grades.items()},
             'renderer_median_ms': round(statistics.median(times), 4), 'renderer_p95_ms': round(times[47], 4),
             'human_ratings': 0, 'capture_issues': sum(bool(r['capture_issue']) for r in rows)}
    result = {'engine_version': freeze['engine_version'], 'seed': freeze['seed'], 'corpus_sha256': hashlib.sha256(raw).hexdigest(),
              'frozen_sha256': freeze['sha256'], 'sample': '50 NFL and 50 NBA fixed-seed completed games; previous and coached fixtures excluded',
              'limitations': ['Mechanical checks recompute normalized facts, not independent publisher facts.',
                              'Source coverage does not prove all individual plays are correct.',
                              'Automated editorial proxy scores are not human judgments.',
                              'Human preference versus legacy and external editorial metadata was not measured.'],
              'by_league': summary}
    (output / 'heldout-v03-evaluation.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print('Offline held-out evaluation saved.')


if __name__ == '__main__':
    main()
