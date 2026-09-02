# RotoWire relay MLS prop replacement — plan

## Decision

Do not point the existing Bovada parser at a different URL or treat every
`sport: Soccer` row as MLS.  Add a dedicated, candidate-only
`ingest_rotowire_mls_props.py` publisher based on the proven
`ingest_underdog_props.py` source-ID pattern.  It will read RotoWire's public
PrizePicks relay once per run, retain the complete raw capture, and write only
rows that match one published MLS fixture and resolve every source player to
one canonical player.

This is a replacement of the **MLS reader's current-source policy**, not a
rewrite or deletion of historical Bovada rows.  Bovada remains attributable
history; it must not be silently mixed into a new PrizePicks threshold board.

## What was measured on 2026-08-16

The relay endpoint was read once at:

```text
https://www.rotowire.com/picks/api/lines.php
```

Its current response contained array-valued `markets`, `entities`, `events`,
and `props` collections.  The source relationship is:

```text
props.marketID -> markets.marketID
props.entities[] -> entities.entityID -> entities.eventID -> events.eventID
```

An entity also carries `name`, `team`, `pos`, and a RotoWire player profile
URL such as `https://www.rotowire.com/soccer/player/oscar-garcia-36464`.  The
numeric profile suffix is the candidate source-player key; its persistence
across captures must be tested before activation.  `entityID` remains in the
raw capture as a board-local record identifier.

The current read exposed 35 PrizePicks soccer threshold rows across three
non-MLS fixtures:

| Fixture | Threshold rows | Market families |
| --- | ---: | --- |
| Club Necaxa vs Leon | 17 | Saves, Crosses, Passes Attempted, Shots, Shots on Target, Tackles |
| Deportivo vs Elche | 16 | Saves, Clearances, Crosses, Passes Attempted, Shots, Shots on Target, Tackles |
| Pachuca vs Puebla | 2 | Chances Created, Goals Allowed |

There were **zero MLS fixtures in that capture**.  It proves the JSON contract,
but it is not evidence of MLS coverage and must produce `NO_MLS_BOARD`, not an
empty or cross-league MLS write.

The candidate database currently holds 714 MLS props from Bovada across 15
games and two markets (`goals`, `assists`).  Only 154 of those rows belong to
games already linked to an ESPN event; 12 of the 14 recent MLS `prop_games`
are unlinked.  The replacement must bind RotoWire's event ID to the published
MLS fixture before any prop write, rather than repeating that reachability gap.

## Product and data contract

### Source and offer semantics

- Source label: `rotowire_prizepicks_relay`.
- It is a **More/Less threshold**, not a sportsbook price.  The relay's
  numeric `over`/`under` fields must not populate `props.odds` or
  `prop_odds_snapshots`, and the UI must not render them as `O -137` / `U -137`.
- Persist canonical `over` and `under` sides for compatible existing history
  and settlement APIs, but render them as **More** and **Less** when this
  source is selected.  Source attribution must read “PrizePicks threshold via
  RotoWire”, not the internal source key.
- Phase 1 market map is direct and narrow: `Shots -> shots`, `Shots on Target
  -> shots_on_target`, `Passes Attempted -> passes_attempted`, `Saves -> saves`,
  `Clearances -> clearances`, `Tackles -> tackles`, and `Crosses -> crosses`.
  `Chances Created` and `Goals Allowed` stay unimplemented until an explicit
  product/settlement decision; unknown market labels are counted and skipped.
- Kambi goals and assists remain a separate possible source.  They are not
  part of this replacement implementation and must never be overwritten by a
  RotoWire threshold.

### Canonical fixture identity

1. Group the relay's soccer props by native `eventID` and retain source
   `homeTeam`, `awayTeam`, and `eventTime`.
2. Load the independently published ESPN MLS fixtures for the UTC date plus
   adjacent local date when necessary.
3. Normalize both teams through the existing exhaustive MLS vocabulary in
   `link_prop_games.py`.  A missing or colliding club vocabulary is a rejected
   event, never a fuzzy match.
4. Require exactly one published MLS fixture with the same two normalized
   teams and compatible kickoff.  Create/find the canonical `prop_games` row
   using its ESPN event ID and bind native `eventID` in
   `prop_game_source_ids`.
5. One source event ID mapping that later identifies a different canonical
   game is a hard `SourceIdentityConflict`.

### Canonical player identity

1. Reuse `player_source_ids(source, league, source_player_key, player_id, ...)`
   from the Underdog publisher.  After the persistence check, source player key
   will be the numeric RotoWire soccer profile ID; keep the full profile URL and
   board `entityID` in the capture artifact for audit.
2. A preexisting source-key mapping wins.  A new mapping requires one exact
   canonical MLS name plus the published team on the matched fixture; position
   must also agree when both source and canonical positions are present.
3. A reviewed `name_alias` may resolve a new source key only if it points to
   exactly one MLS player on that fixture.  Never fuzzy-match, never create a
   `players` row, and never resolve a same-name player without the fixture
   team.
4. Queue unresolved or ambiguous IDs in `unresolved_players` keyed by source
   player key with a precise reason.  Reject the whole event if any participant
   is unresolved, so an apparently complete MLS fixture cannot be partial.

### Capture and reader state

- Save the exact raw response under the bind-mounted data directory before
  parsing, with capture time, SHA-256, source URL, parser version, source row
  count, MLS-candidate count, eligible event count, rejected-event reasons,
  and market-family counts in a `prop_source_captures` record.
- Treat the relay as a current local-day, pre-lock board rather than a
  schedule/history API.  Derive each fixture's calendar date from `eventTime`,
  retain the capture timestamp, and never fill a new slate from a prior day's
  rows.  The observed 2026-08-17 soccer board contained only that day's
  Chicago-time fixtures; this remains an observed behavior, not a permanent
  provider guarantee.
- A complete board with no matching MLS fixture records `NO_MLS_BOARD` and
  writes no MLS props.  A matching fixture with incomplete identity or market
  data records `REJECTED`; it does not replace the last-good source state.
- A successful current capture updates only this source's canonical MLS rows.
  It does not delete historical Bovada rows, invent zeroes, carry an old line
  to a different fixture, or modify Kambi rows.
- The MLS board API selects the configured current source.  Until a successful
  RotoWire MLS capture exists, it must render an explicit unavailable/stale
  state rather than presenting Bovada as if it were the new source.

## Why a source-kind UI change is required

`MarketSlateBoard.tsx` currently renders every row as two sportsbook odds
chips (`O` and `U`) and prints the raw `source` value.  Passing the relay's
`-137` placeholders through would falsely claim sportsbook juice.  The board
needs a source-contract lookup that:

| Source contract | Side labels | Price display | Attribution |
| --- | --- | --- | --- |
| sportsbook odds | Over / Under | current odds | existing source label |
| `rotowire_prizepicks_relay` | More / Less | `Threshold only` | PrizePicks threshold via RotoWire |

The API continues to return `source`; it can expose a derived `offer_kind` and
display label so the frontend does not reimplement the policy.  The existing
“Model evidence unavailable” state is retained for source markets our stored
MLS logs cannot support.

Current MLS logs contain only `goals`, `assists`, `shots`, and `sot`.  Therefore
only `shots` and `shots_on_target` are initially chartable from the relay.
Passes, saves, clearances, tackles, and crosses may be shown as published
thresholds, but must report model/settlement evidence unavailable until an
independent published MLS per-game stat source is added.  They must not be
estimated from a different statistic.

## Implementation sequence

1. Add tests and a fixture representing one MLS fixture plus a non-MLS soccer
   fixture, source-player links, one unresolved player, a changed source-key
   conflict, unsupported market labels, and a locked/empty MLS board.
2. Extract the additive source-key table helpers from
   `ingest_underdog_props.py` or reuse them without duplicating identity rules.
   Add `prop_source_captures` only; no destructive migration and no existing
   prop deletion.
3. Implement `ingest_rotowire_mls_props.py` with a single fetch, raw capture,
   exact event/player gates, compact source-count summary, `--dry-run`, and
   non-zero exit for a nonempty MLS candidate board that produces zero eligible
   events.  An ordinary no-MLS board is a distinct, successful no-op state.
4. Update `/api/props`, `/api/props/slate`, and `MarketSlateBoard` to surface
   the source contract and distinguish More/Less threshold rows from sportsbook
   lines.  Do not change the request path to call RotoWire.
5. Capture the next MLS pre-lock board manually, run the publisher against a
   disposable SQLite clone, and verify: capture SHA, source/MLS event counts,
   fixture-link coverage, player-ID coverage, no player creation, current-board
   API rows, and the exact rendered More/Less interaction.
6. Only after that evidence and a separate terms/compliance decision, decide
   whether to install a bounded, `flock`-protected candidate timer.  Managed
   DEV, its service, its tunnel, production, merge, and scheduling are out of
   scope for this plan.

## Promotion gates

- At least one captured pre-lock MLS fixture, with real RotoWire-to-ESPN
  fixture linkage and all source participants either resolved or the event
  rejected.
- Measured MLS market-family count from that capture.  The research-only 9/11
  hypothesis is not a gate pass.
- No new canonical player rows; zero duplicate source-key mappings; zero
  unexplained unresolved IDs.
- Candidate clone `PRAGMA quick_check`, protected-table fingerprints before and
  after, API source semantics, and a rendered board check proving the UI says
  More/Less threshold rather than sportsbook odds.
- Separate authorization for any automated collection, managed-DEV migration,
  timer, merge, or production promotion.

## Current state

The candidate implementation is complete and is intentionally **unactivated**:
it has fixture tests for exact RotoWire-to-ESPN linkage, full-fixture rejection,
source-key conflicts, no-odds threshold persistence, stale-Bovada exclusion,
and rendered More/Less behavior.  It has not been run against the candidate
database because no current pre-lock MLS relay fixture has been captured.

No candidate database, service, timer, managed-DEV state, tunnel, merge, or
production state was changed while implementing it.  The pre-lock capture and
promotion gates above remain required before any activation decision.
