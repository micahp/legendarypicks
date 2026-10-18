# Discrete-prop evaluation artifact contract

Every discrete-outcome prediction experiment in Legendary Picks must preserve enough information to
recompute each forecast and every evaluation result. This applies across leagues and markets, including
NFL carries, receptions, touchdowns, sacks and interceptions; NBA, MLB and NHL player props; and other
integer-valued outcomes.

## Required observation record

Store one immutable row for every forecasted observation, including:

- Canonical league, competition/season, event ID, scheduled start and actual event date.
- Canonical player ID, team ID, opponent where relevant, and source identifiers used to resolve them.
- Market/statistic name, units, integer support, line/threshold and side when the forecast is line-based.
- Forecast creation time, information cutoff, lock time, and whether the forecast was available before
  that cutoff.
- The realized outcome and settlement state. A true zero, missing result, void, push, DNP, and unresolved
  identity must remain distinct states.
- Any population strata used by the experiment, including the exact feature value and the rule that maps
  it to a tier.

## Required predictive distribution

Preserve the complete predictive PMF over its declared support for each observation. An equivalent CDF
is acceptable only if it recovers every PMF atom exactly, including endpoint and tail mass. Record the
support bounds, any tail bucket, and any truncation or renormalization. Probabilities must be finite,
nonnegative, and sum to one within a stated numerical tolerance.

Means, quantiles, intervals, event probabilities, or a parametric family name alone are not substitutes
for the observation-level PMF/CDF. If a tail is represented by a bucket, preserve the bucket definition
and enough information to score all possible outcomes consistently.

## Required frozen provenance

Keep these artifacts with each experiment:

- Model name/version, source commit, and any uncommitted source patch checksum.
- The exact frozen parameter file used to generate the forecast, stored byte-for-byte, with SHA-256.
- Input snapshot or immutable extract identifier and SHA-256; include source tables/partitions and their
  extraction query or version when the input is an extract.
- Population definition, evaluation window, inclusion/exclusion rules, and realized row/game counts by
  season and every reported stratum.
- Exact reproduction command, runtime/library versions, seeds, and all deterministic/stochastic settings.
- Forecast artifact format, schema version, path, creation time, row count, and checksum.
- Outcome/settlement source and version, plus any normalization or identity crosswalk versions.

Never replace a frozen parameter file, input fingerprint, or forecast artifact in place. New runs receive
new versioned artifacts. Large data files may live in research storage outside Git; commit their manifest,
checksums, schema, and stable storage location.

## Recomputable evaluation outputs

The observation records must support independent recomputation of proper distribution scores, point
error summaries, event probabilities and reliability, randomized PIT, prediction sets/intervals, and
paired comparisons grouped at the game/event level. Preserve row-level score inputs or the full PMF and
outcome so aggregates are never the only surviving result.

## Universal and market-specific fields

The provenance, forecast cutoff, canonical event/player identity, realized outcome state, full PMF/CDF,
frozen parameters, input fingerprint, evaluation population, reproduction command, and checksums are
universal requirements.

The statistic definition, legal support, units, settlement/void rules, line and side semantics, provider
market identifiers, position/role groupings, and useful strata are market-specific. Each experiment must
define these explicitly without changing the universal artifact requirements.
