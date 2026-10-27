"""Rule regimes from the NFL rule-history registry (docs/research/NFL-RULE-REGIME-REGISTRY-2010-2026.json).

A target game's active rules are the registry entries whose effective seasons cover its season and whose applicability
includes its season type (REG or POST). The engine uses the active rules to choose which historical samples a target may
draw from, and records the registry's checksum and the active rule IDs with every simulation manifest.
"""
import hashlib
import json
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[2] / 'docs/research/NFL-RULE-REGIME-REGISTRY-2010-2026.json'


def load_registry(path=REGISTRY):
    """The registry and its SHA-256, read from the file as bytes so the checksum matches the file exactly."""
    raw = Path(path).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def active_rules(registry, season, season_type='REG', domain=None):
    """Return matching rule IDs from either registry schema.

    Schema 1 calls applicability ``applies_to``; the expanded annual inventory
    (schema 2) calls it ``season_types``. Schema 2's ``trial_until`` is its
    explicit inclusive end-season field for temporary rules. Expiry markers and
    contingent approvals are not active rules. Other records without an end
    field remain open-ended until a verified supersession or expiry is recorded.
    """
    out = []
    for change in registry['changes']:
        if change.get('adoption_status') in {
            'expiry_of_temporary_provision',
            'approved_contingent_not_automatically_active',
        }:
            continue
        start = change.get('effective_from_season')
        end = change.get('effective_through_season', change.get('trial_until'))
        if start is not None and season < start:
            continue
        if end is not None and season > end:
            continue
        applicability = change.get('applies_to', change.get('season_types', []))
        if season_type not in applicability:
            continue
        if domain is not None and change.get('domain') != domain:
            continue
        out.append(change['id'])
    return sorted(out)


def regime_key(registry, season, season_type='REG', domain=None):
    """Seasons with the same key have the same active rules for the domain, so their samples are comparable."""
    return tuple(active_rules(registry, season, season_type, domain))


def seasons_with_same_rules(registry, target_season, seasons, season_type='REG', domain=None):
    """The seasons in `seasons` whose active rules match the target season's: the only seasons whose samples may be pooled."""
    target = regime_key(registry, target_season, season_type, domain)
    return sorted(s for s in seasons if regime_key(registry, s, season_type, domain) == target)
