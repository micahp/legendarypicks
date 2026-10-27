"""Small, deterministic renewal models for fixed-strength NHL event bundles."""

from __future__ import annotations

import hashlib
import math
import random
import bisect
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


MODEL_VERSION = "nhl-5v5-autonomous-renewal-v1"
PAIRED_EXPERIMENT_VERSION = "nhl-5v5-arrival-paired-crn-v1"
PERIOD_SECONDS = 1200
MIN_CONTEXT_BUNDLES = 100
DIRICHLET_ALPHA = 0.5
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20261027

FAMILIES = (
    "goal", "shot-on-goal", "missed-shot", "blocked-shot", "faceoff",
    "stoppage", "hit", "giveaway", "takeaway", "other",
)
OWNER_DOMAINS = {
    "goal": ("home", "away"),
    "shot-on-goal": ("home", "away"),
    "missed-shot": ("home", "away"),
    "blocked-shot": ("home", "away"),
    "faceoff": ("home", "away"),
    "stoppage": ("home", "away", "unknown"),
    "hit": ("home", "away"),
    "giveaway": ("home", "away"),
    "takeaway": ("home", "away"),
    "other": ("home", "away", "unknown"),
}
SHOT_ATTEMPT_FAMILIES = frozenset({"goal", "shot-on-goal", "missed-shot", "blocked-shot"})
SOG_FAMILIES = frozenset({"goal", "shot-on-goal"})


@dataclass(frozen=True)
class Token:
    family: str
    owner: str

    def __post_init__(self) -> None:
        if self.family not in FAMILIES:
            raise ValueError(f"unsupported event family {self.family!r}")
        if self.owner not in OWNER_DOMAINS[self.family]:
            raise ValueError(f"unsupported owner {self.owner!r} for {self.family}")


@dataclass(frozen=True)
class Context:
    previous_family: str
    possession_known: bool
    score_diff: int
    clock_bucket: int

    def __post_init__(self) -> None:
        if self.previous_family not in FAMILIES and self.previous_family != "start":
            raise ValueError(f"unsupported previous family {self.previous_family!r}")
        if not isinstance(self.score_diff, int):
            raise ValueError("score difference must be an integer")
        if self.clock_bucket not in range(4):
            raise ValueError("clock bucket must be in 0..3")

    @property
    def score_state(self) -> str:
        return score_state_from_diff(self.score_diff)


@dataclass(frozen=True)
class Transition:
    game_id: str
    period: int
    gap_seconds: int
    context: Context
    mark: tuple[Token, ...]

    def __post_init__(self) -> None:
        if self.period not in (1, 2, 3):
            raise ValueError("only regulation periods 1-3 are supported")
        if not 1 <= self.gap_seconds <= PERIOD_SECONDS:
            raise ValueError("arrival gap must be a positive whole number of seconds")
        if not self.mark:
            raise ValueError("event bundle mark cannot be empty")


def context_keys(context: Context) -> tuple[tuple[object, ...], ...]:
    """Return the preregistered A1 hierarchy, most specific first."""
    return (
        ("exact", context.previous_family, context.possession_known,
         context.score_state, context.clock_bucket),
        ("family_possession", context.previous_family, context.possession_known),
        ("family", context.previous_family),
        ("pooled",),
    )


def score_state_from_diff(home_minus_away: int) -> str:
    if home_minus_away > 0:
        return "home-leading"
    if home_minus_away < 0:
        return "away-leading"
    return "tied"


def update_context(context: Context, mark: Sequence[Token], arrival_second: int) -> Context:
    """Advance score, possession-known proxy and last family from one sampled bundle."""
    possession_known = context.possession_known
    score_diff = context.score_diff
    for token in mark:
        if token.family == "goal":
            score_diff += 1 if token.owner == "home" else -1
            possession_known = False
        elif token.family == "faceoff":
            possession_known = token.owner in {"home", "away"}
        elif token.family in {"giveaway", "takeaway"}:
            possession_known = token.owner in {"home", "away"}
        elif token.family in {"shot-on-goal", "missed-shot", "blocked-shot", "stoppage"}:
            possession_known = False
    return Context(
        previous_family=mark[-1].family,
        possession_known=possession_known,
        score_diff=score_diff,
        clock_bucket=min(3, max(0, arrival_second // 300)),
    )


@dataclass
class _Counts:
    n: int = 0
    gaps: Counter[int] | None = None
    sizes: Counter[int] | None = None
    families: dict[tuple[int, tuple[str, ...]], Counter[str]] | None = None
    owners: dict[tuple[int, tuple[str, ...], str], Counter[str]] | None = None

    def __post_init__(self) -> None:
        if self.gaps is None:
            self.gaps = Counter()
        if self.sizes is None:
            self.sizes = Counter()
        if self.families is None:
            self.families = defaultdict(Counter)
        if self.owners is None:
            self.owners = defaultdict(Counter)

    def add(self, transition: Transition) -> None:
        self.n += 1
        self.gaps[transition.gap_seconds] += 1
        self.sizes[len(transition.mark)] += 1
        prefix: list[str] = []
        for position, token in enumerate(transition.mark):
            self.families[(position, tuple(prefix))][token.family] += 1
            self.owners[(position, tuple(prefix), token.family)][token.owner] += 1
            prefix.append(token.family)


class RenewalModel:
    """A0 pooled or A1 context-conditioned discrete renewal model."""

    def __init__(self, name: str, *, alpha: float = DIRICHLET_ALPHA) -> None:
        if name not in {"A0", "A1"}:
            raise ValueError("model name must be A0 or A1")
        if alpha <= 0:
            raise ValueError("Dirichlet alpha must be positive")
        self.name = name
        self.alpha = float(alpha)
        self.stats: dict[tuple[object, ...], _Counts] = defaultdict(_Counts)
        self.max_bundle_size = 0
        self.training_transitions = 0
        self._gap_cdfs: dict[tuple[object, ...], tuple[float, ...]] = {}
        self._size_cdfs: dict[tuple[object, ...], tuple[float, ...]] = {}
        self._family_cdfs: dict[tuple[tuple[object, ...], int, tuple[str, ...]], tuple[float, ...]] = {}
        self._owner_cdfs: dict[tuple[tuple[object, ...], int, tuple[str, ...], str], tuple[float, ...]] = {}

    def fit(self, transitions: Iterable[Transition]) -> None:
        rows = list(transitions)
        if not rows:
            raise ValueError("cannot fit an arrival model without transitions")
        self.stats = defaultdict(_Counts)
        self._gap_cdfs.clear()
        self._size_cdfs.clear()
        self._family_cdfs.clear()
        self._owner_cdfs.clear()
        self.max_bundle_size = max(len(row.mark) for row in rows)
        for row in rows:
            for key in context_keys(row.context):
                self.stats[key].add(row)
        if not self.stats[("pooled",)].n:
            raise AssertionError("pooled training counts are empty")
        self.training_transitions = len(rows)

    def selected_key(self, context: Context) -> tuple[object, ...]:
        if self.name == "A0":
            return ("pooled",)
        for key in context_keys(context):
            if self.stats.get(key) and self.stats[key].n >= MIN_CONTEXT_BUNDLES:
                return key
        return ("pooled",)

    def fallback_level(self, context: Context) -> str:
        key = self.selected_key(context)
        return str(key[0])

    def _probability(self, count: int, total: int, categories: int) -> float:
        return (count + self.alpha) / (total + self.alpha * categories)

    def gap_probability(self, context: Context, seconds: int) -> float:
        if not 1 <= seconds <= PERIOD_SECONDS:
            return 0.0
        counts = self.stats[self.selected_key(context)].gaps
        return self._probability(counts[seconds], sum(counts.values()), PERIOD_SECONDS)

    def sample_gap(self, context: Context, rng: random.Random) -> int:
        key = self.selected_key(context)
        cdf = self._gap_cdfs.get(key)
        if cdf is None:
            counts = self.stats[key].gaps
            cdf = _make_cdf([counts[gap] + self.alpha
                             for gap in range(1, PERIOD_SECONDS + 1)])
            self._gap_cdfs[key] = cdf
        return _sample_cdf(cdf, rng) + 1

    def _size_probability(self, key: tuple[object, ...], size: int) -> float:
        counts = self.stats[key].sizes
        domain_size = max(1, self.max_bundle_size)
        if not 1 <= size <= domain_size:
            return 0.0
        return self._probability(counts[size], sum(counts.values()), domain_size)

    def _family_counts(self, key: tuple[object, ...], position: int,
                       prefix: tuple[str, ...]) -> Counter[str]:
        return self.stats[key].families.get((position, prefix), Counter())

    def _owner_counts(self, key: tuple[object, ...], position: int,
                      prefix: tuple[str, ...], family: str) -> Counter[str]:
        return self.stats[key].owners.get((position, prefix, family), Counter())

    def mark_log_probability(self, context: Context, mark: Sequence[Token]) -> float:
        key = self.selected_key(context)
        size_p = self._size_probability(key, len(mark))
        if size_p <= 0:
            return -math.inf
        total = math.log(size_p)
        prefix: list[str] = []
        for position, token in enumerate(mark):
            family_counts = self._family_counts(key, position, tuple(prefix))
            family_p = self._probability(family_counts[token.family], sum(family_counts.values()),
                                          len(FAMILIES))
            owner_counts = self._owner_counts(key, position, tuple(prefix), token.family)
            domain = OWNER_DOMAINS[token.family]
            owner_p = self._probability(owner_counts[token.owner], sum(owner_counts.values()),
                                        len(domain))
            total += math.log(family_p) + math.log(owner_p)
            prefix.append(token.family)
        return total

    def sample_mark(self, context: Context, rng: random.Random) -> tuple[Token, ...]:
        key = self.selected_key(context)
        size_cdf = self._size_cdfs.get(key)
        if size_cdf is None:
            size_counts = self.stats[key].sizes
            size_cdf = _make_cdf([size_counts[size] + self.alpha
                                  for size in range(1, self.max_bundle_size + 1)])
            self._size_cdfs[key] = size_cdf
        size = _sample_cdf(size_cdf, rng) + 1
        prefix: list[str] = []
        result: list[Token] = []
        for position in range(size):
            prefix_key = tuple(prefix)
            family_key = (key, position, prefix_key)
            family_cdf = self._family_cdfs.get(family_key)
            if family_cdf is None:
                family_counts = self._family_counts(key, position, prefix_key)
                family_cdf = _make_cdf([family_counts[family] + self.alpha
                                         for family in FAMILIES])
                self._family_cdfs[family_key] = family_cdf
            family = FAMILIES[_sample_cdf(family_cdf, rng)]
            domain = OWNER_DOMAINS[family]
            owner_key = (key, position, prefix_key, family)
            owner_cdf = self._owner_cdfs.get(owner_key)
            if owner_cdf is None:
                owner_counts = self._owner_counts(key, position, prefix_key, family)
                owner_cdf = _make_cdf([owner_counts[owner] + self.alpha for owner in domain])
                self._owner_cdfs[owner_key] = owner_cdf
            owner = domain[_sample_cdf(owner_cdf, rng)]
            result.append(Token(family, owner))
            prefix.append(family)
        return tuple(result)

    def gap_log_probability(self, context: Context, seconds: int) -> float:
        probability = self.gap_probability(context, seconds)
        return math.log(probability) if probability > 0 else -math.inf

    def manifest(self) -> dict[str, object]:
        return {
            "name": self.name,
            "model_version": MODEL_VERSION,
            "training_transitions": self.training_transitions,
            "max_training_bundle_size": self.max_bundle_size,
            "minimum_context_bundles": MIN_CONTEXT_BUNDLES,
            "dirichlet_alpha": self.alpha,
            "context_hierarchy": ["exact", "family_possession", "family", "pooled"],
        }


def _sample_weighted(weights: Sequence[float], rng: random.Random) -> int:
    total = sum(weights)
    if total <= 0:
        raise ValueError("categorical weights must have positive sum")
    target = rng.random() * total
    cumulative = 0.0
    for index, weight in enumerate(weights):
        cumulative += weight
        if target < cumulative:
            return index
    return len(weights) - 1


def _make_cdf(weights: Sequence[float]) -> tuple[float, ...]:
    total = sum(weights)
    if total <= 0:
        raise ValueError("categorical weights must have positive sum")
    cumulative = []
    current = 0.0
    for weight in weights:
        current += weight / total
        cumulative.append(current)
    cumulative[-1] = 1.0
    return tuple(cumulative)


def _sample_cdf(cdf: Sequence[float], rng: random.Random) -> int:
    return min(len(cdf) - 1, bisect.bisect_left(cdf, rng.random()))


def sample_trace(model: RenewalModel, seed: int, *, horizon: int = PERIOD_SECONDS,
                 initial: Context | None = None) -> list[tuple[int, tuple[Token, ...]]]:
    if not 1 <= horizon <= PERIOD_SECONDS:
        raise ValueError("trace horizon must be in 1..1200 seconds")
    context = initial or Context("faceoff", True, 0, 0)
    rng = random.Random(seed)
    time = 0
    trace: list[tuple[int, tuple[Token, ...]]] = []
    while time < horizon:
        gap = model.sample_gap(context, rng)
        arrival = time + gap
        if arrival >= horizon:
            break
        mark = model.sample_mark(context, rng)
        trace.append((arrival, mark))
        context = update_context(context, mark, arrival)
        time = arrival
        if len(trace) > horizon:
            raise AssertionError("positive gaps produced more events than clock seconds")
    validate_trace(trace, horizon=horizon)
    return trace


def validate_trace(trace: Sequence[tuple[int, Sequence[Token]]], *, horizon: int) -> None:
    previous = 0
    for second, mark in trace:
        if not previous < second < horizon:
            raise ValueError("trace times must be strictly increasing inside the period")
        if not mark:
            raise ValueError("trace contains an empty event bundle")
        previous = second
    goals = sum(token.family == "goal" for _, mark in trace for token in mark)
    sog = sum(token.family in SOG_FAMILIES for _, mark in trace for token in mark)
    attempts = sum(token.family in SHOT_ATTEMPT_FAMILIES for _, mark in trace for token in mark)
    if goals > sog or sog > attempts:
        raise ValueError("generated goals, SOG, and shot attempts do not reconcile")


def trace_counts(trace: Sequence[tuple[int, Sequence[Token]]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for _, mark in trace:
        counts["bundle_count"] += 1
        for token in mark:
            counts[f"family:{token.family}"] += 1
            if token.family in SHOT_ATTEMPT_FAMILIES:
                counts["shot_attempts"] += 1
            if token.family in SOG_FAMILIES:
                counts["sog"] += 1
            if token.family == "goal":
                counts["goals"] += 1
    return dict(counts)


def crps(samples: Sequence[float], observation: float) -> float:
    if not samples:
        raise ValueError("CRPS requires at least one forecast sample")
    first = sum(abs(float(sample) - observation) for sample in samples) / len(samples)
    second = sum(abs(float(left) - float(right)) for left in samples for right in samples)
    return first - second / (2 * len(samples) ** 2)


def paired_game_bootstrap(candidate_a: Mapping[str, tuple[float, float]],
                          candidate_b: Mapping[str, tuple[float, float]], *,
                          replicates: int = BOOTSTRAP_REPLICATES,
                          seed: int = BOOTSTRAP_SEED) -> dict[str, float | int]:
    """CI for B-A; values are (loss, exposure weight) aggregated within game."""
    games = sorted(set(candidate_a) & set(candidate_b))
    if not games or replicates < 1:
        raise ValueError("paired bootstrap needs common games and positive replicates")
    rng = random.Random(seed)
    deltas = []
    for _ in range(replicates):
        sampled = [games[rng.randrange(len(games))] for _ in games]
        sums = [0.0, 0.0]
        weights = [0.0, 0.0]
        for game in sampled:
            for index, mapping in enumerate((candidate_a, candidate_b)):
                loss, weight = mapping[game]
                sums[index] += loss
                weights[index] += weight
        if weights[0] > 0 and weights[1] > 0:
            deltas.append(sums[1] / weights[1] - sums[0] / weights[0])
    if not deltas:
        raise ValueError("paired bootstrap produced no finite replicate")
    deltas.sort()
    return {
        "replicates": len(deltas),
        "seed": seed,
        "mean_delta_b_minus_a": sum(deltas) / len(deltas),
        "ci95_low": deltas[int(0.025 * (len(deltas) - 1))],
        "ci95_high": deltas[int(0.975 * (len(deltas) - 1))],
    }


def paired_crps_bootstrap(candidate_a: Mapping[str, Sequence[float]],
                          candidate_b: Mapping[str, Sequence[float]], *,
                          replicates: int = BOOTSTRAP_REPLICATES,
                          seed: int = BOOTSTRAP_SEED) -> dict[str, float | int]:
    """CI for mean paired period CRPS difference B-A, clustered by game."""
    games = sorted(set(candidate_a) & set(candidate_b))
    if not games or replicates < 1:
        raise ValueError("paired CRPS bootstrap needs common games and positive replicates")
    rng = random.Random(seed)
    deltas: list[float] = []
    for _ in range(replicates):
        sampled = [games[rng.randrange(len(games))] for _ in games]
        rows_a = [score for game in sampled for score in candidate_a[game]]
        rows_b = [score for game in sampled for score in candidate_b[game]]
        if rows_a and rows_b:
            deltas.append(sum(rows_b) / len(rows_b) - sum(rows_a) / len(rows_a))
    deltas.sort()
    return {
        "replicates": len(deltas),
        "seed": seed,
        "mean_delta_b_minus_a": sum(deltas) / len(deltas),
        "ci95_low": deltas[int(0.025 * (len(deltas) - 1))],
        "ci95_high": deltas[int(0.975 * (len(deltas) - 1))],
    }


def common_random_seed(game_id: str, period: int, replicate: int) -> int:
    raw = f"{PAIRED_EXPERIMENT_VERSION}|{game_id}|{period}|{replicate}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
