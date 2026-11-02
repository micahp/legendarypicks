"""PBV1 package sampler for the SLC personnel draw (research flag `--playcall-pbv1-package`, off by default).

The sampler is the pre-registered PBV1 model (docs/research/PBV1-SAMPLER-SPEC-2026-11-02.md), refitted on the frozen training table
docs/research/pbv1-package-integration-2026-11-02/pbv1_training_plays.csv, whose SHA-256 is checked before use. For a scrimmage
play it draws the RB-plus-TE package code (the SLC personnel vocabulary, for example '11') from the play's cell: play family,
down, HPV1 distance bucket and red zone. The cell is shrunk toward its parent (family, down) with K = 20. A package never observed
for the parent gets no mass, the spec's support rule.

Training is as of the game's season: only seasons before it are fitted, as in the PBV1 folds. The draw uses its own substream,
keyed on the play's seed text with the suffix ':pbv1', so no other draw changes. Every play that cannot be drawn is counted under
a named reason and keeps the formation draw, so no fallback is silent.
"""
import collections
import csv
import hashlib
import random

K = 20  # the primary pseudo-count of the spec, fixed before fitting and not tuned
MODEL_VERSION = 'pbv1-package-sampler-spec-2026-11-02'
TRAINING_TABLE = 'docs/research/pbv1-package-integration-2026-11-02/pbv1_training_plays.csv'
TABLE_SHA256 = 'ab875384a82ea1d6472e12007d0e1f79316508861a1843730253f40253d8a993'  # pbv1_training_manifest.json csv_sha256
DISTANCE_BUCKETS = ((1, 2, 'd1_2'), (3, 4, 'd3_4'), (5, 6, 'd5_6'), (7, 9, 'd7_9'), (10, 14, 'd10_14'), (15, 99, 'd15p'))
RED_ZONE_YARDS = 20  # HPV1: red zone is yardline_100 <= 20


def distance_bucket(togo):
    """The HPV1 distance bucket of yards to go, or None outside the buckets (counted by the caller, never guessed)."""
    yards = int(togo)
    for low, high, label in DISTANCE_BUCKETS:
        if low <= yards <= high:
            return label
    return None


def load(path, expected_sha256, cutoff_season, target='package'):
    """Refit the PBV1 model on seasons before cutoff_season from the frozen table. Refuses any other file contents.

    `target` names the package column: 'package' is the RB-only code the SLC uses; 'package_comparable' is RB plus FB, the
    primary PBV1 target, read only by the equality test against the frozen evaluation."""
    with open(path, 'rb') as handle:
        raw = handle.read()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise ValueError(f'PBV1 training table hash {digest} does not match the pinned {expected_sha256}')
    cell, parent, fitted = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter), 0
    for row in csv.DictReader(raw.decode('utf-8').splitlines()):
        if int(row['season']) >= int(cutoff_season):
            continue
        key = (row['family'], row['down'], row['distance'], int(row['red_zone']))
        cell[key][row[target]] += 1
        parent[key[:2]][row[target]] += 1
        fitted += 1
    if not fitted:
        raise ValueError(f'PBV1 has no training plays before the {cutoff_season} season')
    return Model(cell, parent, fitted, int(cutoff_season), digest, target)


class Model:
    """The fitted tables, shared by every game of a batch. Per-game counters live in Draws."""

    def __init__(self, cell, parent, fitted, cutoff_season, table_sha256, target='package'):
        self.cell, self.parent = cell, parent
        self.fitted_plays = fitted
        self.cutoff_season = cutoff_season
        self.table_sha256 = table_sha256
        self.target = target
        self.version = MODEL_VERSION

    def distribution(self, cell_key):
        """The shrunk package distribution of a cell, or None when its parent has no training plays."""
        parent_counts = self.parent.get(cell_key[:2])
        if not parent_counts:
            return None
        parent_total = sum(parent_counts.values())
        cell_counts = self.cell.get(cell_key, collections.Counter())
        cell_total = sum(cell_counts.values())
        return {package: (cell_counts.get(package, 0) + K * count / parent_total) / (cell_total + K)
                for package, count in parent_counts.items()}

    def describe(self):
        return {'model': self.version, 'training_table_sha256': self.table_sha256, 'training_cutoff_season': self.cutoff_season,
                'fitted_plays': self.fitted_plays, 'K': K, 'target_column': self.target}


class Draws:
    """Per-game draws with named counters. Fallbacks keep the formation draw and are reported, never hidden."""

    def __init__(self, model):
        self.model = model
        self.usage = collections.Counter()
        self.packages = collections.Counter()

    def draw(self, intent, down, togo, yardline_100, seed_text):
        """A package code for this play, or None (counted) when the cell cannot be drawn."""
        family = 'run' if intent == 'run' else 'pass'
        bucket = distance_bucket(togo)
        if bucket is None:
            self.usage['fallback_distance_outside_buckets'] += 1
            return None
        if int(down) not in (1, 2, 3, 4):
            self.usage['fallback_down_unknown'] += 1
            return None
        cell_key = (family, str(int(down)), bucket, int(float(yardline_100) <= RED_ZONE_YARDS))
        dist = self.model.distribution(cell_key)
        if not dist:
            self.usage['fallback_parent_unseen'] += 1
            return None
        rng = random.Random(int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], 'big'))
        labels = sorted(dist)
        package = rng.choices(labels, weights=[dist[label] for label in labels], k=1)[0]
        self.usage['drawn'] += 1
        self.packages[package] += 1
        return package

    def report(self):
        return {'usage': dict(self.usage), 'packages': dict(sorted(self.packages.items())), **self.model.describe()}
