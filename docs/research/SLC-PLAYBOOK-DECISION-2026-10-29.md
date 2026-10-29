# SLC team playbooks: decision, 2026-10-29

Scope decision for SLC v1. It is recorded so it can be overturned, and it is not a claim that the playbooks are integrated.

## What the playbooks contain

Gridiron Physics `research/nfl-team-season-playbooks-2026-10-27` at `0c1541c`: 76 team-season files under `data/playbooks/`, for
example `KC-2025.json`. Each has an offense and a defense block. The offense block counts categories (formation, personnel, motion,
play action, pass depth, pass location, route, air yards, red zone, goal line, no huddle, pass rate) with rates, Wilson intervals,
and the source play IDs for each category. The data is one season, 2025.

## What the engine consumes

- The play-call layer's covariates are the situation (down, distance, field position, score difference, quarter, clock), the
  team-by-down term, and the season term (`playcall_model.GROUP_NAMES`). Nothing else.
- The outcome draw is over (intent, event) cells. No formation, personnel, motion or route enters the engine. `e1_drive.py` and
  `game_state.py` both state that personnel is not conditioned.

## Decision

1. The team play-type tendency, meaning how often a team passes on each down, is already in the play-call artifact through the
   team-by-down term, fitted on 2010 to 2025 for the 2026 evaluation. A separate playbook pass-rate prior would count the same
   tendency twice, so it is not added.
2. Formations, personnel, motion and routes have no consumer in the engine. Using them needs an outcome model conditioned on
   formation, which is not built. Adding them as weights with no outcome dependence would be decorative, so they are not added.
3. The 2025 playbook files are admissible as prior-season inputs for a 2026 evaluation (the season is complete before 2026). They
   become usable only when a formation-conditioned outcome model exists, with its own cutoff audit and validation.

## What "not integrated" means here

Team play-type tendency is integrated through the fitted team-by-down term. Formation and personnel are not integrated, because the
engine has no model that uses them. That is the honest state, and the decision is yours to change. The change would be: build a
formation-conditioned outcome model from 2010 to 2025 play-by-play, with a cutoff audit per evaluation season, then test whether it
changes the event mix against the 2025 playbook shares.

## Evidence used

- `grep` of `formation` and `personnel` in `e1_drive.py`, `game_state.py`, `e2_reference.py`, `slc_playcall.py` and `pre_event.py`
  finds only documentation lines that say personnel is not conditioned.
- `playcall_model.GROUP_NAMES` lists the covariates above.
