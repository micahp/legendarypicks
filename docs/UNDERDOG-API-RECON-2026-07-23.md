# Underdog Fantasy API recon (2026-07-23)

Triggered by: looking for a source of "expected significant strikes / takedowns / fight time"
for UFC to compare against for PrizePicks/Underdog-style lineup picks. PrizePicks' API 403'd
(blocked from this host). Underdog's did not.

## The endpoint

`https://api.underdogfantasy.com/beta/v5/over_under_lines` — no auth, no API key, plain GET,
reachable from this host. Returns one big snapshot (~8MB as of this check):
`{appearances, games, opened_lines_count, over_under_lines, players, solo_games}`. A raw copy
of one pull is saved at (not committed — 8MB, scratchpad only)
`/tmp/claude-0/-root/5f143334-ed34-4583-ad02-c4146e43e6bc/scratchpad/underdog_over_under_lines.json`
for anyone re-analyzing this without re-fetching.

**Shape**: `players[]` (id, name, sport_id, position, team_id) → `appearances[]` (id, player_id,
match_id) → `over_under_lines[]` (over_under.title, over_under.appearance_stat.appearance_id,
stat_value). Multiple lines per player-market at different price points are common (see UFC
fight-time below) — these aren't duplicates, they're Underdog's own multi-tier pricing.

## What's actually in it, per sport (this pull, 2026-07-23)

| sport_id | players | lines | real coverage |
|---|---|---|---|
| MMA | 26 | 345 | Significant Strikes O/U, Fight Time (Mins) O/U (multiple price points per fighter), Finishes O/U, Knockouts O/U, Submissions O/U, 1st/2nd Round Finish O/U — all real, tied to this weekend's card (verified: Abdul Hussein vs Cody Gibson, the same fight we ingested from ESPN tonight) |
| MLB | 118 | 858 | 52 distinct markets, including **1st-inning splits** (1st Inn. Batters Faced / Hits Allowed / Pitch Count / Runs Allowed / Strikeouts) that `bovada_scraper.py`'s `MARKET_MAP` does not cover at all today — a genuinely new market category, not a duplicate of what we already ingest |
| TENNIS | 48 | 362 | Real per-match markets (e.g. "1st Set Games Played (vs Opponent)") — directly relevant, tennis majors are already on the individual-sport-props roadmap |
| CS (Counter-Strike) | 139 | 280 | Real per-map Kills/Headshots for named pro players |
| VAL (Valorant) | 100 | 100 | Real per-map Kills for named pro players |
| LOL (League of Legends) | 60 | 253 | Real per-map Kills/Assists/Fantasy Points for named pro players |
| NFL | 346 | 925 | **Season-long futures only** (Season Receiving Yards O/U, Season Receiving TDs O/U, Regular Season Games Started O/U) — not per-game props. Checked specifically because this looked like it might close the "NFL off-season, zero live props" gap from tonight's EV/CLV work — **it does not**, these are draft-prospect/rookie-season futures, not weekly lines. |
| BASKETBALL | 16 | 16 | One market ("Points"), 16 players — thin, likely early/summer-league noise, not a real signal either way |
| CFB / CFL / KBO | 60 / 58 / 52 | 93 / 84 / 60 | Not investigated in depth this pass — flagged for later if any of these become relevant |

## What this does and doesn't unlock

- **UFC** (the original ask): real market lines for sig strikes / takedowns / fight time now
  exist as a comparison target for the projections we already built tonight from ESPN's
  per-fight stats. This is the missing "line" half of a real edge computation (projection vs.
  line), not something to build from scratch.
- **MLB 1st-inning props**: a real, live, new market category we don't currently ingest at all —
  worth a look independent of the UFC thread that led here.
- **Tennis**: a live source for the already-planned tennis-majors props work.
- **NFL**: does NOT help with tonight's separate finding that Bovada has zero live NFL props
  right now — Underdog's NFL board is season-futures only, same off-season gap either way.

## Open question / not yet decided

Underdog is a DFS pick'em platform, not a sportsbook — these lines carry no traditional
odds/vig (no American-odds price per side), just a threshold and Underdog's own fixed
pick-count payout structure. That means the existing EV math (de-vig fair-probability vs.
market-implied-probability) doesn't directly apply here — a line from this source could only
be compared against OUR OWN projection (real edge = our empirical hit-rate vs. their line), not
plugged into the same EV/CLV pipeline the sportsbook-sourced props use. Whether/how to
represent that distinction in the schema (a different `source` value on the existing `props`
table, e.g. `source='underdog'`, is the minimal change) is a design decision for whoever builds
the ingestion, not yet made.
