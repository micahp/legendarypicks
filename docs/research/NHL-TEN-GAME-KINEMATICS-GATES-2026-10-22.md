# Ten-game tracking quality gates

**Study branch:** `research/nhl-ten-game-kinematics-2026-10-22`

**Base:** `25d1c746f714d89cbaf2561d4d25035c0fb4b33a`
**Purpose:** freeze data-quality thresholds before the full-population audit and before fitting any movement candidate.

## Data and use

The input is the locally held 2026 Big Data Cup release at
`/root/lp-research-data/stathletes-big-data-cup-2026`. The official release describes tracking
positions in rink feet, event coordinates in camera perspective, jersey numbers as potentially
blank, and game-clock values in whole seconds. Raw files remain outside the repository. The
analysis is limited to research use and will not redistribute the source data.

## Gates frozen before the full audit

| Gate | Acceptance threshold | Why this threshold is required |
|---|---|---|
| Release integrity | All 54 listed assets exist, have the manifest byte size, and match its SHA-256. | A partial or changed release invalidates population counts and reproducibility. |
| Tracking coordinate validity | At least 99.0% of player and puck rows have finite X/Y inside the documented 200-by-85-foot rink envelope (`X ∈ [-100,100]`, `Y ∈ [-42.5,42.5]`). | A one-period pilot found some blank coordinates. A 1% ceiling allows sparse video-tracking dropouts; every missing row is counted and any trajectory window crossing one is discarded. |
| Event-to-track alignment | For any event-linked analysis: at least 100 actor/event matches in at least 8 games; with the preregistered direct coordinate mapping, median nearest same-second actor distance ≤20 ft and 95th percentile ≤40 ft in at least 8 games. Candidate axis reflections are diagnostics only and cannot be selected on the full audit sample. Otherwise event coordinates are quarantined from modeling. | The first-period pilot showed close actor alignment without reflecting either axis. Event clocks are rounded to seconds, so the limits allow timing and tracking noise while rejecting a wrong identity join or coordinate frame. |
| Temporal order | In every analyzed period file, image-frame suffixes are unique and strictly increasing in file order; game clock never increases within a period. At least 8 games must have a median inferred rate of 25–32 frames/s. | The frame suffix is the only subsecond ordering signal in the release. Clock reversals or implausible rates prevent a defensible fixed-horizon forecast. |
| Player identity coverage | At least 90% of player rows have both a track ID and jersey number; at least 90% of labeled jersey rows join the same game/team shift roster; fewer than 0.1% of repeated `(period, team, track ID)` observations conflict on jersey/team. IDs remain game-scoped unless cross-game identity is independently verified. | The roster join checks identity semantics against a second release table and prevents a track ID or jersey from becoming a verified athlete identity without evidence. |
| Puck continuity | At least 99% of frames contain exactly one puck row; at least 95% of puck rows have finite coordinates; at least 95% of consecutive observed puck locations are no more than 0.10 seconds apart; and at least 10,000 uninterrupted 21-frame puck windows occur across 8 games, with at least 1,000 per game. | A puck row with blank coordinates is not a location. The pilot had 95.25% coordinate coverage; the window rule directly verifies that usable short paths remain after dropouts are excluded. A failure bars puck-conditioned modeling, but not tracking-only skater-path prediction. |
| Forecast-window coverage | At least 10,000 valid player windows overall and at least 1,000 in each of 8 games. A window must contain six consecutive input frames through cutoff `t` and the same player track at `t+15` frames; no window may bridge a missing frame or period. | This supplies a usable sample for game-grouped development comparisons and ensures the nominal half-second horizon is observed directly. |

The event-alignment gate is separate from the tracking-only movement gate: a failure bars event
coordinates and event-conditioned claims, but does not by itself invalidate trajectory prediction
from the tracking coordinate system. Any failed gate and its consequence will be reported rather
than softened after seeing the result.

## Boundaries

Passing these gates establishes only that the release is structurally usable for the stated
analysis. It does not validate optical-tracking error, identify real athletes across games, establish
causal reaction time, or prove that the 2D coordinates support collision, goalie, or puck-flight
physics. Those require separate labels and independent measurements.

## Threshold adjustment before the full audit

The first real period file was used as the required smallest-unit pilot. It had 34,413 frames,
one puck row in every frame, and 0.59% rows with a blank X or Y. Before scanning the full release
or fitting any model, the coordinate completeness cutoff was changed from the draft 99.9% to 99.0%.
The reason is operational: sparse missing rows can be quarantined without contaminating any
forecast, because windows crossing a missing coordinate are reset. A 99.9% gate would reject this
otherwise highly observed source for a dropout rate the analysis explicitly handles. The revised
99.0% threshold is frozen for the full-population scan and all subsequent comparisons.

The pilot also had 95.25% finite puck coordinates. The puck-coordinate floor is therefore frozen
at 95.0%, paired with an uninterrupted-window count. If that count fails, mechanism selection is
limited to skater movement and cannot claim puck response or puck-flight validation.
