# Research — free MLS player-prop lines (2026-08-16)

## Decision in one sentence

There is a plausible **no-paid, no-key 9-of-11** route for MLS player-prop
*thresholds*: use RotoWire's public PrizePicks relay for seven stat families
and Kambi for goals plus assists.  This is a research finding, not an approved
ingest or a claim of current MLS coverage: the MLS slate needed to prove it
locked shortly before this research completed.

## Requested market families

| Market family | Candidate source | Status | What the source supplies |
| --- | --- | --- | --- |
| Shots | RotoWire / PrizePicks relay | observed on live soccer rows | More/Less threshold |
| Shots on target | RotoWire / PrizePicks relay | observed on live soccer rows | More/Less threshold |
| Passes attempted | RotoWire / PrizePicks relay | observed on live soccer rows | More/Less threshold |
| Goals | Kambi | observed on MLS event | player scoring prices |
| Goalie saves | RotoWire / PrizePicks relay | observed as `Saves` | More/Less threshold |
| Clearances | RotoWire / PrizePicks relay | observed on live soccer rows | More/Less threshold |
| Assists | Kambi | observed on MLS event | player assist prices |
| Attempted dribbles | none in the usable combined feed | missing | do not synthesize |
| Tackles | RotoWire / PrizePicks relay | observed on live soccer rows | More/Less threshold |
| Crosses | RotoWire / PrizePicks relay | observed on live soccer rows | More/Less threshold |
| Fouls | none in the usable combined feed | missing | do not synthesize |

This is exactly **9/11** target families.  The threshold feeds are not
traditional sportsbook over/under prices.  Kambi carries actual odds for its
goals and assists markets.  Do not label the RotoWire `over`/`under` fields as
PrizePicks sportsbook juice without a separate contract check; the product is
More/Less pick'em, not a two-sided sportsbook market.

## Live evidence collected

### 1. Kambi MLS event data

The normal public Kambi event endpoint was read without authentication:

```text
https://eu-offering-api.kambicdn.com/offering/v2018/ub/betoffer/event/1025806485.json?lang=en_GB&market=GB
```

The event was FC Cincinnati vs New York City FC.  The relevant player-market
labels returned included:

```text
First Goal Scorer
Most Shots on Target (Settled using Opta data)
To give an assist (Settled using Opta data)
To score at least 2 goals
To score at least 3 goals
To score or give an assist (Settled using Opta data)
```

The live extraction counted the following **open outcome matches** after a
broad market-label search:

```text
Kambi open outcomes by target:
goal    112
assist  37
```

Those are evidence that the relevant markets were open, not normalized player
prop counts.  A production collector must classify the individual Kambi market
keys and preserve the provider event and player identifiers.

Kambi alone is not an 80% answer.  Across the broader fixtures examined, it
principally exposed scoring, assists, keeper saves, and a small amount of shots
on target; it did not expose passes, clearances, dribbles, tackles, crosses, or
fouls at the requested breadth.

### 2. RotoWire's public PrizePicks relay

This unauthenticated URL returned live JSON at the time of research:

```text
https://www.rotowire.com/picks/api/lines.php
```

This is a **multi-sport, multi-competition board**, not an MLS endpoint.  It
contains `markets`, `entities`, `events`, and `props`; its soccer rows can
represent any soccer competition that has active PrizePicks lines.  A prop
contains a numeric `line` under a `lines[]` member whose `book` is
`prizepicks`.  Current example rows observed from the response:

| Market | Player | Team | Line |
| --- | --- | --- | ---: |
| Clearances | David Affengruber | Elche | 4.5 |
| Crosses | German Valera | Elche | 3.0 |
| Passes Attempted | David Affengruber | Elche | 64.5 |
| Saves | Matias Dituro | Elche | 2.5 |
| Shots | Pierre-Emerick Aubameyang | Deportivo | 2.0 |
| Shots on Target | Pierre-Emerick Aubameyang | Deportivo | 0.5 |
| Tackles | Danny Leyva | Club Necaxa | 2.0 |

The command used to join market and player metadata to active PrizePicks soccer
rows yielded:

```text
RotoWire PrizePicks soccer target families currently present:
Chances Created
Clearances
Crosses
Goals Allowed
Passes Attempted
Saves
Shots
Shots on Target
Tackles

RotoWire PrizePicks soccer threshold records: 42
```

The active rows were **not MLS** (they included clubs such as Elche, Leon,
Club Necaxa, and Club Tijuana).  The last MLS match had started roughly 15
minutes earlier, and its pre-match prop rows had been removed at lock.  The
RotoWire frontend bundle references `/picks/api/lines.php` and
`/picks/api/alerts.php`; no public historical endpoint for PrizePicks lines was
found.  Do not claim an MLS board was captured from this run.

PrizePicks' own MLS editorial material confirms that MLS player thresholds are
offered (including passes attempted, goalie saves, fouls, and shots):

- https://www.prizepicks.com/playbook-article/orlando-city-inter-miami-prediction-lineups-picks-prizepicks
- https://www.prizepicks.com/playbook-article/how-to-play-prizepicks-soccer-fantasy-scoring-system-for-world-cup

That supports the coverage hypothesis, but the next MLS slate must be captured
and measured before it can become a data-coverage claim.

## Reusable soccer-league discovery surface

The RotoWire relay is useful beyond MLS: it is a single public discovery board
for active player thresholds across whichever soccer competitions PrizePicks is
listing.  The rows observed during this investigation came from non-MLS clubs,
which proves the board is not MLS-specific.

For any future soccer league, treat it as a **candidate discovery surface**,
not a league authority:

1. Read the complete board and retain its capture timestamp and payload
   fingerprint.
2. Resolve the event's teams and kickoff to the target league's independently
   published fixture inventory.
3. Count the actual market families for that league and slate; do not infer
   coverage from a different competition.
4. Keep the `rotowire_prizepicks_relay` source identity intact so its
   thresholds are never confused with the official league data or Kambi odds.

This could make a later EPL, La Liga, Liga MX, or other soccer-league addition
substantially cheaper to research.  It does not prove that every competition
has every market, or that a source row remains available after lock.

## Rejected alternatives

| Surface | What was verified | Why it is not the answer |
| --- | --- | --- |
| DraftKings | Current product navigation includes a subset of player props | Datacenter requests were blocked by Akamai; no supported free feed was obtained. |
| BetRivers | Public JSON event detail returned genuine prices | MLS player menu was limited to scoring, assists, and saves. |
| Bovada | Public coupon/event JSON returned genuine prices | MLS player coverage did not approach the requested statistic families. |
| Unibet KSP v2 | Public contest-page JSON returned genuine prices | Its player filter yielded only a goalscorer proposition for the tested MLS event. |
| PointsBet AU | Public MLS event detail returned 72 markets | The player markets were goalscorer variants, not the advanced stat families. |
| Ladbrokes/Entain AU | Public REST and persisted-query read paths returned a full MLS event card | The card had 125 mostly match/goal markets and no requested player-stat markets. |
| UnderDog | Public board returned soccer lines | It did not have MLS on the active board at the time checked. |
| PrizePicks direct API | It is the upstream product behind the promising thresholds | Direct requests from this host returned HTTP 403.  Do not attempt to evade that control. |

SofaScore and official MLS data remain useful for research, pre-match context,
and post-game validation; neither is a source of pre-match betting thresholds.

## Proposed capture contract — not implemented

No code, database, service, scheduler, or managed-DEV state was changed for
this research.  If implementation is later authorized, keep it source-separated
and published-first:

1. Poll only during a conservative pre-match window and save the complete raw
   RotoWire response before any event reaches lock.
2. Filter the broad board down to MLS by joining `props.entities[].eventID` to
   the board event, then verify its normalized home/away clubs against the
   MLS fixture inventory for that kickoff.  Do not treat `sport: Soccer` as
   MLS, and do not join by player display name alone.
3. Store source (`rotowire_prizepicks_relay` or `kambi_unibet`), raw event ID,
   raw player ID when published, market label, threshold/odds fields, capture
   timestamp, and the full raw-payload fingerprint.
4. Treat the sources as separate observations.  Do not overwrite a Kambi odds
   record with a PrizePicks threshold, and do not manufacture a two-sided price
   where the source only supplies a More/Less line.
5. Fail closed: if a board is absent, locked, partial, or cannot be matched to a
   canonical MLS fixture, retain the last-good snapshot with an explicit stale
   reason rather than inventing zeroes or copying a prior line forward.
6. Capture one complete upcoming MLS slate and report the actual distinct
   market-family counts.  Promotion requires that run to prove at least 9/11;
   the evidence in this document is not a substitute.

## Operational and policy caveats

- Both discovered URLs were reachable without an API key or paid subscription
  during research.  Neither is a documented, licensed developer data feed.
- Publisher terms, payload shape, availability, and geo behavior can change.
  Any automated collection needs a separate terms/compliance decision.
- Do not route around PrizePicks' direct API HTTP 403 or other anti-bot controls.
  The viable candidate above is the independently reachable RotoWire relay.
- The currently untracked Kambi prototype is in managed DEV at
  `/root/legendarypicks/backend/ingest_kambi_mls_props.py`; it is not present
  in this isolated worktree and was not modified here.

## Current state

| State | Status |
| --- | --- |
| Research | complete for the candidate route and evidence above |
| Candidate implementation | not started |
| MLS-slate 9/11 measurement | pending capture before the next MLS lock |
| Managed DEV | unchanged |
| Production | unchanged |
