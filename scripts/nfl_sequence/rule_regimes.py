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
    """The registry IDs active for a season and season type, optionally restricted to one domain, sorted."""
    out = []
    for change in registry['changes']:
        start, end = change.get('effective_from_season'), change.get('effective_through_season')
        if start is not None and season < start:
            continue
        if end is not None and season > end:
            continue
        if season_type not in change.get('applies_to', []):
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
