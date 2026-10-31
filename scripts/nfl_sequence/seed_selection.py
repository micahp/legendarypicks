"""Validation and provenance helpers for explicit, non-contiguous seed batches."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


@dataclass(frozen=True)
class SeedSelection:
    seeds: tuple[int, ...]
    sha256: str

    @property
    def seed_start(self) -> int:
        return self.seeds[0]

    @property
    def seed_end_inclusive(self) -> int:
        return self.seeds[-1]

    def manifest(self) -> dict:
        return {
            'kind': 'explicit_seed_list',
            'seed_count': len(self.seeds),
            'seed_start': self.seed_start,
            'seed_end_inclusive': self.seed_end_inclusive,
            'sha256': self.sha256,
        }


def selection_from_seeds(values) -> SeedSelection:
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError('explicit seed selection must be a nonempty list')
    if any(type(seed) is not int or seed < 0 for seed in values):
        raise ValueError('every explicit seed must be a non-negative integer')
    if len(set(values)) != len(values):
        raise ValueError('explicit seed selection contains duplicate seeds')
    seeds = tuple(sorted(values))
    canonical = json.dumps(seeds, separators=(',', ':')).encode('ascii')
    return SeedSelection(seeds=seeds, sha256=hashlib.sha256(canonical).hexdigest())


def load_seed_selection(path: Path) -> SeedSelection:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'cannot read explicit seed list {path}: {exc}') from exc
    if not isinstance(payload, dict) or 'seeds' not in payload:
        raise ValueError(f'{path} must be a JSON object with a "seeds" list')
    try:
        return selection_from_seeds(payload['seeds'])
    except ValueError as exc:
        raise ValueError(f'{path}: {exc}') from exc
