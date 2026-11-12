# SLC V1.7: penalty probability-model branch

**Branch:** `feature/slc-v1.7-penalty-model-2026-11-12`  
**Base:** `slc-v1.6`, unchanged.  
**Status:** Model/sampler/CLI code complete for **single verified foul per opportunity**; not yet fitted on cleaned data, evaluated, integrated or release validated.

This work is intentionally independent from the agent preparing the historical penalty corpus. The current model predicts *whether a penalty occurs and its committing side/type*. It does not accept/decline, assess yards, award first downs, alter clock/down/possession, or affect the frozen V1.6 simulation.

## Exact data handoff: one JSONL record per **eligible opportunity and phase**

The final training dataset must include verified *no-foul* rows, not just PBP rows with `penalty=1`. A source PBP row is not automatically a unique opportunity, especially with `no_play`, dead-ball events, multiple fouls, accepted/declined flags and null source fields.

Each JSONL record looks like:

```json
{
  "context": {
    "phase": "pre_snap",
    "rule_era": 2024,
    "offense_team": "ARI",
    "defense_team": "DAL",
    "down": 1,
    "to_go": 10,
    "yardline_100": 65,
    "play_class": "pre_snap"
  },
  "opportunity_id": "2024_01_ARI_DAL:103:presnap",
  "game_kickoff_utc": "2024-09-08T20:25:00+00:00",
  "source_published_utc": "2024-09-09T14:00:00+00:00",
  "outcome": "offense:false_start",
  "label_verified": true,
  "foul_count": 1,
  "disposition": "accepted"
}
```

For a verified no-foul pre-snap opportunity, use `outcome="none"`, `foul_count=0` and `disposition="none"`. A live-ball row uses `phase="live_ball"` and `play_class` one of `run`, `dropback`, or `kick`. Only create a live-ball opportunity when a legally modeled play has reached that stage. If a pre-snap penalty prevents a snap, there is no corresponding live-ball opportunity for that attempted snap.

**Source requirements:** stable season/game/ordered-play IDs, offense and defense team IDs, before-play context, rule-era year, verified foul event and disposition, a real source publication vintage, and a frozen source manifest SHA-256. Game kickoff time alone is insufficient evidence that a source revision existed before that kickoff.

The trainer rejects duplicate opportunity IDs per phase, future games, source vintages beyond the cutoff, unverified labels, unsupported types, ambiguous/offsetting dispositions, and multiple-foul opportunities. Do not force unknown or excluded events into `none`. The corpus builder must report every exclusion by season, foul type and reason, along with the eligible denominator retained in the fit.

### V1.7 model taxonomy (initial supported subset)

`pre_snap`:
- Offensive: `false_start`, `delay_of_game`
- Defensive: `encroachment`, `neutral_zone_infraction`

`live_ball`:
- Offensive: `offensive_holding`, `offensive_pass_interference`, `illegal_block`, `intentional_grounding`, `illegal_formation`, `illegal_shift`, `illegal_motion`
- Defensive: `defensive_holding`, `defensive_pass_interference`, `illegal_contact`, `roughing_passer`, `offside`

These are not a claim of complete 2026 NFL foul coverage. Every type and its dead/live timing needs a verified mapping from the official rules and data agent's classifier. Offsetting/multiple fouls, special-teams-specific penalties, dead-ball-after-play fouls and other categories still need a separate, validated model/engine extension before V1.7 can freeze.

## Model implementation

- `scripts/nfl_sequence/penalty_fit.py`: a phase-specific categorical model, smoothed along rule era, intended play class, down, and distance/field bucket, with shrunk committing-team offense/defense foul propensities. It never consumes post-play outcome fields as a predictor.
- `scripts/nfl_sequence/penalty_sampler.py`: disabled-by-default proposal sampler with a separate, deterministic SHA-256-namespaced RNG stream per phase and unique play opportunity. It does not consume V1.6 random draws.
- `scripts/nfl_sequence/penalty_train.py`: offline JSONL training and holdout evaluation, immutable model JSON and SHA manifest. It reports categorical log loss, multiclass Brier and any-foul Brier for context-only versus team-adjusted candidates.
- `scripts/nfl_sequence/test_penalty_fit.py`, `test_penalty_sampler.py`, `test_penalty_train.py`: model data gates, cutoff leakage, denominator handling, deterministic sampling, baseline-disable and serialization regression tests.

The stage model currently supports **at most one classified foul per opportunity**. This is an explicit implementation limit, not an assumption that NFL penalties are independent or always single-foul.

### Training, once verified data is ready

```bash
python3 scripts/nfl_sequence/penalty_train.py \
  --train-jsonl /path/to/verified-opportunities-train.jsonl \
  --holdout-jsonl /path/to/verified-opportunities-2025.jsonl \
  --as-of-utc 2025-01-01T00:00:00+00:00 \
  --source-sha256 <64-character-manifest-hash> \
  --model-out /path/to/penalty-v17-candidate.json
```

The input train rows must have game kickoff AND source evidence publication dates strictly before the fit cutoff. Holdout rows must be after the fit cutoff. Do not train from 2026 snapshots whose source publication could be after the target game's cutoff. This CLI intentionally reports `research_only_not_release_validated` even when it generates scores.

Tests to execute in the cloned repo:

```bash
PYTHONPATH=scripts/nfl_sequence python3 -m unittest \
  test_penalty_fit test_penalty_sampler test_penalty_train
```

## Agent/model boundary and remaining V1.7 work

**Data agent owns:** source capture, disposition verification, unique pre-snap/live-ball opportunities, no-foul denominators, foul taxonomy, source cutoff/vintage manifest, historical 2024/2025 held-out datasets, and exclusion/coverage accounting.

**This branch owns:** probability model, shrunk team tendencies, offline scoring and independent deterministic proposal sampling. Model fitting cannot be called validated until real chronological holdouts compare it against context-only and league controls.

**Not yet built:** deterministic NFL Rule 14 enforcement and statistical-accounting engine; acceptance/decline logic; offsetting/multiple-foul process; complete special-teams and dead-ball foul coverage; integration into pre-snap/live-ball simulation transitions; broad paired full-game validation. The existing V1.6 game-state code must stay untouched until those components pass legal transition fixtures.

### Freeze gates

1. Source and cutoff manifest complete; source-dependent denominator and eligibility validated.
2. Fully executable automated tests (not just added test files) and year-heldout proper scores.
3. Every supported foul and acceptance/decline/offsetting transition legal and stat-correct, with unsupported combinations blocked explicitly.
4. Penalties OFF: identical frozen V1.6 sampled games and RNG histories.
5. Penalties ON: historical penalty frequencies, first downs, drive/clock behavior and scoring improve or remain within prespecified non-regression bounds on independent holdouts.
6. Immutable fit, code/source hashes, seed ledgers, manifests and a recorded V1.7 freeze decision.

**No claim is made that the current probability branch satisfies these release gates.**
