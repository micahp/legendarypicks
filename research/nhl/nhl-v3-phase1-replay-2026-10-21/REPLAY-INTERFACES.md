# NHL V3 Phase 1 replay interfaces

The implementation follows the approved [event schema v1](../fullframe-event-audit-2026-10-21/PROPOSED-SCHEMA.md)
and its [component disposition rules](../fullframe-event-audit-2026-10-21/DISPOSITION-RULES.md).
`replay_data.py` reads the pinned normalized ledgers and official sources;
`replay_model.py` is pure deterministic transition logic; `prospective.py`
exposes a pregame-only input boundary for a later simulator.

## Provenance and time

`NormalizedEvent` retains `game_id`, source event ID, zero-based source array
index, publisher sort order, period number/type, period-local clock, event owner,
source retrieval timestamp, both raw and compressed PBP/shift hashes, source
URLs, source verification state, frame hash, audit version, and every available
component disposition/reason code. The feeds do not provide an absolute event
timestamp; the clock remains period-local and retrieval time remains provenance.

## Event fields

| Interface field | Status | Use |
|---|---|---|
| source event ID, event type, sort order, period, period clock | Direct | Replay chronology in publisher order. |
| owner team ID, shooter ID, goalie-in-net ID | Direct, separately gated | Stable identity joins only when the matching disposition is `ACCEPT`. |
| situation code | Direct | Parse recorded skater counts and goalie-present bits; retain the raw code. |
| strength class | Derived in the pinned audit | The replay retains the source classification and independently parses the raw manpower digits. |
| score, team attempts, SOG | Derived from accepted ordinary PBP events | Shootout events stay in separate counters. |
| shooter SOG, goalie saves/SA/GA | Derived from direct event IDs and component-eligible events | Exported as targets only when the approved label reader and replay counts both pass. |
| coordinates, shot type, miss reason | Direct and independently disposed | Nulls stay null; no value is inferred. |
| penalty fields and duration minutes | Direct, field-level dispositions | No penalty timer or service interval is invented. |
| penalty service / delayed state | Unavailable as a complete state | Record calls and contemporaneous manpower; only explicit delayed-penalty event types are labeled direct. |
| player-on-ice intervals | Direct shift-chart rows with deployment dispositions | Accepted intervals support an observed deployment join only; never tracking or possession. |
| continuous puck location, player movement, possession, stoppage duration | Unavailable | Must be latent state in a future simulator. |

## State outputs

Each `GameReplay` carries regulation and overtime score separately, regular shot
attempts and SOG by side, separate shootout attempts/goals, situation-code
manpower observations/transitions, penalty calls, directly verified goalie
observations and observed goalie-ID changes, and component quality counts.
`GameReplay` does not accept shift data as an input to scoring. A bad shift chart
therefore cannot change a team score or SOG count.

The shootout winner's one-goal adjustment is applied only when constructing the
historical final-score representation from the official final score. Shootout
attempts never enter ordinary team/player SOG or goals. In prospective use the
winner must come from generated shootout events; there is no official-result
argument in the simulation interface.

## Prospective boundary

`SimulationRequest` accepts only a `PregameSnapshot` and a random seed. Each
feature must have an accepted disposition and an `available_at_utc` no later
than scheduled start. The request has no observed event stream, final score,
postgame player target, replay result, or shift chart. Historical replay is an
audit input only; future events must be newly sampled.
