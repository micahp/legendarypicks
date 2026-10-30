"""Stable named random streams for paired-seed model ablations."""
from __future__ import annotations

import hashlib
import json
import random


SCHEMA = 'lp.nfl.paired-random-streams.v1'


class PairedRandomStreams:
    """Derive an independent deterministic RNG from a seed, frozen snapshot, and semantic draw key."""

    def __init__(self, seed, snapshot_sha256):
        if type(seed) is not int:
            raise TypeError('paired random streams require an integer seed')
        if (not isinstance(snapshot_sha256, str) or len(snapshot_sha256) != 64
                or any(char not in '0123456789abcdef' for char in snapshot_sha256.lower())):
            raise ValueError('paired random streams require a 64-character frozen snapshot SHA-256')
        self.seed = seed
        self.snapshot_sha256 = snapshot_sha256
        self.root_sha256 = hashlib.sha256(
            f'{SCHEMA}:{seed}:{snapshot_sha256}'.encode('utf-8')
        ).hexdigest()

    def key(self, stream, *coordinates):
        """Return the stable hash for one semantic stream without advancing another stream."""
        if not isinstance(stream, str) or not stream:
            raise ValueError('random stream needs a non-empty semantic name')
        material = json.dumps([SCHEMA, self.seed, self.snapshot_sha256, stream, *coordinates],
                              sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        return hashlib.sha256(material.encode('utf-8')).hexdigest()

    def rng(self, stream, *coordinates):
        """Return a fresh RNG scoped to exactly one named draw site."""
        return random.Random(int(self.key(stream, *coordinates)[:16], 16))

    def manifest(self):
        return {'schema': SCHEMA, 'root_sha256': self.root_sha256,
                'snapshot_sha256': self.snapshot_sha256}
