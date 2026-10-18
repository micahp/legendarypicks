"""Shared checks for assigning ESPN IDs to rows carrying NFL GSIS IDs."""
from __future__ import annotations

import json
import os
from typing import Mapping, Optional, Tuple


ARTIFACT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "published-identity-names.json",
)


class IdentityCrosswalkError(RuntimeError):
    """The committed publisher crosswalk is missing or malformed."""


def normalize_id(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    key = str(value).strip()
    if key.endswith(".0") and key[:-2].isdigit():
        key = key[:-2]
    return key or None


def load_espn_to_gsis(path: str = ARTIFACT) -> Tuple[dict[str, str], set[str]]:
    try:
        with open(path, encoding="utf-8") as handle:
            artifact = json.load(handle)
        crosswalks = artifact["leagues"]["nfl"]["crosswalks"]
        mapping = crosswalks["espn_id_to_gsis_id"]
        ambiguous = crosswalks["ambiguous_espn_ids"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise IdentityCrosswalkError(
            "NFL ESPN-to-GSIS publisher crosswalk is missing or invalid"
        ) from exc
    if not isinstance(mapping, dict) or not isinstance(ambiguous, list):
        raise IdentityCrosswalkError("NFL ESPN-to-GSIS crosswalk has an invalid shape")
    return (
        {str(key): str(value) for key, value in mapping.items()},
        {str(key) for key in ambiguous},
    )


def espn_assignment_conflict(
    espn_id,
    existing_gsis_id,
    crosswalk: Mapping[str, str],
    ambiguous_espn_ids: set[str] | frozenset[str] = frozenset(),
) -> Optional[str]:
    """Return a reason when an ESPN ID cannot safely be attached to this row.

    An empty GSIS field has no competing identity. A populated one must agree
    with nflverse's unique ESPN-to-GSIS mapping; an absent mapping fails closed.
    """
    existing = normalize_id(existing_gsis_id)
    if not existing:
        return None
    espn_key = normalize_id(espn_id)
    if not espn_key:
        return "missing_espn_id"
    if espn_key in ambiguous_espn_ids:
        return "ambiguous_published_espn_id"
    target = crosswalk.get(espn_key)
    if target is None:
        return "unverified_published_espn_id"
    if normalize_id(target) != existing:
        return "espn_gsis_identity_conflict"
    return None
