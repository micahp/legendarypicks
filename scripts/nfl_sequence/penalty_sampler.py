"""Isolated V1.7 penalty event proposal sampler.

This produces a *proposal*, never an enforced or credited penalty. No existing
V1.6 game-state path is touched. A future caller must feed proposals to a
rule-accurate enforcement engine, and refuse unsupported transitions.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random

from penalty_fit import Context, NO_FOUL, PenaltyModel, _utc
from penalty_scrimmage_kick import KICK_FOUL_YARDS
from penalty_enforcement import RULES



@dataclass(frozen=True)
class PenaltyProposal:
    opportunity_key: str
    phase: str
    outcome: str
    model_sha256: str | None
    source_sha256: str | None
    rng_namespace: str | None

    @property
    def has_foul(self) -> bool:
        return self.outcome != NO_FOUL

    @property
    def committing_side(self) -> str | None:
        return None if not self.has_foul else self.outcome.split(":", 1)[0]

    @property
    def foul_type(self) -> str | None:
        return None if not self.has_foul else self.outcome.split(":", 1)[1]


class PenaltySampler:
    """One independent deterministic draw per unique phase/opportunity.

    The stream is derived by SHA-256 from the seed, unique opportunity key,
    and pre-snap/live-ball phase. It cannot advance the existing SLC RNG.
    """

    def __init__(self, model: PenaltyModel | None, *, enabled: bool = False):
        self.enabled = bool(enabled)
        if self.enabled and (model is None or not model.fitted):
            raise ValueError("enabled V1.7 penalties require a fitted model")
        self.model = model
        self._model_hash = model.sha256() if self.enabled else None
        self.model_provenance = None

    @classmethod
    def from_artifacts(cls, *, model_path: str | Path, manifest_path: str | Path,
                       source_manifest_path: str | Path, as_of_utc: str) -> "PenaltySampler":
        """Load a fitted research model only when its provenance is consistent.

        This enables isolated proposals, not full-game enforcement or a release
        claim. The source manifest is checked byte-for-byte against the fit.
        """
        model = PenaltyModel.from_json(Path(model_path).read_text(encoding="utf-8"))
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        source_hash = hashlib.sha256(Path(source_manifest_path).read_bytes()).hexdigest()
        if manifest.get("status") != "research_only_not_release_validated":
            raise ValueError("expected a research-only penalty fit manifest")
        if manifest.get("model_sha256") != model.sha256():
            raise ValueError("penalty model hash does not match fit manifest")
        if (manifest.get("source_manifest_sha256") != source_hash
                or model.source_sha256 != source_hash):
            raise ValueError("penalty source manifest hash mismatch")
        if (manifest.get("train_before_utc") != model.train_before_utc
                or manifest.get("observed_opportunities") != model.opportunities):
            raise ValueError("penalty fit metadata does not match model")
        if _utc(as_of_utc) < _utc(model.train_before_utc):
            raise ValueError("penalty model was trained after the requested as-of time")
        sampler = cls(model, enabled=True)
        kick_key = json.dumps(["live_ball", "kick"])
        kick_opportunities = sum(model.context_counts.get(kick_key, {}).values())
        sampler.model_provenance = {
            "kick_opportunities": kick_opportunities,
            "kick_rate_status": ("research_uncalibrated_scrimmage_kick_backoff"
                                 if kick_opportunities == 0 else
                                 "kick_training_present_requires_holdout_validation"),
            "status": manifest["status"], "model_sha256": model.sha256(),
            "source_manifest_sha256": source_hash,
            "train_before_utc": model.train_before_utc,
            "observed_opportunities": model.opportunities,
        }
        return sampler

    def propose(self, context: Context, *, game_seed: int, opportunity_key: str) -> PenaltyProposal:
        if not isinstance(opportunity_key, str) or not opportunity_key.strip():
            raise ValueError("unique opportunity key is required")
        if not isinstance(game_seed, int) or isinstance(game_seed, bool):
            raise ValueError("game_seed must be an integer")
        if not self.enabled:
            return PenaltyProposal(opportunity_key, context.phase, NO_FOUL, None, None, None)

        namespace = f"slc-v1.7/penalty/{context.phase}"
        material = f"{namespace}|{game_seed}|{opportunity_key}"
        digest = hashlib.sha256(material.encode("utf-8")).digest()
        rng = random.Random(int.from_bytes(digest, "big"))
        if context.phase == 'live_ball':
            # Conditional support matters: a coarse pooled class model can
            # put DPI on a run, or intentional grounding on a punt. These
            # events are not physically possible on that snap. Retain their
            # probability mass as a no-foul opportunity rather than
            # renormalizing the remaining foul rates upward.
            allowed = (set(KICK_FOUL_YARDS) if context.play_class == 'kick' else {
                key for key, rule in RULES.items()
                if rule.phase == 'live_ball' and context.play_class in rule.play_classes
            })
            probs = self.model.predict(context)
            removed_mass = sum(
                chance for label, chance in probs.items()
                if label != NO_FOUL and tuple(label.split(':', 1)) not in allowed
            )
            cleaned = {
                label: chance for label, chance in probs.items()
                if label == NO_FOUL or tuple(label.split(':', 1)) in allowed
            }
            cleaned[NO_FOUL] = cleaned.get(NO_FOUL, 0.) + removed_mass
            threshold = rng.random()
            total = 0.
            result = NO_FOUL
            for label, chance in cleaned.items():
                total += chance
                if threshold < total:
                    result = label
                    break
        else:
            result = self.model.sample(context, rng)
        return PenaltyProposal(
            opportunity_key=opportunity_key, phase=context.phase, outcome=result,
            model_sha256=self._model_hash,
            source_sha256=self.model.source_sha256, rng_namespace=namespace)
