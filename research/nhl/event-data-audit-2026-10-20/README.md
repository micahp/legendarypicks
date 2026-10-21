# NHL event-data coverage audit (2026-10-20)

Research-only feasibility audit for the next step toward "predict everything that
happens in an NHL game, then derive props from it". This directory answers one
question: **before anyone fits a simulator, how much of a game can we actually
reconstruct from official event feeds, and where do those feeds contradict the
official-label foundation?**

It fits nothing, evaluates no market, and writes nothing to the production
database.

## Two instruments, deliberately

| instrument | scope | answers |
|---|---|---|
| `audit_frame_ids.py` | **full frame** — all 4,876 games | do game and player IDs reconcile between the imported boxscore bodies and the label tables? |
| `audit_event_coverage.py` | **stratified sample** — 60 games per start season | which event fields exist, and where do the event feed and the labels disagree? |
| `audit_event_detail.py` | the same **300-game sample** | exact shot-field completeness, event-time lineup alignment, and reconciliation against approved quality-gated player labels |

The split is not laziness. ID reconciliation is cheap per game and a frame-level
fact; event reconstruction is ~120 KB of play-by-play plus ~290 KB of shift chart
per game, which is a network job, and field availability is a property of the
source that a sample settles. Every sampled rate is reported with its n and is a
statement about the sampled games, never about the frame.

## Sources

| what | endpoint / file | carriage |
|---|---|---|
| play-by-play | `api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play` | located shots, shot types, strength states (`situationCode`), penalties, rosters |
| shift charts | `api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={game_id}` | shift intervals per player, per period |
| official labels | `../official-outcome-backfill-2026-10-20/*.csv` | scores, team SOG, per-player SOG/TOI, appearance status |

Raw bodies are gzipped outside Git at `/root/lp-data/nhl-event-data-audit-2026-10-20/`,
one file per game per source, with a sidecar carrying the uncompressed and
compressed SHA256. `event_evidence_manifest.csv` is the tracked index. Bodies are
never overwritten: a validated body is reused, so a re-run costs nothing and a
failed fetch resumes.

## Running it

```sh
cd research/nhl/event-data-audit-2026-10-20
PY=/root/legendarypicks/backend/venv/bin/python

$PY select_sample.py            # deterministic sample (seed 20261021), prints its sha256
$PY fetch_event_evidence.py     # resumable; 1.1s between request starts; stops on 401/403/407/429/451
$PY audit_frame_ids.py          # full-frame ID reconciliation
$PY audit_event_coverage.py     # sample: per-game metrics, per-season coverage, contradictions
$PY audit_event_detail.py       # verifies all source hashes; compares approved eligible labels
$PY write_event_detail_report.py # writes REPORT-DETAIL.md from measured outputs
$PY write_report.py             # regenerates REPORT-EVENTS.md from the measured outputs
$PY -m pytest tests -q          # parsers + injected contradictions (network-free)
```

`fetch_event_evidence.py` accepts `--max-new N` for a bounded probe and
`--kind pbp|shifts` to fetch one source.

## What "contradiction" means here

Every check compares two independent instruments and reports disagreement instead
of resolving it:

- feed shot count vs official team SOG, per side, per game
- feed goal count vs canonical official score
- shift-summed TOI vs official per-player TOI (tolerance 30s, contradiction >60s)
- official participant with no shift rows
- feed roster ID absent from the label rows; goal scorer absent from the feed roster
- more than 12 players on the ice at once, from shift intervals

A mismatch is a finding for the audit, not a bug to paper over: a simulator built
on a feed that disagrees with the labels would inherit the disagreement silently.

## Extending to the full frame

The sample exists to keep the audit inside one session. Filling in the remaining
4,576 games is the same command with a different sample file:

```sh
# 1. write a frame-wide sample file (game_id, season, game_date, home_team, away_team, ...)
# 2. point the fetcher at it:  SAMPLE = HERE / "sample_games.csv" is module-level,
#    so copy the file or edit that constant
```

This audit recommends a separately scoped, staged research import; it did not
fetch the remaining games. At 1.1 seconds between requests, two requests for
each of 4,876 games imply about 179 minutes of request-spacing time alone, before
network latency or retries. The detailed report scales sample body sizes to a
rough compressed-size estimate. That size is not a full-frame measurement.

Do not repoint the stratified sample file in place for a full import. A full
import should have its own resumable manifest and immutable raw artifact store,
then publish full-frame coverage checks before event-derived model features are
used.

## Detailed field audit and schema

`REPORT-DETAIL.md` is the measured source for shot shooter identity, coordinates,
shot types, period/clock, PBP-vs-approved SOG/saves/shots-against/goals-against
counts, event-time shooter/goalie/situation checks, and missing/contradictory/
unusable game counts by season. It distinguishes direct `shootingPlayerId` from
the credited goal-scorer ID used for a goal's SOG credit. Quarantined and
not-applicable labels are never used as target values.

`PROPOSED-SCHEMA.md` specifies a source-preserving event, player-role, shift,
lineup-check, approved-label crosswalk, and issue-ledger contract. The detailed
reader only reads the frozen sample and approved outcome artifact; it does not
fetch feeds, change the frame or labels, or write production data.

## Known documentation defect found while auditing

`official-outcome-backfill-2026-10-20/README.md` and `frame_sources.json` pin
`canonical_frame.csv` to SHA256 `336d8a8d…`. The committed file actually hashes to
`f417a1272b2bb4adff5757dae398dd1000dd2284f43b6ccb7dd28eaae99edf2b` — which is the
value `research_label_source_pins.json` and `research_label_summary.json` already
record, and the value every script here verifies. The reader pins are right; the
prose pin is stale. Left untouched in this branch because it is another
directory's documentation, but it should be corrected before anyone quotes the
frame hash from the README.
