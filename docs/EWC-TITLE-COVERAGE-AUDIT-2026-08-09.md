# EWC 2026 title coverage audit — 2026-08-09

**Status:** audit only (no implementation). Branch `fix/ewc-title-coverage`, worktree
`/root/lp-ewc-coverage` from `dev` (`08d2133`). The user correction: "pending" means **data
coverage** (we lack that title's schedule/results data), not branding. Branding is secondary.

## 1. What the UI currently shows

The Games tab on `pages/leagues/esports.tsx` renders 24 program tiles from
`backend/routers/esports/ewc.py` `EWC_TITLES` (25 tournaments; Mobile Legends = MSC + MWI).
Per tile: `Week(s) N` from the **hardcoded program catalog** (media-guide weeks, e.g.
`weeks: [5]` for CoD), and `N tracked matches` / `Match feed pending` from the client-side
count of projection matches matched against the tile's `feedTitles`.

Live projection today (managed dev `GET /api/esports/events/ewc-2026`, 2026-08-09):
80 EWC rows across **5 slate titles**:

| Slate title | Rows today | Maps to program tile |
|---|---:|---|
| Call of Duty | 28 | call-of-duty-black-ops-7 |
| Rainbow Six | 32 | rainbow-six-siege |
| King of Glory | 13 | honor-of-kings |
| Dota 2 | 6 | dota-2 |
| CS2 | 1 | counter-strike-2 |

→ **5 tiles show a match count; 19 tiles show `Match feed pending`.** `Schedule pending`
never renders for program tiles because every catalog entry carries hardcoded weeks — the
week label is a *program claim*, not data coverage (the gap the user called out).

## 2. Why: three distinct mechanisms

1. **No feed for the title (16 titles).** The normalized slate carries exactly 8 titles
   (`_ESPORTS_TITLES`: LoL, Valorant, CS2, Dota 2, Rainbow Six, King of Glory, Overwatch,
   Call of Duty). 16 program titles have no feed at all in our pipeline.
2. **Feed exists but EWC rows aged out (3 titles).** LoL, Valorant, Overwatch are feed titles,
   but their EWC weeks ran in July; the slate keeps finished rows only
   `LP_RESULTS_RETENTION_DAYS=7` (`slate.py:89`) and upcoming rows 14 days
   (`pandascore.py:583`) — their EWC matches are gone from the board.
3. **Feed exists and rows are inside the windows (5 titles).** CoD BO7, R6, HoK, Dota, CS2
   currently have rows (recent weeks or upcoming).

Presence ≠ completeness: e.g. CS2 shows 1 row today while its official week-7 program (Aug 12)
has more matches; the 5 "present" tiles must still be verified against the authoritative
published schedule.

## 3. Per-title matrix

Legend: **PRESENT** = feed rows inside retention/upcoming windows today; **AGED-OUT** = feed
title exists but EWC rows are beyond retention; **NO-FEED** = no feed in the pipeline.
Source page = authoritative Liquipedia MediaWiki page (all probed `exists` via
`action=query&prop=info`, 2026-08-09, permitted API channel).

| # | Program tile | Competition(s) | Program weeks (hardcoded) | Rows today | Class | Why | Source page (subwiki) |
|---|---|---|---|---:|---|---|---|
| 1 | Apex Legends | ALGS Split 1 | 1 | 0 | NO-FEED | not in slate feed registry | apexlegends:Apex Legends Global Series/2026/Split 1/Playoffs |
| 2 | Call of Duty: Black Ops 7 | CoD BO7 | 5 | 28 | PRESENT | codmw EWC window retained | callofduty:Esports World Cup/2026/BO7 |
| 3 | Call of Duty: Warzone | Warzone Resurgence Series | 4 | 0 | NO-FEED | not in slate feed registry | callofduty:Warzone Resurgence Series/2026 |
| 4 | Chess | Chess | 6 | 0 | NO-FEED | not in slate feed registry | chess:Esports World Cup/2026 |
| 5 | Counter-Strike 2 | CS2 | 7 | 1 | PRESENT | upcoming window (week 7 Aug 12) | counterstrike:Esports World Cup/2026 |
| 6 | Crossfire | Crossfire | 7 | 0 | NO-FEED | not in slate feed registry | crossfire:Esports World Cup/2026 |
| 7 | Dota 2 | Dota 2 | 1–2 | 6 | PRESENT | recent rows in retention | dota2:Esports World Cup/2026 |
| 8 | EA Sports FC 26 | FC Pro 26 WC | 3 | 0 | NO-FEED | not in slate feed registry | easportsfc:FC Pro 26/World Championship |
| 9 | Fatal Fury: CotW | Fatal Fury | 1 | 0 | NO-FEED | not in slate feed registry | fighters:Esports World Cup/2026/CotW |
| 10 | Fortnite Reload | Reload Elite Series | 7 | 0 | NO-FEED | not in slate feed registry | fortnite:Reload Elite Series/2026 |
| 11 | Free Fire | Free Fire | 2 | 0 | NO-FEED | not in slate feed registry | freefire:Esports World Cup/2026 |
| 12 | Honor of Kings | KWC | 5 | 13 | PRESENT | KoG rows in retention | honorofkings:Honor of Kings World Cup/2026 |
| 13 | League of Legends | LoL | 2 | 0 | AGED-OUT | feed title; EWC week 2 ran July, past 7d retention | leagueoflegends:Esports World Cup/2026 |
| 14 | Mobile Legends | MSC + MWI | 2–4 | 0 | NO-FEED | not in slate feed registry | mobilelegends:MSC/2026, MLBB Women's Invitational/2026 |
| 15 | Overwatch 2 | OWCS Midseason | 4 | 0 | AGED-OUT | feed title; EWC week 4 in July, past retention | overwatch:Overwatch Champions Series/2026/Midseason Championship |
| 16 | PUBG: Battlegrounds | PUBG | 3 | 0 | NO-FEED | not in slate feed registry | pubg:Esports World Cup/2026 |
| 17 | PUBG Mobile | PUBG Mobile WC | 5–6 | 0 | NO-FEED | not in slate feed registry | pubgmobile:PUBG Mobile World Cup/2026 |
| 18 | Rainbow Six Siege | R6 | 6 | 32 | PRESENT | R6 rows in retention (week 6) | rainbowsix:Esports World Cup/2026 |
| 19 | Rocket League | RL | 6 | 0 | NO-FEED | not in slate feed registry | rocketleague:Esports World Cup/2026 |
| 20 | Street Fighter 6 | SF6 | 4 | 0 | NO-FEED | not in slate feed registry | fighters:Esports World Cup/2026/SF6 |
| 21 | Teamfight Tactics | TFT | 3 | 0 | NO-FEED | not in slate feed registry | tft:Esports World Cup/2026 |
| 22 | Tekken 8 | T8 | 5 | 0 | NO-FEED | not in slate feed registry | fighters:Esports World Cup/2026/T8 |
| 23 | Trackmania | Trackmania | 7 | 0 | NO-FEED | not in slate feed registry | trackmania:Esports World Cup/2026 |
| 24 | Valorant | Valorant | 1 | 0 | AGED-OUT | feed title; EWC week 1 in July, past retention | valorant:Esports World Cup/2026 |

Counts: **PRESENT 5 · AGED-OUT 3 · NO-FEED 16**. All 24 titles have an authoritative
Liquipedia MediaWiki page (probed exists), so every "no data" tile is **fillable from an
authoritative published source** — schedule AND results — without inventing anything.

## 4. Proposed source + implementation plan (for approval — NOT yet implemented)

### Source
Liquipedia MediaWiki API per competition (the approved channel already used for the Club
Championship standings; terms allow API access, no HTML scraping, no request-path fetching):
one `action=parse&prop=text|wikitext|revid` call per title page (the 21 pages above, batched
per subwiki), gzip + descriptive `LegendaryPicks` UA.

### Fill (published-first, mirrors the standings pattern)
1. **Per-title published schedule snapshots** — operator-run fetcher
   `backend/fetch_ewc_title_schedule.py` (or extended fetcher) that, per title:
   - fetches the source page (one API call per title),
   - extracts the published schedule section (matches: date/time, participants, stage, score),
   - validates revision, event identity (EWC 2026, qualifier exclusion like the standings
     `is_ewc_2026_serie`), complete population per source, numeric dates, no TBD participants
     fabricated,
   - atomically publishes last-good per-title JSON under `backend/data/esports_ewc_schedules/`.
2. **API** — the projection's `titles[]` gains data-derived coverage fields: per title
   `schedule` (from the published snapshot: window/weeks, match count, first/last date) and
   `feedCount` (from the normalized slate). Tiles render **data**:
   - `schedule.status`/`weeks` from the published snapshot — `Schedule pending` when no
     published schedule is ingested (honest, data-true);
   - `feed pending` when the feed has no rows (unchanged, data-true);
   - the hardcoded program weeks are **removed from the tile label** (branding/program claim →
     replaced by data coverage; the program catalog stays only as the title directory).
3. **UI** — tiles + match view consume the coverage fields; no invented matches/participants/
   dates/scores anywhere; a title with a published schedule but no feed rows shows its real
   schedule with a `feed pending` marker on results.
4. **Verification (separate layers, in order):**
   - source payload: per-title API responses saved as fixtures (rev + checksum);
   - normalized data: parser/validator tests (dates, identity, qualifiers excluded, TBD
     handling, last-good);
   - API: route tests for the coverage fields;
   - UI: Jest tile tests + browser gate on the disposable preview (desktop + mobile,
     zero console/page errors) — preview only (`/root/lp-ewc-preview-BIEs6Q` :3105/:8105),
     no managed DEV, no DB write, no merge/push/deploy/tag.
5. **Honesty contract:** titles whose source publishes no schedule stay `Schedule pending`;
   titles with no feed stay `feed pending`; never invent rows. Branding (official tile art,
   colors) is out of scope unless required for data identity.

### Environment notes
- The prior worktree `/root/lp-ewc-2026` was removed externally; our esports work is preserved
  in `backup/esports-ewc-before-leagues-cup-20260808` (HEAD = `99e300e`) and `dev` contains the
  24-title catalog built by other agents (`e5c3cf2`, `1be39cf`, `3dd20e7`, `08d2133`).
- This audit lives on `fix/ewc-title-coverage` (`/root/lp-ewc-coverage`), isolated from dev.
