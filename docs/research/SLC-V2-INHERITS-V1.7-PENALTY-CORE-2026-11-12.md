# V2 carries forward V1.7 shared 16-foul penalty core

The V2 branch must consume the same penalty model catalog, sampler, enforcement rules, and transition bridge that were introduced in V1.7, rather than reimplementing them and allowing the rule sets to diverge.

**V1.7 source:** `feature/slc-v1.7-penalty-model-2026-11-12` (16-rule enforcement PR #40; follow-up grounding correction after PR).  
**NFL ruleset:** 2026, Rules 4, 7, 8, 12, 14.  
**Source documentation:** `docs/research/SLC-V1.7-PENALTY-16-TYPE-ENFORCEMENT-2026-11-12.md` on the V1.7 branch.

The following files are copied **byte-identically** from the V1.7 branch:

- `penalty_fit.py`: model foul catalog and pure-Python, cutoff-safe fit.
- `penalty_sampler.py`: disabled-by-default, independent RNG proposal mechanism.
- `penalty_enforcement.py`: all 16 modeled foul types, NFL 2026 field/down transitions and fail-closed boundaries.
- `penalty_transition.py`: explicit-ruling adapter; no acceptance decision is inferred.
- The four matching `test_penalty_{fit,sampler,enforcement,transition}.py` suites.

**Integration status:** importing these modules does not enable penalty sampling in V2 or change its existing RNG, game simulation, strength model, or decisions. This patch is a *shared rules and implementation inheritance*, not a completed V2 penalty-aware full game. The V2 controller needs an explicit penalties-ON opt-in plus verified training model and legal game/clock/stat accounting before it can be evaluated as a penalized V2 model.

**Future model rule:** any model after V1.7 must use this shared catalog and enforcement engine. Do not fork a second rules table; pin the rules version and maintain cross-version parity fixtures. Freeze V1.6 and earlier independently.

Verification (source branch):

```bash
PYTHONPATH=scripts/nfl_sequence python -m unittest -v \
  test_penalty_fit test_penalty_sampler \
  test_penalty_enforcement test_penalty_transition
```

Before enabling V2 penalties, require: enabled-profile legal-transition full-game tests; disabled-profile V2 golden seeds exactly unchanged; held-out source/model metrics and source cutoff provenance; acceptance/decline/clock/statistics integration; and explicit handling or safe rejection of multi-foul, special-teams, possession-change and scoring exceptions.
