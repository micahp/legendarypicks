"""Postgame-specific rule-based review proxy, sharing pregame palette and jargon rules."""
from story_rubric import JARGON, PASTELS

VERSION = 'postgame-rubric-v0.1'
WEIGHTS = {'facts': 30, 'hook': 20, 'specificity': 15, 'voice': 15, 'sequence': 10, 'clarity': 10}
COLORS = dict(zip(WEIGHTS, PASTELS.values()))


def grade_postgame(bundle, recap):
    checks = recap.get('audit')
    if checks is None:
        status = 'needs-audit'
    elif not checks or not all(checks.values()):
        status = 'blocked'
    else:
        status = recap.get('gate', 'needs-audit')
    text = ' '.join([recap.get('headline', ''), recap.get('lede', '')] + recap.get('paragraphs', []))
    rich = any(c.get('type') in ('player_stat', 'passing_line') for c in recap.get('claims', []))
    scores = {'facts': 100 if status not in ('blocked', 'needs-audit') else 0,
              'hook': 70 if rich else 30, 'specificity': 70 if rich else 25,
              'voice': 0 if JARGON.search(text) else 75,
              'sequence': None, 'clarity': 70 if text else 0}
    applicable = sum(WEIGHTS[k] for k, v in scores.items() if v is not None)
    overall = round(sum(WEIGHTS[k] * v for k, v in scores.items() if v is not None) / applicable) if applicable else None
    dimensions = {k: {'score': v, 'weight': WEIGHTS[k], 'applicable': v is not None, 'color': COLORS[k]}
                  for k, v in scores.items()}
    if status == 'eligible' and overall is not None and overall < 65:
        status = 'review'
    return {'version': VERSION, 'status': status, 'overall': overall, 'dimensions': dimensions,
            'interpretation': 'Automated editorial proxy, not a human rating.'}
