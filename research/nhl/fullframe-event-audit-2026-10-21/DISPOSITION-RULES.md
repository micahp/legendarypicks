# Component-level accept, reject, and quarantine rules

These rules prevent a game-level label from hiding a bad event or deployment
record. A source body can be accepted while one of its feature components is
quarantined.

## Source body

- **Accept for audit** only if the source list contains the pinned game ID; the
  manifest and sidecar identify the expected NHL endpoint and game; HTTP status
  is 200; compressed and decompressed lengths and SHA-256 values match; JSON
  shape and source game IDs validate; and payload row counts agree.
- **Reject** a body from analysis on any missing/duplicate manifest row, source
  URL or game identity mismatch, failed request, hash mismatch, malformed JSON,
  bad source payload shape, wrong game type, or mismatched row count.
- Preserve rejected evidence and its reason. Never overwrite the response or
  infer a substitute from official totals.

## PBP event

- `event_disposition=ACCEPT` when event type, source event ID, period type and
  event clock are present and valid. `QUARANTINE` missing type/ID/timeline;
  `REJECT` duplicate source event IDs.
- Event owner, shooter, goalie, coordinates, shot type, and penalty fields each
  have their own disposition. A valid event row can remain accepted for one
  purpose while another field is quarantined.
- Ordinary team shot counts exclude every shootout event. Team goal comparison
  excludes shootout goal events, then adds one goal to the official shootout
  winner. A tied official final score with a shootout is quarantined.
- Team goals are eligible only when PBP home/away IDs and abbreviations match
  the canonical frame and official game sides, PBP event counts reconcile to
  the official final scores, PBP embedded scores do not conflict when present,
  and every counted goal has valid unique event identity, time, and owner.
- Team SOG is eligible under the same identity and event integrity checks when
  ordinary PBP SOG counts reconcile to official team SOG.
- Shooter attribution accepts direct `shootingPlayerId`, or `scoringPlayerId`
  for a goal whose direct shooting ID is absent, only when the ID appears in the
  PBP roster and as an official, identity-resolved skater for the event owner’s
  team. Otherwise quarantine that player feature.
- Goalie identity accepts direct `goalieInNetId` only when it resolves to an
  official appearing goalie on the defending team. A missing ID is recorded as
  expected empty net only when the PBP situation code says no goalie is present;
  otherwise quarantine goalie attribution.
- Goalie saves, shots against, and goals against use these direct event IDs and
  only the approved label reader’s eligible, non-quarantined targets. Goalie
  shifts are never used to assign goalie stats.
- Coordinates are accepted for spatial features only when both are finite and
  within the audited rink bounds. Missing or out-of-bounds values are retained
  and spatially quarantined, while the event may still support a valid team
  count or player identity.
- Unblocked `shotType` is accepted only when present. Blocked shot type is
  `NOT_APPLICABLE` when absent; a published blocked-shot type is preserved.
- Penalty timing, duration, and player identity are separate components.
  Duration remains in publisher minutes. Bench penalties without a committed
  player are `NOT_APPLICABLE` for individual attribution. A player ID that is
  missing, unresolved, or on the wrong team is quarantined with its reason.

## Approved player targets

- Preserve every row’s approved `quality_status`, reason code, accepted value,
  and eligibility flags from the pinned NHL research-label reader.
- A `QUARANTINED` or `NOT_APPLICABLE` label is never a training, evaluation, or
  grading target. Do not replace its accepted value with an official raw value.
- For an eligible `SOG`, goalie `SAVES`, `SHOTS_AGAINST`, or `GOALS_AGAINST`
  row, event-derived use additionally requires direct event identity and exact
  count reconciliation to the accepted label. A mismatch quarantines that
  player-stat target while leaving unrelated team outcomes independent.
- Official boxscore goalie TOI remains the duration field. Shift TOI is only a
  deployment quality comparison.

## Player shift interval and deployment

- Reject malformed intervals, exact duplicate intervals, overlapping intervals
  for the same player and period, and intervals with player/team identity
  conflicts.
- Quarantine a player-game deployment when either the shift team abbreviation
  or team ID is missing; reject intervals when the published team identifiers
  conflict with each other or the official game appearance.
- Quarantine a player deployment when any published shift duration disagrees
  with its period-local start/end interval; the mismatch is retained as
  `SHIFT_DURATION_DISAGREES_WITH_INTERVAL`.
- Reject the entire shift chart when the median shift-to-official-TOI ratio is
  within 0.15 of 2.0 across players with more than 300 seconds of official TOI;
  this reproduces the pinned sample's duplicate-chart check. Record
  `DUPLICATE_SHIFT_CHART` with the game ID and observed median ratio.
- A player-game deployment is accepted only when the player is an official
  appearing player with resolved identity, is present in the PBP roster, has
  valid non-overlapping intervals, belongs to the source team, and summed shift
  duration is within 30 seconds of official boxscore TOI.
- Quarantine a player-game deployment with missing intervals, unavailable
  official TOI, or a TOI difference greater than 30 seconds. If a chart contains
  exact duplicate intervals, reject all its intervals. If only one player
  overlaps, reject the overlapping intervals and quarantine that player’s
  remaining intervals.
- Event-level player-on-ice attribution may use only accepted intervals. A
  rejected or quarantined deployment does not invalidate a separately
  reconciled team score or team SOG outcome.
- Retain direct event goalie IDs independently. Report whether they agree with
  an accepted goalie interval, but never derive goalie saves, shots faced, or
  goals against from shifts.
- Never interpret shift intervals as actual player movement, puck possession,
  or continuous on-ice tracking.
