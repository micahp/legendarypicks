"""Experimental conditioning over optional historical outcome-row attributes.

Mandatory event compatibility, legal source-row checks, cutoff rules and roster
eligibility are applied before these helpers receive candidate rows.  These
helpers only handle optional contextual row conditioning.
"""
from __future__ import annotations

import math


MIN_CANDIDATES = 20
MIN_EFFECTIVE_SAMPLE_SIZE = 10.0
RELAX_PRIORITY = (
    'exact_yardline', 'qb_target_role', 'coverage', 'formation', 'streak',
    'decision_label:A', 'decision_label:B', 'decision_label:C',
    'decision_label:D', 'decision_label:E', 'decision_label:F',
    'decision_label:G', 'decision_label:H', 'decision_label:I',
    'decision_label:J', 'decision_label:K', 'decision_label:L',
    'decision_label:M', 'decision_label:N',
)


def effective_sample_size(weights):
    """Kish effective sample size for finite non-negative row weights."""
    values = [float(weight) for weight in weights]
    if any(not math.isfinite(weight) or weight < 0 for weight in values):
        raise ValueError('row weights must be finite and non-negative')
    total = sum(values)
    squares = sum(weight * weight for weight in values)
    return (total * total / squares) if total > 0 and squares > 0 else 0.0


def weight_concentration(weights):
    values = [float(weight) for weight in weights]
    total = sum(values)
    if total <= 0:
        return {'max_share': 0.0, 'hhi': 0.0}
    shares = [weight / total for weight in values]
    return {'max_share': max(shares, default=0.0), 'hhi': sum(share * share for share in shares)}


def filter_order_dependence(rows, conditions):
    """Compare the legacy non-empty sequential fallback in canonical and reverse order."""
    matches = {name: {index for index, row in enumerate(rows) if predicate(row)}
               for name, predicate in conditions}

    def apply(order):
        current = set(range(len(rows)))
        stages = []
        for name in order:
            matched = current & matches[name]
            applied = bool(matched)
            if applied:
                current = matched
            stages.append({'condition': name, 'applied': applied, 'candidate_count_after': len(current)})
        return current, stages

    forward, forward_stages = apply([name for name, _ in conditions])
    reverse, reverse_stages = apply([name for name, _ in reversed(conditions)])
    union = forward | reverse
    intersection = forward & reverse
    return {
        'canonical_order': [name for name, _predicate in conditions],
        'reverse_order': [name for name, _predicate in reversed(conditions)],
        'canonical_final_candidates': len(forward),
        'reverse_final_candidates': len(reverse),
        'jaccard_similarity': len(intersection) / len(union) if union else 1.0,
        'symmetric_difference_candidates': len(forward ^ reverse),
        'canonical_stages': forward_stages,
        'reverse_stages': reverse_stages,
    }


def support_aware(rows, conditions, base_weights, *, min_candidates=MIN_CANDIDATES,
                  min_ess=MIN_EFFECTIVE_SAMPLE_SIZE):
    """Apply the full intersection, relaxing one optional condition at a time.

    At each step the condition whose removal yields the best normalized support
    score is relaxed.  Exact ties use ``RELAX_PRIORITY`` and then condition
    name.  If the eligible event pool itself is below either threshold, all
    optional conditions are relaxed and the eligible pool is retained; the
    below-threshold status remains explicit in the returned audit record.
    """
    if min_candidates < 1 or min_ess < 1:
        raise ValueError('support thresholds must be positive')
    if len(rows) != len(base_weights):
        raise ValueError('base weights must align with candidate rows')
    weights = [float(weight) for weight in base_weights]
    if any(not math.isfinite(weight) or weight < 0 for weight in weights):
        raise ValueError('base row weights must be finite and non-negative')
    matches = {name: {index for index, row in enumerate(rows) if predicate(row)}
               for name, predicate in conditions}

    def selected(active):
        if not active:
            return list(range(len(rows)))
        indices = set.intersection(*(matches[name] for name, _ in active))
        return [index for index in range(len(rows)) if index in indices]

    def support(indices):
        selected_weights = [weights[index] for index in indices]
        return {'candidate_count': len(indices), 'effective_sample_size': effective_sample_size(selected_weights)}

    active = list(conditions)
    initial_indices = selected(active)
    initial_support = support(initial_indices)
    relaxation = []
    current_indices = initial_indices
    while (len(current_indices) < min_candidates or support(current_indices)['effective_sample_size'] < min_ess) and active:
        options = []
        for name, _predicate in active:
            trial = [condition for condition in active if condition[0] != name]
            trial_indices = selected(trial)
            trial_support = support(trial_indices)
            score = min(trial_support['candidate_count'] / min_candidates,
                        trial_support['effective_sample_size'] / min_ess)
            priority = RELAX_PRIORITY.index(name) if name in RELAX_PRIORITY else len(RELAX_PRIORITY)
            options.append((score, -priority, name, trial, trial_indices, trial_support))
        _score, _priority, removed, active, current_indices, trial_support = max(
            options, key=lambda item: (item[0], item[1], item[2]))
        relaxation.append({'condition': removed, **trial_support})
    final_support = support(current_indices)
    return [rows[index] for index in current_indices], {
        'method': 'support_aware',
        'optional_conditions_requested': [name for name, _predicate in conditions],
        'optional_conditions_retained': [name for name, _predicate in active],
        'relaxation_trace': relaxation,
        'minimum_candidate_count': int(min_candidates),
        'minimum_effective_sample_size': float(min_ess),
        'initial_support': initial_support,
        'final_support': final_support,
        'base_support': support(list(range(len(rows)))),
        'below_minimum_after_relaxation': (
            final_support['candidate_count'] < min_candidates
            or final_support['effective_sample_size'] < min_ess),
        'filter_order_dependence': filter_order_dependence(rows, conditions),
    }


def soft_weights(rows, conditions, base_weights, *, max_condition_weight=4.0,
                 shrinkage_prior_n=25.0):
    """Return bounded conditional row weights, shrunk toward the eligible pool.

    Each condition is represented as a mixture of its historical conditional
    distribution and the eligible historical distribution.  Condition factors
    are combined by geometric mean, not an unrestricted product.  The resulting
    contextual multiplier is bounded by the same per-condition cap.
    """
    if len(rows) != len(base_weights):
        raise ValueError('base weights must align with candidate rows')
    if not math.isfinite(max_condition_weight) or max_condition_weight <= 1.0:
        raise ValueError('max condition weight must be finite and greater than one')
    if not math.isfinite(shrinkage_prior_n) or shrinkage_prior_n <= 0:
        raise ValueError('shrinkage prior must be finite and positive')
    base = [float(weight) for weight in base_weights]
    if any(not math.isfinite(weight) or weight < 0 for weight in base):
        raise ValueError('base row weights must be finite and non-negative')
    base_total = sum(base)
    if not rows or base_total <= 0:
        return [], {
            'method': 'soft', 'optional_conditions_requested': [name for name, _predicate in conditions],
            'optional_conditions_weighted': [], 'unsupported_conditions': [name for name, _ in conditions],
            'candidate_count_before': len(rows), 'candidate_count_after': len(rows),
            'effective_sample_size': 0.0, 'max_weight_share': 0.0, 'hhi': 0.0,
            'max_condition_weight': max_condition_weight, 'shrinkage_prior_n': shrinkage_prior_n,
        }
    count_eff = effective_sample_size(base)
    shrink = count_eff / (count_eff + shrinkage_prior_n) if count_eff + shrinkage_prior_n else 1.0
    log_weights = [0.0] * len(rows)
    weighted_conditions = []
    unsupported = []
    for name, predicate in conditions:
        matching = [index for index, row in enumerate(rows) if predicate(row)]
        match_mass = sum(base[index] for index in matching)
        if match_mass <= 0:
            unsupported.append(name)
            continue
        p = match_mass / base_total
        conditional_ratio = min(1.0 / p, max_condition_weight)
        matched_set = set(matching)
        for index in range(len(rows)):
            likelihood_ratio = conditional_ratio if index in matched_set else 0.0
            component = max(0.0, 1.0 + shrink * (likelihood_ratio - 1.0))
            log_weights[index] += math.log(max(component, 1e-12))
        weighted_conditions.append({'condition': name, 'eligible_match_probability': p,
                                    'shrinkage': shrink, 'conditional_ratio_capped': conditional_ratio})
    divisor = len(weighted_conditions) or 1
    contextual = [math.exp(total / divisor) for total in log_weights]
    contextual = [min(max_condition_weight, max(0.0, weight)) for weight in contextual]
    final = [base_weight * context_weight for base_weight, context_weight in zip(base, contextual)]
    concentration = weight_concentration(final)
    return final, {
        'method': 'soft',
        'optional_conditions_requested': [name for name, _predicate in conditions],
        'optional_conditions_weighted': weighted_conditions,
        'unsupported_conditions': unsupported,
        'candidate_count_before': len(rows), 'candidate_count_after': len(rows),
        'effective_sample_size': effective_sample_size(final),
        'max_weight_share': concentration['max_share'], 'hhi': concentration['hhi'],
        'max_condition_weight': max_condition_weight, 'shrinkage_prior_n': shrinkage_prior_n,
        'filter_order_dependence': filter_order_dependence(rows, conditions),
        'context_weight_min': min(contextual, default=1.0),
        'context_weight_max': max(contextual, default=1.0),
    }
