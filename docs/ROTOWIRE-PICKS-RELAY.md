# RotoWire Picks relay — source reference

## Purpose and status

This document describes the public RotoWire Picks relay used by the candidate
MLS PrizePicks-threshold publisher.  It is a **discovery and pre-match offer
surface**, not an official MLS data authority, a historical archive, or a
license to imply sportsbook prices.

Endpoint observed without credentials:

```text
https://www.rotowire.com/picks/api/lines.php
```

The current candidate implementation is [ingest_rotowire_mls_props.py](../backend/ingest_rotowire_mls_props.py).
It has not been scheduled, run against a worktree database, promoted to managed
DEV, or enabled in production.

## What one live board contained

The board was measured on 2026-08-16.  It contained 91 markets, 1,056
entities, 54 events, and 2,216 top-level prop records (about 1.94 MB).  These
are snapshot counts, not a coverage guarantee; the book changes as events
approach lock.

### Current-day, pre-lock behavior

Treat this endpoint as a **current local-day board**, not as a schedule or
historical-lines API.  In the 2026-08-17 Central-time read, every soccer
fixture was later that same Chicago calendar day (2:00 PM, 8:00 PM, and 10:00
PM CDT); no prior-day, completed, or future-day soccer fixture was present.
Earlier research also found lines disappear around match lock and found no
public historical PrizePicks endpoint.

This is observed behavior, not a permanent provider guarantee.  Every capture
must derive the event date from `eventTime`, record its own timestamp, and
remain a no-op when the wanted league is absent.  Never fill a later slate from
an old capture or infer a full schedule from this board.

PrizePicks offers in that read:

| Sport | Offers | Events | Examples of observed markets |
| --- | ---: | ---: | --- |
| NFL | 942 | 17 | passing/rushing/receiving yards, receptions, TDs, sacks, tackles, kicking, interceptions |
| MLB | 210 | 10 | total bases, hits, runs, RBI, singles, pitcher strikeouts, earned runs |
| WNBA | 168 | 5 | points, rebounds, assists, combos, fantasy score, turnovers |
| CFB | 106 | 7 | passing/rushing/receiving yards, passing TDs, kicking points, interceptions |
| NHL | 59 | 1 | goals, hat tricks |
| CS2 | 42 | 4 | maps 1+2 kills and headshots |
| Soccer | 35 | 3 | passes attempted, saves, shots, shots on target, tackles, clearances, crosses |
| NBA | 18 | 1 | points/rebounds/assists averages, triple-doubles |
| Valorant | 4 | 1 | maps 1+2 kills |

The same relay also carried offers labelled `draftkings-sb`, `fanduel-sb`,
`caesars-sb`, `betmgm-sb`, `hardrock-sb`, `underdog`, `sleeper`, `pick6`, and
`rtsports`.  Their live coverage was concentrated in MLB, NFL, and WNBA, with
CS2 also present for Underdog and Sleeper.  They are separate observations,
not interchangeable writers for the same board.

## Actual payload contract

The relay is normalized in four top-level arrays:

```text
props[].marketID    -> markets[].marketID
props[].entities[]  -> entities[].entityID
entities[].eventID  -> events[].eventID
```

Important field names from the observed payload:

| Record | Stable/useful fields | Notes |
| --- | --- | --- |
| `markets[]` | `marketID`, `sport`, `category`, `marketName` | The display label is **`marketName`**, not `name`. |
| `entities[]` | `entityID`, `eventID`, `sport`, `name`, `team`, `pos`, `link` | `entityID` is board-local. The numeric suffix of the profile `link` is the candidate player source key, subject to cross-capture validation. |
| `events[]` | `eventID`, `homeTeam`, `awayTeam`, `eventTime` | Some events also expose weather, moneyline, or an odds source. |
| `props[]` | `propID`, `marketID`, `entities`, `projection`, `hitRates`, `lines[]` | The parent record is a proposition; the provider-specific offers live in `lines[]`. |
| `props[].lines[]` | `book`, `lineID`, `line`, `over`, `under`, `lineTime`, `score`, `factors` | Filter `book == "prizepicks"` for the MLS candidate route. |

The nested `lines[]` shape is material.  A flat `props[].book` parser silently
misses active offers.  The candidate parser supports the observed nested shape
and an older flat fallback, but the nested form is the currently measured
contract.

## Offer semantics

For the PrizePicks rows, `line` is a **More/Less threshold**.  The observed
numeric `over` and `under` values (for example, `-137`) are not sportsbook
American odds for our product.  Therefore:

- Persist the compatible `over` and `under` sides only as selections.
- Store no `props.odds` or odds snapshots for this source.
- Render **More** / **Less**, not `O -137` / `U -137`.
- Attribute the offer as **“PrizePicks threshold via RotoWire.”**

`projection`, `hitRates`, `score`, and `factors` are useful source-side
research metadata.  They are not independently published canonical game stats,
and must not become LP projections, settlement inputs, or backfilled history
without a separate source contract.

## MLS use: strict eligibility boundary

Soccer is not MLS-specific.  The measured soccer board had three non-MLS
fixtures:

| Fixture | PrizePicks threshold offers |
| --- | ---: |
| Club Necaxa vs Leon | 17 |
| Deportivo vs Elche | 16 |
| Pachuca vs Puebla | 2 |

Consequently, `sport == "Soccer"` is never a valid MLS filter.  A candidate
MLS event must pass every gate below before any row can be published:

1. Map `marketID` through `markets[].marketName` using an explicit allow-list.
2. Resolve its one entity to an event, player profile key, team, and position.
3. Normalize both source clubs through the exhaustive MLS vocabulary.
4. Match one independently published ESPN MLS fixture with the same home/away
   clubs and exact kickoff instant.
5. Resolve every source player through `player_source_ids`, or one exact
   canonical MLS name/team/position or reviewed alias.
6. Reject the entire fixture if any supported participant is malformed,
   unresolved, ambiguous, or attempts to repoint a stored source key.

No canonical player may be created from a RotoWire display name.  `eventID`,
the RotoWire profile key, and the ESPN event ID are preserved separately; they
must not be joined by human-readable names.

### Current MLS market map

| RotoWire `marketName` | Canonical key | Existing MLS evidence state |
| --- | --- | --- |
| Shots | `shots` | chartable from stored logs |
| Shots on Target | `shots_on_target` | chartable from stored logs |
| Passes Attempted | `passes_attempted` | published threshold only |
| Saves | `saves` | published threshold only |
| Clearances | `clearances` | published threshold only |
| Tackles | `tackles` | published threshold only |
| Crosses | `crosses` | published threshold only |

`Chances Created` and `Goals Allowed` are counted but intentionally skipped.
Goals and assists remain outside this relay implementation.  No dribbles or
fouls route has been verified for this candidate.

## Capture, failure, and reader contract

Each eventual run fetches the endpoint once, saves the exact bytes before
parsing, fingerprints them with SHA-256, and records source URL, parser
version, source market counts, event counts, status, and rejection reasons in
`prop_source_captures`.

| Condition | Status | Write behavior |
| --- | --- | --- |
| Relay successfully responds but has no exact MLS fixture | `NO_MLS_BOARD` | No MLS prop write |
| MLS fixture exists but fails fixture/player/market gates | `REJECTED` | No partial fixture write |
| Exact fixture and all identities resolve | `PUBLISHED` | Upsert this source's threshold rows only |

The MLS reader selects only `rotowire_prizepicks_relay`; it does not fall back
to stale Bovada MLS rows.  Until a successful MLS capture exists, the board
shows an explicit source-unavailable state.

## Operational limits and promotion gates

- This endpoint is public as observed, but it is not a documented LP data API.
  Terms/compliance approval is required before unattended collection.
- Do not bypass controls on PrizePicks' direct API.  Use only the independently
  reachable relay if its use is approved.
- Do not call this source from request handlers.  A collector writes a capture;
  API/UI routes read the database only.
- It is a same-day/pre-lock discovery surface: fetch a fresh board for each
  local day and do not expect it to retain completed or historical offers.
- Do not schedule it until a real pre-lock MLS capture demonstrates fixture
  linkage, player resolution, actual MLS market coverage, and last-good/failure
  behavior on a disposable database clone.
- Managed DEV, its public tunnel, production, merges, and timers are separate
  authorization boundaries.

## Related artifacts

- [Replacement design and promotion gates](PLAN-rotowire-mls-props-replacement-2026-08-16.md)
- [Original MLS source research](RESEARCH-MLS-PLAYER-PROP-LINES-2026-08-16.md)
- [Candidate publisher](../backend/ingest_rotowire_mls_props.py)
- [Source identity primitives](../backend/prop_source_identity.py)
