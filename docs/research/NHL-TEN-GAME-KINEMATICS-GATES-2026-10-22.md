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
| Temporal order and clock coverage | In every analyzed period file, numeric Image Id suffixes are unique and strictly increasing in file order; game clock never increases within a period. At least 99% of tracking rows and Image Id groups must have a parseable game clock. The initial 25–32 increments-per-game-clock-second check is only a provisional rate proxy; the release does not document a capture rate. Blank-clock rows/groups are counted and excluded from event alignment, while consecutive Image Id increments remain eligible for fixed-index tracking windows. | Image Id order permits a sequence forecast, but whole-second game clocks do not establish subsecond elapsed time. Clock reversals or missing groups are counted; no physical duration is inferred from these fields. |
| Player identity coverage | At least 90% of player rows have both a track ID and jersey number; at least 90% of labeled jersey rows join the same game/team shift roster; fewer than 0.1% of repeated `(period, team, track ID)` observations conflict on jersey/team. IDs remain game-scoped unless cross-game identity is independently verified. | The roster join checks identity semantics against a second release table and prevents a track ID or jersey from becoming a verified athlete identity without evidence. |
| Puck frame/coordinate coverage | At least 99% of Image Id groups contain exactly one puck row; at least 95% of puck rows have finite coordinates; and at least 10,000 uninterrupted 21-Image-Id puck windows occur across 8 games, with at least 1,000 per game. A separate 100ms continuity condition is assessable only if subsecond cadence is documented. | A puck row with blank coordinates is not a location. The pilot had 95.25% coordinate coverage; the window rule verifies that usable short paths remain after dropouts are excluded. Without a timebase, this gate establishes sequence continuity only, not puck speed or elapsed time. |
| Forecast-window coverage | At least 10,000 valid player windows overall and at least 1,000 in each of 8 games. A window must contain six consecutive input Image Id groups through cutoff `t` and the same player track at numeric suffix `t+15`; no window may bridge a missing suffix, coordinate, or period. | This supplies a usable sample for game-grouped development comparisons at a fixed observation-index horizon. It does not assert a duration in seconds. |

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

The first real period file was used as the required smallest-unit pilot. It had 34,413 Image Id
groups, one puck row in each group, and 0.59% rows with a blank X or Y. Before scanning the full release
or fitting any model, the coordinate completeness cutoff was changed from the draft 99.9% to 99.0%.
The reason is operational: sparse missing rows can be quarantined without contaminating any
forecast, because windows crossing a missing coordinate are reset. A 99.9% gate would reject this
otherwise highly observed source for a dropout rate the analysis explicitly handles. The revised
99.0% threshold is frozen for the full-population scan and all subsequent comparisons.

The pilot also had 95.25% finite puck coordinates. The puck-coordinate floor is therefore frozen
at 95.0%, paired with an uninterrupted-window count. If that count fails, mechanism selection is
limited to skater movement and cannot claim puck response or puck-flight validation.

The first full-scan attempt encountered 27 whole Image Id groups (270 tracking rows) with blank game clocks
in the third tracking-period file. The audit now counts blank clocks explicitly and continues using
Image Id order for movement windows. Before resuming the full scan, the temporal gate was extended
to require at least 99% game-clock coverage at both row and Image Id group level. Those 27 groups are
approximately 0.076% of that period's 35,392 groups, so the missing segment is measurable and
below the frozen floor if no other material gaps appear. This change was made before fitting any
candidate; blank clocks are not imputed.

## Full-audit disposition and timebase correction

The complete audit covered 959,754 unique Image Id groups and 8,401,602 tracking rows. It found
99.45% finite in-rink X/Y, 462,680 skater windows, 60,368 puck windows, and 95.74% finite puck XY.
Image Id suffix order was strictly increasing in all files; there were 793 suffix gaps, which reset
the affected windows. Game-clock coverage was 99.89% of rows and 99.89% of groups, but 27 clock
reversals occurred.

The release's official [data dictionary](https://github.com/bigdatacup/Big-Data-Cup-2026) defines
Image Id as an identifier and documents whole-second Game Clock values; it does not specify video
capture cadence or subsecond timestamps. The observed numeric-suffix/game-clock ratios ranged from
44.79 to 76.33 increments per clock second. They are not interpreted as camera frame rates because
the clock is coarse and does not provide elapsed wall time. Thus the initial 25–32 rate-proxy check
fails, and no physical frames-per-second claim is supported.

The frame/coordinate portion of puck coverage passes. The frozen ≤0.10-second puck-gap check is
unassessable and is not reported as a pass: no independent subsecond timebase exists. Similarly,
the 15-step movement experiment uses numeric Image Id increments only and reports no seconds-based
forecast horizon.
