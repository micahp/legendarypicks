"""Content-keyed caching for expensive SLC setup fits.

This module is separate from the statistical models so introducing caching
cannot change a model's source-code SHA or mathematical implementation.
"""
from __future__ import annotations

import hashlib
import json
import os

import numpy as np
import scipy

import decision_layer
import fit_cache
import pass_label_outcomes


def pass_label_input_sha256(pool):
    """Fingerprint exactly the ordered inputs consumed by the conditional fit.

    The fitted model uses the pool cell, event type, season, penalty eligibility,
    source run/dropback flags for fumbles, and its A/D/E labels. Its manifest also scans the labels on other event
    types, so those are included. No raw player or yardage field participates.
    The ordered digest is streaming and does not materialize another pool.
    """
    digest = hashlib.sha256()
    for cell, rows in pool.items():
        digest.update(json.dumps(('cell', cell), separators=(',', ':')).encode())
        digest.update(b'\n')
        for event, row, _runoff, _spot in rows:
            labels = row.get('labels') or {}
            values = (event, row.get('season'), row.get('penalty'),
                      row.get('play_type'), row.get('qb_scramble'),
                      tuple(labels.get(category) for category in pass_label_outcomes.CATEGORIES))
            digest.update(json.dumps(values, separators=(',', ':')).encode())
            digest.update(b'\n')
    return digest.hexdigest()


def fit_pass_label_outcomes(pool, *, ridge=pass_label_outcomes.RIDGE,
                            base_prior=pass_label_outcomes.BASE_PRIOR):
    """Reuse numerical fitting only for an identical training input and build.

    Call the original model directly if caching is disabled. In particular,
    this does not cache mutable samplers or any game-specific state.
    """
    model = pass_label_outcomes.PassLabelOutcomeModel
    if not os.environ.get('SLC_FIT_CACHE_DIR'):
        return model.fit(pool, ridge=ridge, base_prior=base_prior)
    source = (pass_label_input_sha256(pool), float(ridge), float(base_prior),
              np.__version__, scipy.__version__)
    return fit_cache.memo('pass_label_outcomes.fit', source,
                          lambda: model.fit(pool, ridge=ridge, base_prior=base_prior),
                          code_files=(__file__, pass_label_outcomes.__file__, decision_layer.__file__))
