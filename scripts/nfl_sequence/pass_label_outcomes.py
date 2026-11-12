"""Regularized pass-outcome model conditional on receiver/depth/location labels.

The model is used only after a dropback is known to produce a pass attempt.
Sacks are deliberately excluded from its outcome vocabulary.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

import decision_layer
import e0_single_play as e0

MODEL_ID = 'slc-pass-label-conditional-outcomes-v1-research'
OUTCOMES = ('pass_complete', 'pass_incomplete', 'interception', 'fumble_lost')
CATEGORIES = ('A', 'D', 'E')
FEATURES = tuple((category, value) for category in CATEGORIES
                 for value in decision_layer.CAT_ROLES[category])
RIDGE = 0.01
BASE_PRIOR = 20.0
MIN_ROWS = 100


def _softmax(logits):
    values = np.asarray(logits, dtype=np.float64)
    values = values - np.max(values, axis=-1, keepdims=True)
    values = np.exp(values)
    return values / values.sum(axis=-1, keepdims=True)


class PassLabelOutcomeModel:
    def __init__(self, base, global_base, coefficients, manifest):
        self.base = {tuple(key): tuple(float(x) for x in value) for key, value in base.items()}
        self.global_base = tuple(float(x) for x in global_base)
        self.coefficients = np.asarray(coefficients, dtype=np.float64)
        self.manifest = dict(manifest)
        self._calibration = {}
        self._feature_index = {feature: i for i, feature in enumerate(FEATURES)}

    @classmethod
    def fit(cls, pool, *, ridge=RIDGE, base_prior=BASE_PRIOR):
        """Fit from clean pre-cutoff pool rows already annotated with decision labels."""
        samples = []
        all_counts = {}
        global_counts = np.ones(len(OUTCOMES), dtype=np.float64)
        penalty_eligibility = {'known_clean': 0, 'penalty_tagged': 0, 'unknown': 0, 'other': 0}
        feature_index = {feature: i for i, feature in enumerate(FEATURES)}
        outcome_index = {event: i for i, event in enumerate(OUTCOMES)}
        for cell, rows in pool.items():
            counts = np.ones(len(OUTCOMES), dtype=np.float64)
            for event, row, _runoff, _spot in rows:
                if event not in outcome_index:
                    continue
                penalty = row.get('penalty')
                if penalty is None:
                    penalty_eligibility['unknown'] += 1
                    continue
                try:
                    penalty = int(penalty)
                except (TypeError, ValueError):
                    penalty_eligibility['other'] += 1
                    continue
                if penalty != 0:
                    penalty_eligibility['penalty_tagged' if penalty == 1 else 'other'] += 1
                    continue
                penalty_eligibility['known_clean'] += 1
                if int(row.get('season', 0)) < decision_layer.FIRST_CHARTED_SEASON:
                    continue
                counts[outcome_index[event]] += 1.0
                global_counts[outcome_index[event]] += 1.0
                labels = row.get('labels') or {}
                if not any(labels.get(category) is not None for category in CATEGORIES):
                    continue
                x = np.zeros(len(FEATURES), dtype=np.float64)
                for category in CATEGORIES:
                    value = labels.get(category)
                    index = feature_index.get((category, value))
                    if index is not None:
                        x[index] = 1.0
                samples.append((tuple(cell), event, x))
            if counts.sum() > len(OUTCOMES):
                all_counts[tuple(cell)] = counts
        if len(samples) < MIN_ROWS:
            raise ValueError(f'pass-label model needs at least {MIN_ROWS} labelled pass outcomes; found {len(samples)}')

        global_base = global_counts / global_counts.sum()
        base = {}
        for cell, counts in all_counts.items():
            probabilities = (counts + float(base_prior) * global_base) / (counts.sum() + float(base_prior))
            base[cell] = probabilities

        x = np.stack([sample[2] for sample in samples])
        y = np.fromiter((outcome_index[sample[1]] for sample in samples), dtype=np.int64, count=len(samples))
        offsets = np.stack([np.log(base.get(sample[0], global_base)) for sample in samples])
        n, feature_count = x.shape
        outcome_count = len(OUTCOMES)

        def objective(flat):
            coefficients = flat.reshape(feature_count, outcome_count)
            probabilities = _softmax(offsets + x @ coefficients)
            loss = -np.log(np.maximum(probabilities[np.arange(n), y], 1e-15)).mean()
            loss += 0.5 * float(ridge) * np.square(coefficients).sum()
            residual = probabilities
            residual[np.arange(n), y] -= 1.0
            gradient = x.T @ residual / n + float(ridge) * coefficients
            return float(loss), gradient.ravel()

        result = minimize(objective, np.zeros(feature_count * outcome_count), jac=True,
                          method='L-BFGS-B', options={'maxiter': 200, 'ftol': 1e-10})
        if not result.success:
            raise ValueError(f'pass-label conditional fit did not converge: {result.message}')
        coefficients = result.x.reshape(feature_count, outcome_count)
        manifest = {
            'model': MODEL_ID,
            'source_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'rows': len(samples),
            'contexts': len(base),
            'outcomes': list(OUTCOMES),
            'features': [f'{category}={value}' for category, value in FEATURES],
            'ridge': float(ridge),
            'base_prior': float(base_prior),
            'iterations': int(result.nit),
            'penalty_eligibility': penalty_eligibility,
            'penalty_policy': 'fit only rows with penalty=0; NULL, tagged and unknown codes are excluded',
            'fit_seasons': sorted({int(row.get('season')) for rows in pool.values()
                                   for _event, row, _runoff, _spot in rows
                                   if row.get('labels') and any(row['labels'].get(c) is not None
                                                                 for c in CATEGORIES)}),
        }
        payload = {'manifest': manifest,
                   'base': {str(key): list(value) for key, value in sorted(base.items())},
                   'global_base': global_base.tolist(), 'coefficients': coefficients.tolist()}
        manifest['sha256'] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return cls(base, global_base, coefficients, manifest)

    def base_probabilities(self, context):
        probabilities = self.base.get(tuple(context), self.global_base)
        return dict(zip(OUTCOMES, probabilities))

    def probabilities(self, context, labels):
        x = self._feature_vector(labels)
        logits = np.log(self.base.get(tuple(context), self.global_base)) + x @ self.coefficients
        probabilities = _softmax(logits)
        return dict(zip(OUTCOMES, probabilities.tolist()))

    def _feature_vector(self, labels):
        x = np.zeros(len(FEATURES), dtype=np.float64)
        for category in CATEGORIES:
            index = self._feature_index.get((category, (labels or {}).get(category)))
            if index is not None:
                x[index] = 1.0
        return x

    def ratio(self, context, labels, event, *, label_prior=None, calibration_key=None):
        if event not in OUTCOMES:
            return 1.0
        base = self.base_probabilities(context)[event]
        if base <= 0:
            return 1.0
        if label_prior:
            key = (tuple(context), calibration_key)
            offset = self._calibration.get(key)
            if offset is None:
                offset = self._calibration_offset(context, label_prior)
                self._calibration[key] = offset
            x = self._feature_vector(labels)
            logits = np.log(self.base.get(tuple(context), self.global_base)) + x @ self.coefficients + offset
            probability = _softmax(logits)[OUTCOMES.index(event)]
        else:
            probability = self.probabilities(context, labels)[event]
        return float(probability) / base

    def _calibration_offset(self, context, label_prior):
        """Center conditional effects so generated labels preserve the base event mix in expectation."""
        options = [list((label_prior.get(category) or {}).items()) for category in CATEGORIES]
        if any(not values for values in options):
            return np.zeros(len(OUTCOMES), dtype=np.float64)
        combinations = []
        for combination in itertools.product(*options):
            weight = math.prod(float(item[1]) for item in combination)
            x = np.zeros(len(FEATURES), dtype=np.float64)
            for category, (value, _probability) in zip(CATEGORIES, combination):
                index = self._feature_index.get((category, value))
                if index is not None:
                    x[index] = 1.0
            combinations.append((weight, x))
        base = np.asarray(self.base.get(tuple(context), self.global_base))
        offset = np.zeros(len(OUTCOMES), dtype=np.float64)
        logits_base = np.log(self.base.get(tuple(context), self.global_base))
        converged = False
        for _ in range(100):
            expected = np.zeros(len(OUTCOMES), dtype=np.float64)
            for weight, x in combinations:
                expected += weight * _softmax(logits_base + x @ self.coefficients + offset)
            if np.max(np.abs(expected - base)) < 1e-10:
                converged = True
                break
            offset += np.log(base / np.maximum(expected, 1e-15))
            offset -= offset.mean()
        if not converged:
            raise ValueError(f'pass-label calibration failed for {context!r}')
        return offset
