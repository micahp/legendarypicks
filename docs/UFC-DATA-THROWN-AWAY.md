# UFC data we are throwing away

Measured 2026-08-20 against dev `backend/data/picks.dev.db`, the live dev API
(`:8096`), and what ESPN actually publishes for the same fights. Every item
below is data the publisher hands us (or a fetch we already run) that we then
discard or never surface. Zero ESPN requests were spent on this document.

**TL;DR:** for a UFC fight that has props we store 48 stat fields per fighter in
`player_game_logs`, then the UI shows five of them. For a fight WITHOUT props
(Contender Series, any card we do not price) we store **nothing** — no stats, no
winner detail beyond the scoreboard snapshot. And the snapshot itself drops the
finish method for any fight captured before 2026-08-19 (code landed in `b9646f7`).

---

## 1. What ESPN publishes for one fight

From `sports.core.api.espn.com/v2/sports/mma/leagues/ufc/events/{event}/competitions/{fight}`
(the object the current-card ingest already fetches):

- competitors (fighter ids, order, **winner flag**, linescores ref, statistics ref)
- status (period/round, clock, state, completed)
- **details[]** — the fight timeline: Round Start, Takedown, "Fight Over", and the
  finish method detail (id + text). This is what `ufc_outcome` parses the method
  out of; **the timeline itself is discarded**.
- format (regulation periods — used only to *derive* "Decision", never stored)
- officials, venue, broadcasts, cardSegment, matchNumber
- capability flags: `boxscoreAvailable`, `summaryAvailable`, `playByPlayAvailable`,
  `commentaryAvailable`, `highlightsAvailable`, `previewAvailable`, `recapAvailable`,
  `gamecastAvailable` — **we use none of these surfaces**

Per fighter, from `.../competitors/{id}/statistics` (already fetched when the
fight has props):

- ~40 stats: knockDowns, total/sig strikes by position (distance/clinch/ground ×
  head/body/leg), takedowns (attempted/landed/slams/accuracy), advances (half
  guard/side/mount/back), reversals, submissions, timeInControl, target and
  position breakdowns

And `.../competitors/{id}/linescores` — per-round scoring. **Never fetched.**

## 2. What we keep today

| surface | kept |
|---|---|
| scoreboard snapshot | game_id, date, state, status, period, clock, home/away name+abbrev+record, **winner flag**, event name, card_segment; `outcome_method/round/clock` **only for fights captured after 2026-08-19** |
| player_game_logs (prop-linked fights only) | 48 fields: result (W/L/D/NC), method, round, clock_display, fight_time, fight_time_seconds, + all ~40 stats |
| game page | FINAL/name rendering, recap (winner now grounded — fixed 2026-08-20) |
| player page | "Recent Fights": Opponent, Date, Result, Sig Str (landed/attempted), Takedowns (landed/attempted) |

## 3. What we throw away, by pipeline stage

### 3a. Fights without props: everything
`ingest_ufc_fight_stats/load_targets` builds the work set from
`props JOIN prop_games WHERE league='ufc'`. A fight nobody priced — e.g. Dana
White's Contender Series 401903488, which has 0 props — gets **no** fighter
stats, **no** player_game_logs rows, and the game page renders
"Detailed stats aren't available for this sport yet."

That is the largest loss. The data exists; the ingest just never asks for
fights it has no market on.

### 3b. Snapshot: finish method for pre-08-19 captures
`ufc_outcome` (the method parser) and the `outcome_method/round/clock` fields
landed in `b9646f7` on 2026-08-19. Snapshots written before that (all UFC
finals captured earlier, e.g. the 08-18 Contender Series slate until we
re-captured it today) carry the winner flag but **no method**. The detail page
and recap therefore say "won" without "by decision / KO / sub" until the slate
is re-captured. `needs_refresh` retires a finished day, so nothing re-fetches
it automatically.

### 3c. Stats fetch: shape loss
`fetch_stats` keeps only `name → value` for each stat:
```python
return {item["name"]: item.get("value") for item in stats_list ...}
```
It drops `displayValue`, `abbreviation`, `description`, `type` for every stat,
and reads only `categories[0]` (the "All Splits" bucket) — any per-round split
category in the payload is discarded. The raw payload's `splits` dict also
carries the split id/name/type; discarded.

### 3d. Opponent stats
Each `player_game_logs` row stores the fighter's own stats and the opponent's
**name only**. The opponent's stat line exists only if the opponent is also a
prop target with their own row. One-sided matchups (one fighter priced, the
other not) store half the fight's numbers.

### 3e. Frontend renders 5 of 48 fields
The player page's "Recent Fights" table shows Opponent, Date, Result, Sig Str,
Takedowns. Stored but never rendered: knockdowns, the full strike breakdown
(9 position×target cells), advances, reversals, submissions, takedown slams +
accuracy, timeInControl, fight time, method, round, clock.

The game page has **no** boxscore surface at all for UFC (`hasGameTabs` is
false), even for fights whose stats ARE in `player_game_logs`. The model tab
explicitly zeroes UFC projections (`projKeys = []` for ufc).

### 3f. Fight timeline / officials / venue
`details[]` (every significant event with its clock), officials, venue,
broadcasts, format, and the per-round `linescores` are parsed (method) or never
touched, then discarded. The capability flags (`boxscoreAvailable`,
`playByPlayAvailable`, ...) exist on the object we already hold and we act on
none of them.

## 4. What it would take to stop throwing it away

| gap | size of fix |
|---|---|
| stats for non-prop fights | target the scoreboard card instead of/in addition to prop_games; run `fetch_stats` per fight on the card. The current-card ingest already fetches the card; this is a targets change |
| finish method on old snapshots | backfill/re-capture finished UFC slates once (one request per (league, day)) |
| per-round splits + stat metadata | read `splits.categories` fully instead of `[0]`, keep displayValue |
| opponent stats | write both rows per fight when both fighters resolve |
| render more fields | UI only — data already in `player_game_logs` |
| game-page boxscore | UI + one endpoint reading `player_game_logs` for the fight's two fighters |
| timeline/officials/venue | new ingest surface, not a fix |

## 5. Related

- The recap hallucination that surfaced this whole area (401903488 claimed
  "T. Trembley defeated R. Puga" when the snapshot says Puga won) is fixed in
  `8846f52`: `generate_game_story` now grounds winner + finish from the
  snapshot for scoreless sports instead of letting the model invent one.
- `docs/LEAGUE-STAT-GAPS.md` covers the *aggregation* side (what a leaderboard
  can claim from `player_stats`); this file covers the *capture and render*
  side for UFC specifically.
