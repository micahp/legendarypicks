"""Recovery model for a fumble at or past the offense's goal line (V1.7 research path).

The counts are the audit in docs/research/own-end-zone-recovery-2026-11-16/AUDIT.md (nflverse 1999 to 2025 play
descriptions and official flags). A fumble that leaves the ball at or past the offense goal line is one of five
categories. Each category has a set of outcomes it can produce. Rule outcomes are fixed; the rest are probabilities
from the audit with a discounted prior from 1999 to 2009.

Outcomes:
- touchdown: the defense scores (6 points, then the try and the scoring team's kickoff).
- safety: the defense scores 2 points (then a safety free kick).
- unresolved: the ball stays live, or the play ends with no score the model can place. The drive loop refuses it with a
  named block. No endpoint is invented.

This module does not touch V1.6. The drive loop uses it only when a recovery model is supplied.
"""
import random

# Counts from the audit, split by era. Old = 1999-2009, new = 2010-2025 (primary).
# Support lists the only outcomes each category can produce.
CATEGORIES = {
    'defense_recovers_in_offense_end_zone': {
        'old': {'touchdown': 8}, 'new': {'touchdown': 19}, 'support': ('touchdown',), 'rule': 'touchdown'},
    'offense_recovers_in_own_end_zone': {
        'old': {'safety': 6, 'unresolved': 1}, 'new': {'safety': 13, 'unresolved': 3},
        'support': ('safety', 'unresolved'), 'rule': None},
    'out_of_bounds_in_offense_end_zone': {
        'old': {'safety': 17}, 'new': {'safety': 12}, 'support': ('safety',), 'rule': 'safety'},
    'defense_recovers_in_field': {
        'old': {'touchdown': 17, 'safety': 1}, 'new': {'touchdown': 11, 'unresolved': 3},
        'support': ('touchdown', 'safety', 'unresolved'), 'rule': None},
    'offense_recovers_in_field': {
        'old': {'safety': 7, 'unresolved': 3}, 'new': {'safety': 3, 'unresolved': 4},
        'support': ('safety', 'unresolved'), 'rule': None},
}
OUTCOMES = ('touchdown', 'safety', 'unresolved')
DEFAULT_OLD_WEIGHT = 0.5  # discount for 1999-2009 evidence; 1.0 is the fully pooled sensitivity check


def _total(counts):
    return sum(counts.values())


class RecoveryModel:
    """Dirichlet posterior means for category and outcome, with one pseudo-count per supported outcome.

    `old_weight` scales the 1999-2009 counts. `old_weight=0` uses only 2010-2025.
    """

    def __init__(self, old_weight=DEFAULT_OLD_WEIGHT):
        if not 0 <= old_weight <= 1:
            raise ValueError(f'old_weight must be between 0 and 1 (got {old_weight})')
        self.old_weight = old_weight
        self.category_alpha = {}
        self.outcome_probability = {}
        for name, spec in CATEGORIES.items():
            self.category_alpha[name] = 1.0 + old_weight * _total(spec['old']) + _total(spec['new'])
        total = sum(self.category_alpha.values())
        self.category_probability = {name: alpha / total for name, alpha in self.category_alpha.items()}
        for name, spec in CATEGORIES.items():
            alpha = {o: 1.0 + old_weight * spec['old'].get(o, 0) + spec['new'].get(o, 0) for o in spec['support']}
            norm = sum(alpha.values())
            if spec['rule'] is not None:
                self.outcome_probability[name] = {o: (1.0 if o == spec['rule'] else 0.0) for o in OUTCOMES}
            else:
                self.outcome_probability[name] = {o: (alpha[o] / norm if o in alpha else 0.0) for o in OUTCOMES}

    def effective_sample_size(self):
        """Old counts count at old_weight. Used to report how much evidence sits behind each probability."""
        return {name: self.old_weight * _total(spec['old']) + _total(spec['new']) for name, spec in CATEGORIES.items()}

    def unresolved_probability(self):
        """Share of fumbles at the goal line that reach the named unresolved block."""
        return sum(self.category_probability[c] * self.outcome_probability[c]['unresolved'] for c in CATEGORIES)

    def draw(self, rng):
        """Return (category, outcome). The random stream is the caller's, so the draw is reproducible."""
        names = list(CATEGORIES)
        category = rng.choices(names, weights=[self.category_probability[n] for n in names])[0]
        probs = self.outcome_probability[category]
        outcome = rng.choices(OUTCOMES, weights=[probs[o] for o in OUTCOMES])[0]
        return category, outcome


def load(old_weight=DEFAULT_OLD_WEIGHT):
    return RecoveryModel(old_weight=old_weight)
