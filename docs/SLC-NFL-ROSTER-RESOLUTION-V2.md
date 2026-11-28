# Legendary Picks SLC: Deterministic Pregame Roster Rules

Specification: SLC-NFL-ROSTER-RESOLUTION-V2
Status: Proposed implementation contract
Scope: NFL full-game simulation, player participation, depth-chart roles, injuries, transactions, practice-squad elevations, and special teams.

## 1. Objective

Produce one reproducible, availability-aware roster for each team at a specific pregame cutoff.

The system must support simulations days before kickoff, not just after official inactives are released.

For every player, resolve five independent properties:

1. Identity: Which canonical NFL player is this?
2. Membership: Which team and roster category does the player belong to?
3. Eligibility: Is the player officially eligible to participate?
4. Projection: Is the player expected to participate in this particular game?
5. Role: What positions and responsibilities may the player fill?

Never treat a depth-chart listing as proof of membership, eligibility, or health.

## 2. Data Sources

Use the following sources in order of authority for their respective fields.

| Information | Primary source | Secondary source |
|---|---|---|
| Game schedule, opponent, kickoff | NFL schedule / Legendary Picks versioned schedule | nflverse schedules |
| Active roster, reserve lists, practice squad | Official NFL team roster and transaction notices | nflverse rosters |
| Signings, releases, promotions, elevations | Official team transaction announcements | NFL transactions |
| Position and depth-chart ranking | Official team depth chart | nflverse depth charts |
| Injury practice participation and game designation | NFL.com and official team injury reports | nflverse injuries |
| Game-day inactive players | Official NFL/team game-day inactive announcement | Verified NFL game reporting |
| Player identity | GSIS ID and existing LP player crosswalk | ESPN ID through validated crosswalk |
| Historical snaps and workloads | LP database, nflverse participation/snap data | Other timestamped historical feeds |
| Player performance | Existing LP statistics and SLC reference database | nflverse historical statistics |

### Primary URLs

* NFL schedule: https://www.nfl.com/schedules/
* NFL injuries: https://www.nfl.com/injuries/
* nflverse releases: https://github.com/nflverse/nflverse-data/releases
* nflverse update schedule: https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html
* Miami roster: https://www.miamidolphins.com/team/players-roster/
* Miami depth chart: https://www.miamidolphins.com/team/depth-chart
* Miami transactions: https://www.miamidolphins.com/team/transactions/
* Buffalo roster: https://www.buffalobills.com/team/players-roster/
* Buffalo depth chart: https://www.buffalobills.com/team/depth-chart

Official transactions supersede stale depth-chart and roster snapshots for membership. Official game-day inactives supersede earlier availability projections.

Use nflverse for structured bulk ingestion. Use official announcements to reconcile changes not yet reflected in nflverse.

Never substitute a source's download time for its actual publication time when evaluating historical data availability.

## 3. Immutable As-Of Rule

Every roster resolution has a UTC `as_of` timestamp.

An input may be used only if:

* Its source content was observed or captured by `as_of`.
* Its relevant effective date is not later than `as_of`.
* Its source version is preserved.
* It belongs to the correct game, season, and team.

An event discovered after the cutoff cannot be retroactively added to an earlier forecast.

Persist:

* `source_url`
* `published_at_utc`, when available
* `observed_at_utc`
* `effective_at_utc`, when known
* `source_sha256`
* `source_type`
* `source_version`

If publication time is unavailable, the first verified capture time becomes the earliest supported availability time.

Snapshots must be append-only. A Sunday roster update creates a new snapshot, not a modification of Tuesday's snapshot.

## 4. Membership Resolution

Begin with the latest timestamp-eligible team roster and apply all verified transactions in event order.

Each player receives exactly one current membership classification:

| Membership | Meaning |
|---|---|
| `ACTIVE_ROSTER` | Signed to the team's active/inactive roster |
| `PRACTICE_SQUAD` | Member of the practice squad |
| `ELEVATED` | Practice-squad player officially elevated for the target game |
| `RESERVE` | IR, reserve/PUP, reserve/NFI, or another ineligible reserve designation |
| `SUSPENDED` | Ineligible because of an applicable suspension |
| `DEPARTED` | Released, waived, traded away, or otherwise no longer a member |
| `UNKNOWN` | Insufficient or contradictory evidence |

Rules:

1. A signing to the active roster changes membership to `ACTIVE_ROSTER`.
2. A practice-squad signing changes membership to `PRACTICE_SQUAD`.
3. An official game-specific elevation creates `ELEVATED` eligibility for that game only.
4. An IR transaction changes membership to `RESERVE` immediately when effective.
5. A return-to-practice designation does not activate a player from a reserve list.
6. A confirmed activation from a reserve list restores active eligibility.
7. A release or trade away removes the player from that team's roster.
8. A player may not have active membership with both teams in the same matchup.
9. Missing recent transactions or contradictory official records produce `UNKNOWN`, not an invented membership state.

A newly signed player must be inserted into the candidate roster even if the depth chart has not been updated.

## 5. Game Availability Rules

Compute `official_eligible` separately from `projected_participant`.

| Condition | Official eligibility | Default projection |
|---|---|---|
| Active roster, no inactive designation | Eligible | Include |
| Officially elevated from practice squad | Eligible | Include unless inactive |
| Practice squad, not elevated | Not yet eligible | Exclude unless explicitly projected |
| IR / reserve-PUP / reserve-NFI | Ineligible | Exclude |
| Official injury status Out | Not expected to play | Exclude |
| Official game-day inactive | Ineligible | Exclude |
| Questionable | Pending | Include with uncertainty flag |
| Doubtful | Pending | Include in an explicitly labeled conditional baseline, with an exclusion scenario |
| Full/limited/no practice | Not decisive by itself | Do not automatically exclude |
| Missing injury report | Unknown reporting coverage | Never interpret as confirmed healthy |

Official game-day inactives take precedence over all projected availability decisions.

Practice reports and game-status reports are different observations. Do not convert a missed practice into a game-day inactive designation.

Never infer a player's injury status from an absence in one data feed.

## 6. Provisional vs. Final Rosters

Create three forecast classifications.

### A. PROVISIONAL

Used days before kickoff.

* Official transaction and reserve exclusions applied.
* Latest valid depth chart applied.
* Available injury information applied.
* Uncertain starters remain flagged.
* Explicit projected practice-squad elevations allowed.
* Official game-day participation is not claimed.

### B. UPDATED_PROVISIONAL

Used after final weekly injury designations and transaction updates, but before official inactives.

* Apply all newly available official reports.
* Recalculate starters and backups.
* Retain uncertainty where inactives or elevations are not confirmed.

### C. GAMEDAY_FINAL

Used after game-day eligibility announcements.

* Confirm game-specific elevations.
* Apply official inactive lists.
* Confirm critical position coverage.
* Remove every unconfirmed practice-squad projection.
* Block final classification if required official inputs remain unavailable.

A provisional roster can support a valid conditional simulation. It cannot be represented as an officially verified game-day roster.

## 7. Deterministic Starter Selection

For each required role:

1. Start with the most recent cutoff-valid depth-chart ordering.
2. Remove ineligible players.
3. Apply explicit official announcements identifying starters.
4. Otherwise select the highest-ranked remaining eligible player in that position and formation.
5. Preserve the player's original depth rank and record any promotion.
6. If the role has no valid candidate, report it as unresolved.

A player who signs after the depth chart was published enters the candidate pool with `depth_rank = null`.

Do not automatically place that player ahead of a ranked backup.

If only one eligible candidate exists for a required position, the resolver may select that candidate but must record that the assignment was inferred by the unique-candidate rule.

If multiple unranked candidates remain, require stronger role evidence or an explicit scenario assumption.

Never settle an unresolved starter by alphabetical name, jersey number, or player ID.

### Formation and role model

Continue to support the existing SLC baseline:

* 11 offensive starter roles
* 11 defensive starter roles
* 6 special-teams starter roles

These are 28 role assignments, not necessarily 28 distinct players.

Maintain separate player and role records so an athlete can occupy multiple legitimate roles without being duplicated as a person.

Offense should support QB, RB, WR, TE, FB, and offensive-line depth. Defense should preserve formation-specific positions. Special teams must distinguish kicker, punter, long snapper, holder, kick returner, and punt returner.

Do not force a player into an unrelated position merely to satisfy the 28-role count.

## 8. Practice-Squad and Emergency Replacement Rule

If a required position has no eligible active-roster candidate:

1. Search officially announced active-roster signings.
2. Search officially announced game-specific elevations.
3. Search practice-squad players at the same position.
4. If exactly one practice-squad candidate exists, permit a `PROJECTED_ELEVATION` role in provisional simulations.
5. If several candidates exist, require explicit evidence selecting one.
6. If no candidate can be resolved, block that position-dependent simulation scenario.

`PROJECTED_ELEVATION` is a modeling assumption, not an official transaction or membership state.

When an elevation or signing becomes official, replace the provisional assumption in a new snapshot.

### Special handling for kickers

The resolver must never silently use a departed kicker or a league-average placeholder as though that player were on the team.

A projected practice-squad kicker may be assigned the `PK` role in a provisional scenario if uniquely identified.

Record the projected kicker's player ID, membership, pending eligibility, selected role, and assumption source.

Field-goal and extra-point execution must use the selected kicker's supported performance inputs or a separately documented model fallback, not the departed kicker's statistics.

If the kicker changes, SLC must update both the roster assignment and any kicker-conditioned simulation parameters.

## 9. Injury and Workload Handling

Availability resolution determines participants. Workload modeling determines their involvement.

Do not conflate them.

After finalizing the participant pool:

1. Load historical snaps, starts, routes, carries, targets, and other supported participation features using records eligible at the cutoff.
2. Preserve original role assignments.
3. Remove excluded players from every workload allocation.
4. Recalculate role and usage shares over the remaining eligible players using the active workload model.
5. Reconcile all allocated shares to valid totals.
6. Record fallback behavior for missing history and newly promoted players.

A rookie or new signing without usable history must not automatically inherit the previous starter's efficiency.

The roster resolver must not introduce arbitrary offensive or defensive strength penalties. Player-specific adjustments belong to a separately versioned, empirically evaluated performance model.

## 10. Missing Data and Blocking Conditions

The resolver must distinguish these cases:

* `KNOWN_EXCLUDED`: reliable evidence confirms nonparticipation.
* `KNOWN_ELIGIBLE`: reliable evidence confirms current eligibility.
* `PROJECTED`: explicitly documented provisional participation.
* `UNKNOWN`: insufficient evidence.
* `CONFLICT`: incompatible evidence without a deterministic resolution.

Hard-block the affected simulation scenario for:

* Unresolved QB1.
* Unresolved required kicking role.
* Missing canonical identity for a required participant.
* A starter classified as officially ineligible.
* Duplicate, conflicting role assignments.
* Contradictory same-priority official transactions.
* Missing critical depth positions without a permitted fallback.
* Snapshot evidence that postdates the cutoff.
* An unavailable required source represented as verified.
* A request for `GAMEDAY_FINAL` when elevations or inactives remain unverified.

Noncritical uncertainty must be recorded rather than incorrectly causing zero valid games.

A roster-quality failure is separate from a football simulation failure. Report both categories independently.

## 11. Snapshot Data Contract

Version the roster contract as `lp-nfl-resolved-roster-2`.

Minimum example:

```json
{
  "schema": "lp-nfl-resolved-roster-2",
  "game_id": "2026_11_MIA_BUF",
  "as_of_utc": "2026-11-17T22:00:00Z",
  "forecast_class": "PROVISIONAL",
  "teams": {
    "MIA": {
      "players": [
        {
          "player_name": "Daniel Carlson",
          "gsis_id": "RESOLVE_FROM_LP",
          "membership": "PRACTICE_SQUAD",
          "official_eligible": false,
          "projected_participant": true,
          "projection_status": "PROJECTED_ELEVATION",
          "roles": ["PK"],
          "assumption": "sole_known_kicker_candidate",
          "source_urls": [
            "https://www.miamidolphins.com/team/transactions/"
          ]
        }
      ]
    }
  }
}
```

This is a partial illustrative payload, not a generated or validated snapshot.

The complete production payload additionally stores:

* All players and role assignments for both teams.
* Canonical LP player IDs and source crosswalks.
* Transaction and injury evidence.
* Source timestamps and hashes.
* Original and effective depth ranks.
* Excluded players and exclusion reasons.
* Unresolved roles and scenario assumptions.
* Source capture manifest.
* Resolver rules version.
* Model input fingerprints.
* Content hash.

The same input evidence, cutoff, assumptions, and resolver version must produce identical canonical output regardless of machine or ingestion order.

## 12. Slow-Host / Fast-Host Architecture

### Slow host: authoritative input construction

The slow host performs:

1. Source capture.
2. Team roster and transaction reconciliation.
3. Canonical player identity resolution.
4. Injury and eligibility resolution.
5. Starter and backup role resolution.
6. Workload-input preparation.
7. Snapshot validation and hashing.
8. Export of a self-contained simulation bundle.

The bundle must include a frozen reference-data extract if the fast host does not have the necessary historical database.

### Fast host: simulation execution

The fast host:

1. Verifies snapshot and reference-data hashes.
2. Loads the exact intended model commit.
3. Runs the same frozen roster across all compared SLC versions.
4. Uses common seeds and validated paired-random streams where applicable.
5. Saves individual seed outcomes, errors, box scores, and model provenance.
6. Returns results tied to the immutable roster snapshot.

The fast host must not independently refresh or reinterpret live rosters.

## 13. Existing Repository Integration

Reuse and extend:

* `scripts/nfl_sequence/pregame_snapshot.py`
* `scripts/nfl_sequence/pregame_capture.py` on the research branch
* `scripts/nfl_sequence/build_full_depth_roster_snapshot.py`
* `scripts/nfl_sequence/availability_adapter.py`
* `scripts/nfl_sequence/simulate_pregame_batch.py`
* `scripts/nfl_sequence/slc_family_runner.py`

Required implementation changes:

1. Generalize the existing KC–SEA-specific full-depth construction and provenance checks for arbitrary upcoming games.
2. Add a deterministic transaction-reconciliation stage before full-depth availability application.
3. Allow newly signed players and projected elevations to enter the role candidate pool even if absent from the last depth-chart artifact.
4. Separate official membership, availability, projection assumptions, and depth roles in the schema.
5. Replace the assumption that 28 starter roles require 28 unique players.
6. Extend `availability_adapter.py` to consume the resolved roster contract rather than only filter players already present.
7. Require existing SLC game execution to use the resolved participant and role assignments, including special teams.
8. Add immutable prospective snapshot capture and explicit provisional/final classifications.
9. Ensure both model families consume the identical frozen roster and historical reference inputs.

Do not silently loosen existing validation. Version the new contract and preserve compatibility with historical frozen test fixtures.

## 14. Miami–Buffalo Acceptance Test

Game: `2026_11_MIA_BUF`
Target: November 22, 2026
Initial scenario cutoff: November 17, 2026

Given official Miami transactions known at the cutoff:

| Player | Roster rule |
|---|---|
| Malik Willis | Exclude; injured reserve |
| Zach Sieler | Exclude; injured reserve |
| Zeek Biggers | Exclude; injured reserve |
| Jordan Phillips | Exclude; injured reserve |
| Zane Gonzalez | Exclude; waived |
| Brady Cook | Include in active-roster QB depth |
| Jordan Jefferson | Include in active-roster DL candidate pool |
| Eric Watts | Include in active-roster edge candidate pool |
| Daniel Carlson | Practice squad; projected PK only in provisional scenario |

The resolver must select a QB1 from the cutoff-valid roster and depth evidence, reconcile Miami's defensive replacements without using unavailable players, and preserve Carlson's pending elevation as an explicit assumption.

The same resolution procedure applies to Buffalo.

### Required automated tests

* IR player remains listed QB1/DT1 on an old depth chart: excluded.
* Active-roster signing missing from depth chart: added to candidate pool.
* Practice-squad player not elevated: excluded from official game-day pool.
* Sole practice-squad kicker: provisional projection allowed.
* Same kicker not officially elevated: final snapshot does not silently include him.
* Official inactive announced: removed regardless of depth rank.
* Questionable player: uncertainty preserved, not automatically excluded.
* Backup fills an excluded starter's valid role.
* Multiple unranked replacements: unresolved rather than arbitrary selection.
* A transaction published after the cutoff does not alter an earlier snapshot.
* Identical source bundle generates identical roster hash.
* No game with a resolvable provisional roster is incorrectly counted as having zero valid simulations merely because it lacks final game-day evidence.

## 15. Acceptance Criteria

The roster system is ready when:

1. Miami–Buffalo can produce a valid November 17 provisional snapshot.
2. Every selected participant has a resolved identity and documented membership.
3. All confirmed ineligible players are excluded.
4. Every projected player has an explicit assumption.
5. All required simulation roles are filled or produce a named blocking condition.
6. V1.7 and V2 can consume the same frozen roster.
7. All outputs preserve source, cutoff, and model provenance.
8. A later official roster update can be compared with the earlier forecast without rewriting history.

Final design principle: Never confuse an incomplete roster feed with an incomplete football team, and never confuse a projected participant with an officially confirmed active player.

### Implementation note: prior-game absence diagnostics

New Oracle reports explicitly mark obsolete OUT/INACTIVE designations with `previous_game_out_no_current_report`. The shared roster preflight carries this flag to the resolved GSIS record only for the same canonical team, when the original timestamp precedes that previous kickoff, that kickoff is no later than the snapshot cutoff, and there is no current designation. The resolver preserves it as diagnostic metadata, not a current Out status or eligibility decision. Current designations supersede it, and a future marked observation is refused. Unmarked historical reports retain their existing resolution behavior and hashes. The marker and original evidence are sealed with the snapshot; no frozen model source or package changes.
