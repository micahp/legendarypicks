"""Exact, fail-closed mapping from source labels to the V1.7 rules catalog."""
from __future__ import annotations

from dataclasses import dataclass
import re

import penalty_enforcement


class PenaltyTypeMappingError(ValueError):
    pass


@dataclass(frozen=True)
class PenaltyClassification:
    penalty_type: str
    block_subtype: str | None = None


_ALIASES = {
    'false_start': 'false_start',
    'delay_of_game': 'delay_of_game',
    'encroachment': 'encroachment',
    'neutral_zone_infraction': 'neutral_zone_infraction',
    'offensive_holding': 'offensive_holding',
    'offensive_pass_interference': 'offensive_pass_interference',
    'intentional_grounding': 'intentional_grounding',
    'illegal_formation': 'illegal_formation',
    'illegal_shift': 'illegal_shift',
    'illegal_motion': 'illegal_motion',
    'defensive_holding': 'defensive_holding',
    'defensive_pass_interference': 'defensive_pass_interference',
    'illegal_contact': 'illegal_contact',
    'roughing_the_passer': 'roughing_passer',
    'roughing_passer': 'roughing_passer',
    'defensive_offside': 'offside',
    'offside': 'offside',
    'offsides': 'offside',
}

_BLOCK_ALIASES = {
    'illegal_block_above_the_waist': 'above_waist',
    'illegal_block_in_the_back': 'in_back',
    'block_in_the_back': 'in_back',
}

_SIDE_DEPENDENT = {
    'holding': {'offense': 'offensive_holding', 'defense': 'defensive_holding'},
    'pass_interference': {
        'offense': 'offensive_pass_interference',
        'defense': 'defensive_pass_interference',
    },
}

_NOMINAL_YARDS = {
    # These rules have variable enforcement distances, represented by a spot.
    'defensive_pass_interference': 0,
    'intentional_grounding': 10,
}


def normalize_source_label(label: str) -> str:
    if not isinstance(label, str) or not label.strip():
        raise PenaltyTypeMappingError('penalty_type_label_missing')
    return re.sub(r'[^a-z0-9]+', '_', label.casefold()).strip('_')


def classify_penalty_type(label: str, team: str, block_subtype: str | None = None) -> PenaltyClassification:
    """Map only known label spellings; never infer a nearby foul by substring."""
    if team not in ('offense', 'defense'):
        raise PenaltyTypeMappingError('penalty_committing_side_unsupported:' + str(team))
    normalized = normalize_source_label(label)
    if normalized in _BLOCK_ALIASES:
        inferred_subtype = _BLOCK_ALIASES[normalized]
        penalty_type = 'illegal_block'
        if block_subtype is not None and block_subtype != inferred_subtype:
            raise PenaltyTypeMappingError('penalty_block_subtype_conflicts_with_source_label')
        block_subtype = inferred_subtype
    elif normalized in _SIDE_DEPENDENT:
        penalty_type = _SIDE_DEPENDENT[normalized][team]
    else:
        penalty_type = _ALIASES.get(normalized, normalized)

    if block_subtype not in (None, 'in_back', 'above_waist'):
        raise PenaltyTypeMappingError('penalty_block_subtype_invalid')
    if penalty_type != 'illegal_block' and block_subtype is not None:
        raise PenaltyTypeMappingError('penalty_block_subtype_on_non_block_foul')
    if (team, penalty_type) not in penalty_enforcement.RULES:
        raise PenaltyTypeMappingError(
            f'penalty_type_not_supported_by_v17_rules:{team}:{penalty_type}')
    if penalty_type == 'illegal_block' and block_subtype is None:
        raise PenaltyTypeMappingError('illegal_block_requires_verified_subtype')
    return PenaltyClassification(penalty_type, block_subtype)


def nominal_yards_for(classification: PenaltyClassification) -> int:
    """Return the catalog's nominal yardage; actual enforcement is computed separately."""
    rule = penalty_enforcement.RULES.get(('offense', classification.penalty_type))
    if rule is None:
        rule = penalty_enforcement.RULES.get(('defense', classification.penalty_type))
    if rule is None:
        raise PenaltyTypeMappingError('penalty_type_missing_rule:' + classification.penalty_type)
    if classification.penalty_type == 'illegal_block':
        if classification.block_subtype not in penalty_enforcement.BLOCK_SUBTYPES:
            raise PenaltyTypeMappingError('illegal_block_requires_verified_subtype')
        return penalty_enforcement.BLOCK_SUBTYPES[classification.block_subtype][0]
    if classification.penalty_type in _NOMINAL_YARDS:
        return _NOMINAL_YARDS[classification.penalty_type]
    if rule.yards is None:
        raise PenaltyTypeMappingError('nominal_penalty_yards_undefined:' + classification.penalty_type)
    return rule.yards
