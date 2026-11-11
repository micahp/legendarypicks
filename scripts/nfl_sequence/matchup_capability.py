"""Opponent-adjusted, mechanism-specific NFL strength model. Research-only.

Unlike the SLC event multiplier, this fits a joint conditional distribution:
P(outcome | situation, offense, defense) = softmax(log P_league(outcome | situation)
                                                 + offense_effect + defense_effect).
Offensive and defensive effects are regularized together, so they are estimated
after controlling for opponents and pre-play situation, not from team win rates.

No game simulator imports this file. No penalty, roster, or future-season data
is inferred. Source selection and strict time split belong to the scorer.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math


MODEL_ID = "slc-opponent-adjusted-conditional-multinomial-v0-research"
PRIOR_OBSERVATIONS = 40.0
RIDGE_STRENGTH = 60.0
MIN_CONTEXT_SUPPORT = 20
ITERATIONS = 16


@dataclass(frozen=True)
class Play:
    """One observed, correctly ordered, clean scrimmage play, never a sim draw."""

    season: int
    game_id: str
    play_id: int
    offense: str
    defense: str
    context: str
    outcome: str


def _softmax(logits):
    maximum = max(logits)
    weights = [math.exp(value - maximum) for value in logits]
    total = sum(weights)
    return tuple(weight / total for weight in weights)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class CapabilityModel:
    """Opponent-adjusted per-outcome offense and defense effects.

    Each effect is a category-specific log-odds residual relative to the same
    league situation model. L2 penalties and zero-centered vectors identify the
    coefficients and shrink sparse teams toward the neutral baseline.

    This is NOT a set of independent binary probabilities: all outcomes sum to 1.
    """

    def __init__(self, outcomes, base, global_base, offense, defense, manifest):
        self.outcomes = tuple(outcomes)
        self._indices = {name: i for i, name in enumerate(outcomes)}
        self.base = base
        self.global_base = tuple(global_base)
        self.offense = offense
        self.defense = defense
        self.manifest = manifest

    @classmethod
    def fit(cls, plays, outcomes, *, target_season,
            prior=PRIOR_OBSERVATIONS, ridge=RIDGE_STRENGTH,
            min_context=MIN_CONTEXT_SUPPORT, iterations=ITERATIONS):
        plays = tuple(plays)
        outcomes = tuple(outcomes)
        if not plays or len(outcomes) < 2 or len(outcomes) != len(set(outcomes)):
            raise ValueError("need observed plays and at least two distinct outcomes")
        if (not math.isfinite(prior) or prior <= 0 or not math.isfinite(ridge) or ridge <= 0
                or min_context < 1 or iterations < 1):
            raise ValueError("prior/ridge must be positive and finite; min support and iterations >= 1")
        if not isinstance(target_season, int):
            raise ValueError("target_season must be an integer")
        if any(not (p.offense and p.defense and p.context and p.game_id) for p in plays):
            raise ValueError("plays require offense, defense, game identity and context")
        if any(p.offense == p.defense for p in plays):
            raise ValueError("offense and defense cannot be the same team")
        if any(p.season >= target_season for p in plays):
            raise ValueError("training contains holdout season or future plays")
        if any(p.outcome not in outcomes for p in plays):
            raise ValueError("training contains outcome outside frozen vocabulary")
        unique_ids = {(p.game_id, p.play_id) for p in plays}
        if len(unique_ids) != len(plays):
            raise ValueError("duplicate source game/play identities")

        k = len(outcomes)
        ids = {name: i for i, name in enumerate(outcomes)}
        global_count = Counter(p.outcome for p in plays)
        # Half-count smoothing makes even unobserved event classes possible.
        global_base = tuple((global_count[outcome] + 0.5) / (len(plays) + k * 0.5)
                            for outcome in outcomes)
        contexts = defaultdict(Counter)
        team_index = {"offense": defaultdict(list), "defense": defaultdict(list)}
        for i, p in enumerate(plays):
            contexts[p.context][p.outcome] += 1
            team_index["offense"][p.offense].append(i)
            team_index["defense"][p.defense].append(i)

        base = {}
        for context, counts in contexts.items():
            n = sum(counts.values())
            if n < min_context:
                continue
            base[context] = tuple((counts[outcome] + prior * global_base[j]) / (n + prior)
                                  for j, outcome in enumerate(outcomes))
        baseline_logit = {context: tuple(math.log(p) for p in probabilities)
                          for context, probabilities in base.items()}
        global_logit = tuple(math.log(p) for p in global_base)
        y = [ids[p.outcome] for p in plays]

        offense = {team: [0.0] * k for team in team_index["offense"]}
        defense = {team: [0.0] * k for team in team_index["defense"]}
        for _ in range(iterations):
            # Alternating updates condition each team on every opposing team,
            # rather than multiplying two independently estimated team rates.
            for side, coefficients, other_coefficients in (
                    ("offense", offense, defense),
                    ("defense", defense, offense)):
                for team in sorted(coefficients):
                    gradient = [-ridge * value for value in coefficients[team]]
                    curvature = [ridge] * k
                    for index in team_index[side][team]:
                        p = plays[index]
                        context_logit = baseline_logit.get(p.context, global_logit)
                        other = other_coefficients[p.defense if side == "offense" else p.offense]
                        probabilities = _softmax(
                            [context_logit[j] + coefficients[team][j] + other[j] for j in range(k)])
                        for j in range(k):
                            gradient[j] += (1 if y[index] == j else 0) - probabilities[j]
                            curvature[j] += probabilities[j] * (1.0 - probabilities[j])
                    proposed = [coefficients[team][j]
                                + 0.65 * max(-1.0, min(1.0, gradient[j] / curvature[j]))
                                for j in range(k)]
                    center = sum(proposed) / k
                    coefficients[team] = [value - center for value in proposed]

        off = {team: tuple(values) for team, values in sorted(offense.items())}
        defe = {team: tuple(values) for team, values in sorted(defense.items())}
        manifest = {
            "model": MODEL_ID, "target_season": target_season,
            "fit_seasons": sorted({p.season for p in plays}),
            "plays": len(plays), "games": len({p.game_id for p in plays}),
            "context_count": len(contexts),
            "contexts_with_support": len(base),
            "prior_observations": float(prior), "ridge_strength": float(ridge),
            "min_context_support": int(min_context), "iterations": int(iterations),
            "outcomes": list(outcomes),
            "offense_team_support": dict(sorted((team, len(indices)) for team, indices
                                                 in team_index["offense"].items())),
            "defense_team_support": dict(sorted((team, len(indices)) for team, indices
                                                 in team_index["defense"].items())),
        }
        manifest["fit_sha256"] = _hash({"manifest": manifest, "global": global_base, "base": base,
                                        "offense": off, "defense": defe})
        return cls(outcomes, base, global_base, off, defe, manifest)

    def predict(self, context, offense, defense, *, mode="matchup"):
        """Probability dictionary for the frozen outcome vocabulary.

        league: situation only; offense/defense: one side's residual;
        matchup: both. Missing teams and cells have explicit zero-effect
        fallback and never borrow another club's rating.
        """
        if mode not in ("league", "offense", "defense", "matchup"):
            raise ValueError(f"unsupported mode: {mode}")
        base = self.base.get(context, self.global_base)
        a = self.offense.get(offense) if mode in ("offense", "matchup") else None
        b = self.defense.get(defense) if mode in ("defense", "matchup") else None
        logits = [math.log(p) + (a[j] if a else 0.0) + (b[j] if b else 0.0)
                  for j, p in enumerate(base)]
        return dict(zip(self.outcomes, _softmax(logits)))

    def trace(self, context, offense, defense):
        return {
            "context": context, "offense": offense, "defense": defense,
            "fallbacks": {
                "context": context not in self.base,
                "offense": offense not in self.offense,
                "defense": defense not in self.defense,
            },
            "league": self.predict(context, offense, defense, mode="league"),
            "offense_only": self.predict(context, offense, defense, mode="offense"),
            "defense_only": self.predict(context, offense, defense, mode="defense"),
            "matchup": self.predict(context, offense, defense, mode="matchup"),
        }
