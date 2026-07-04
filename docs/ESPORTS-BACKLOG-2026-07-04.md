# Esports Backlog — 2026-07-04

Follow-up directions surfaced this session on `feat/esports-overwatch` (merged to `dev`, commits
`37d352c`..`8b9631f`). None of these are built yet — this is the punch list for next time.

## 1. PandaScore `number_of_games`/`games[]` wiring (high value, ready to build)

While chasing whether Kalshi/HLTV/egamersworld expose a live in-game score, found that PandaScore's
raw match object — which we already fetch via `_fetch_ps`/`_ps_enrich` — carries fields we never
read:

```
match_type: "best_of"
number_of_games: 5                          <- the Bo-format (Bo1/Bo3/Bo5)
results: [{team_id, score: 2}, {team_id, score: 1}]   <- running series score
games: [{position, status, winner, begin_at, end_at, length, ...}, ...]  <- per-map breakdown
```

Verified live on a real running match ("HOOCH vs SHOKE", CS2 grand final): `number_of_games=5`,
`results` showing 2-1, `games[]` with 3 completed maps each carrying a winner + duration.

**Why it matters**: this solves the "is this match actually over" problem better than the
GRID-`updatedAt` freshness gate built earlier this session (`_grid_live_fresh` in slate.py) — with
`number_of_games` we can compute "mathematically won" ourselves (`ceil(number_of_games/2)` wins)
independent of whether GRID/PS's own `finished` flag has flipped yet. It also unlocks:
- A real, context-aware live score ("2-1 in a Bo5", not a bare unlabeled "1-0")
- Per-map history for a future box-score UI (`games[]` already has position/winner/duration)

**Not built**: no code changes made this session for this. Needs: read `number_of_games` in
`pandascore.py`'s enrich functions, thread it through to slate.py's evidence dict, use it as an
additional "is it over" signal alongside the existing GRID/PS/Kalshi hierarchy, and optionally
surface `games[]` as map-by-map detail on the match card.

## 2. Kalshi as a second odds source for the visibility filter (paused mid-build)

Micah's ask: "Kalshi will have odds too" — `league_tier.py`'s `_has_real_odds()` currently only
checks Bovada's `favorite` field. Kalshi trades game-winner markets (`KXCS2GAME`/`KXVALORANTGAME`/
`KXDOTA2GAME`/`KXLOLGAME`/`KXOWGAME`/`KXCODGAME`) — an OPEN Kalshi market on a matchup should also
count as "has odds", same as Bovada. This would also close the Overwatch title-exemption gap in the
visibility filter (`_title_has_any_signal`) — Kalshi books Overwatch (`KXOWGAME`), Bovada doesn't.

**Not built**: reverted an in-progress edit to `league_tier.py` mid-session (user said "commit
before kalshi"). `_kalshi_esports_matchups()` (kalshi.py) already returns the open-matchup pairs
needed — this is a small, well-scoped addition: OR it into `_has_real_odds`/`_passes_visibility_filter`.

## 3. Kalshi's richer market data (explored, not wired in)

Beyond win/lose, a live Kalshi market object carries: `occurrence_datetime` (an independent
scheduled-start signal), `custom_strike.esports_competitor` (a stable per-team UUID — untested
whether Kalshi exposes a UUID->name lookup, could help team-identity matching if so),
`yes_bid_dollars`/`yes_ask_dollars`/`last_price_dollars` (live market-implied win probability — an
alternative/supplementary "favorite" signal, usable even for titles Bovada doesn't book), and
`volume_fp`/`open_interest_fp` (real trading activity — a possibly stronger tier/significance
signal than pattern-matching league names). None of this is wired in; flagged as a future
enhancement, not urgent.

Confirmed via the event-level endpoint (`/trade-api/v2/events/<ticker>`): Kalshi's own
`settlement_sources` for CS2 are **HLTV** (hltv.org/results) and **Gamers World** (egamersworld.com)
— Kalshi doesn't generate its own live game data, it settles off those.

## 4. HLTV / egamersworld — explored as potential data sources, verdict: not worth building against

- **egamersworld.com**: Cloudflare-gated for plain HTTP (403, JS challenge), but loads fine via
  headless Playwright/Chromium (confirmed, no bot-block once JS executes). Its own internal data
  model includes a `"panda":{"id":...}` reference — **it's built on PandaScore under the hood**,
  confirming PandaScore as the real authoritative source and making egamersworld strictly a fragile,
  Cloudflare-dependent middleman for data we can get directly. Also surfaced real stream metadata
  (official/language/viewer_count) we don't currently track, if ever revisited.
- **HLTV.org**: also loads fine via headless Chromium (no Cloudflare block, unlike the earlier plain
  WebFetch 403). Live match list shows a map/series score placeholder next to team names (was empty
  in the one snapshot checked — likely a lazy-loaded live widget, not confirmed empty-by-design).
  Micah confirmed the underlying **round-by-round live score is not crucial** — did not pursue
  further (would need a full headless-browser render in the request path anyway, which is exactly
  the "no browser in the request path" constraint the YouTube-embed work avoided).

**Verdict: don't build scrapers against either.** Both are Cloudflare-fragile and, for CS2 at least,
downstream of PandaScore data we already have direct API access to. Item #1 above is the actual
path to the same value (live series score/format) without the scraping risk.

## Frontend note

Board sorting/tiering is entirely backend-driven (`league_tier.py`'s `apply_tier_and_filter`) — the
frontend (`pages/esports.tsx`) just renders whatever order/fields the API returns, so this session's
tier work required zero frontend changes and already reflects live on `:3095`.

Current frontend tabs are **status-based only**: `Scheduled` / `Results` (`pages/esports.tsx:416`,
`457-458`). A **league-based tab/grouping view** (browse by league/tournament rather than just by
match status) has NOT been built — this lines up with the older "Leagues hub" idea already in
memory (`project_lp_esports_niche_direction.md`: "move Stats -> a 'Leagues' hub... each league its
own page with tabs"). Flagging explicitly here since it came up this session: the tier data
(`m.tier`, `m.league`) needed to build a league-grouped tab now EXISTS in the API response (added
this session), but the tab/UI itself is still just Scheduled/Results — no league-tab work has
started.
