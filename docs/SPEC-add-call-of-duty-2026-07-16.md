# SPEC — add Call of Duty (CDL) to the /esports board (2026-07-16)

Status: **P1 SHIPPED to preview (2026-07-16).** Registered CoD across the 4 files below; verified on the
LIVE CDL Championship (4 matches, tier-0/prom-330, Bovada odds, YouTube embed resolving to a real live
video, 18/18 matcher_assertions). Preview backend :8096. Not on prod yet.

## P1 RESOLUTION NOTES (what was decided/corrected during implementation)
- **Display title = "Call of Duty"** (decision 1, per user).
- **Ship P1 now against the live Championship** (decision 3, per user).
- **Official CDL YouTube channel = `UCbLIqv9Puhyp9_ZjVtfOy7w`** (@CODLeague, 1.97M subs) — decision 2,
  resolved via YouTube Data API. ⚠️ `@CallofDutyLeague` (UC-VqDM9ogg-Q4urJjKneHxQ, **76 subs**) is a
  DECOY holding a similar handle — same trap as the EWC decoy; do NOT use it.
- **PandaScore slug correction:** the spec below said `/cod-mw/matches/...` works — it **404s**. The
  match-object `videogame.slug` IS `cod-mw`, but the **per-title feed path alias is `codmw`** (no
  hyphen) — same short-alias divergence as `csgo`/`dota2` vs videogame slugs `cs-go`/`dota-2`. So:
  `_PS_TITLES` gets `"codmw"`; `_PS_VG_TITLE` gets `"cod-mw": "Call of Duty"` (keyed on the match slug).
- **Stream wiring correction:** the spec's change #3 suggested `_WATCH_RULES` `("call-of-duty", None,
  [("youtube", "<channel>")])` — that produces a **broken** candidate (`_chan_url`/`_embed_url` can't
  synthesize a player URL from a bare YT handle). Correct path: channel_id in `_YT_TOURNAMENT_CHANNELS`
  (Data-API resolved, the EWC mechanism) for the live embed, PLUS a `web` `_WATCH_RULES` entry
  (`youtube.com/@CODLeague/live`) as the scheduled "where it'll air" fallback (KoG pattern).
- **Event-type awareness (per user):** CDL events come as *major qualifier / major / tournament* and —
  this season — **CoD Champs** (the finale). Wired into `league_tier.py`: CoD is Tier 0 by title
  (excluding "Challengers" which stays Tier 2, and qualifiers which demote to 2); `_stage_rank` treats
  "Cdl Championship"/"cod champs"/"champs" as an event-final (rank 0) so Champs outranks the mid-season
  Majors. ("champs" is safe — not a substring of "champions"; verified no misfire on EWC Champions.)
- **Live scores:** flow through the existing PandaScore enrich path automatically (map score/winner via
  the `codmw` feed) — no new score tracking built, as the user noted ("we already have the live score in
  track and scoreboard").
- **P2 still open:** team-name aliases harvested from the live board (casing noted: Bovada gives
  "Faze Vegas"/"Optic Texas"/"LA Thieves" — display-casing polish territory); Kalshi winner fallback
  only if PS proves lossy; wire Major-vs-Champs stage ordering more granularly once real Bovada Major
  league-strings are observed (regular season).

---

Recon done live — the risky parts are already de-risked (see below).

## Goal
Surface **Call of Duty League** matches on the `/esports` watch board — schedule, odds, live state,
scores, streams — and get **picks for free** (CoD flows into `/api/esports/upcoming`, so both
`/predict` and the board pick UI pick it up automatically). This closes the loop with
`docs/ESPORTS-PRODUCT-DIRECTION.md`, which uses the **CoD League analyst desk** as the model for the
whole pick product.

## Recon result — this is a registration/wiring job, not a new pipeline (verified live 2026-07-16)
- **Bovada is listing CoD RIGHT NOW**: esports coupon has `call-of-duty/cdl-championship`. Bovada is
  our schedule + odds + live-flag backbone, and a title only enters the board when its slug is in
  `_ESPORTS_TITLES` (`slate_sources.py:141`). So adding the slug lights up matches + moneyline +
  `_bov_live` immediately — and the CDL Championship is on, so there's live data to test against.
- **PandaScore covers CoD**: game slug **`cod-mw`** (verified via `/videogames`; `/cod-mw/matches`
  returns live CDL matches). So CoD gets the **same enrichment CS2/Dota get** — live status, scores,
  winner, team logos. It is NOT a data orphan.
- **GRID**: no CoD (`_GRID_LABEL_SLUG` = CS2/Dota only). Fine — PandaScore is the enrich source.
- **Streams**: official **Call of Duty League YouTube** channel via the existing YT resolver +
  `streams.py` known-channel defaults (same pattern as king-of-glory's web default).
- **Tier**: `league_tier.py` **already reserves** "Call of Duty League / CDL / CoD Champs" at **Tier 0
  (flagship international)** — it's commented as "not in the current feed (title lands ~mid-Jul)."

## Changes (minimal, file-by-file)

### 1. `backend/routers/esports/common.py` — register the title
- Add to `_ESPORTS_TITLES`: `"call-of-duty": "Call of Duty"`.
  - Display-title decision: **"Call of Duty"** (fan-clear) vs **"CoD"** (compact, matches CS2/LoL).
    Recommend "Call of Duty"; it's the same length class as "Rainbow Six"/"King of Glory". Whatever we
    pick becomes the `title` string keyed EVERYWHERE (picks/crowd/settlement key on it via `_key`), so
    choose once and don't rename later.
- `_TITLE_SLUG` (reverse map) derives automatically → `"Call of Duty" -> "call-of-duty"`, which
  `slate.py:549` uses for the stream-slug lookup.

### 2. `backend/routers/esports/pandascore.py` — enrich CoD
- Add to `_PS_VG_TITLE`: `"cod-mw": "Call of Duty"` (and defensively `"call-of-duty"`, `"cod"`).
- Add `"cod-mw"` to `_PS_TITLES` so the per-title feed `/cod-mw/matches/{upcoming,past,running}` is
  fetched (`pandascore.py:109`) — this is what supplies logos + past results that the global feed drops.
- **P1 acceptance check:** confirm `cod-mw` match objects carry the same fields the enrich path reads
  (`opponents[].opponent.image_url`, `results`/`winner`, `status`, `streams_list`) on a real live CDL
  match — parity with CS2/Dota is expected but verify, don't assume.

### 3. `backend/routers/esports/streams.py` — attach the official broadcast
- Add a known-channel default: `("call-of-duty", None, [("youtube", "<official CDL channel>")])`.
- **VERIFY the exact channel** (handle/ID) before wiring — the CDL broadcasts on YouTube; confirm the
  current official English channel. YouTube is already our top-priority platform (`_PLATFORM_PRIO`).

### 4. `backend/routers/esports/league_tier.py` — Tier 0
- The tier table already anticipates CDL at Tier 0. Ensure the **actual league strings** map there:
  Bovada's `cdl-championship` → `_slug_to_name` = **"Cdl Championship"**, plus generic "Call of Duty
  League" / "CDL". Add whatever literal strings the live board shows so the marquee event sorts to the
  top, not into the minor bucket.

### 5. (defer) `backend/routers/esports/kalshi.py` — winner fallback
- Only if PandaScore proves lossy on CDL results: add a Kalshi settled-market winner fallback, exactly
  like the existing minor-league fallback. **Don't build preemptively** — PS should cover it.

## Data coverage matrix (CoD)
| Need | Source | Status |
|---|---|---|
| Schedule + matchups | Bovada `call-of-duty/*` | ✅ live now |
| Odds / favorite | Bovada moneyline | ✅ |
| Live flag | Bovada `_bov_live` + PandaScore `status` | ✅ |
| Map score | PandaScore `cod-mw` | ✅ (no GRID realtime, PS score is enough) |
| Honest winner / finished | PandaScore `cod-mw` (Kalshi fallback if needed) | ✅ |
| Team logos | PandaScore `cod-mw` | ✅ |
| Stream | Official CDL YouTube | ✅ (confirm channel) |
| Picks / crowd | automatic via `/api/esports/upcoming` | ✅ no work |

## Team identity / casing (the one real watch-item)
CDL orgs — OpTic Texas, Atlanta FaZe, Toronto Ultra, New York Subliners, Los Angeles Thieves, Vegas
Legion, Carolina Royal Ravens, Miami Heretics, etc. Bovada and PandaScore may spell these differently
(e.g. `OpTic Texas` vs `OpTic Gaming Texas`, `FaZe` stylization). The existing `_canon_team` /
`_same_team` machinery + the new Class-A casing suppressor handle formatting variants; genuine
word-variants may need a couple `_TEAM_ALIASES`/`_XALIASES` entries. **Collect these from the live
board (P2), don't guess** — and run `matcher_assertions.py` after any identity change.

## State machine
CDL is a **Bo5 series** on YouTube — fits the existing SCHEDULED/LIVE/FINISHED/ENDED_UNKNOWN machine
unchanged. Winner/finished come from PandaScore (honest won-flag), never from a partial score.

## Scope guardrails
- **No new pipeline.** Reuse Bovada schedule + PandaScore enrich + YT streams. The whole change is
  data registration in 3–4 files.
- Don't touch shared `_same_team`/`_canon_team` logic to force CoD to fit — add narrow aliases only,
  scope-locked, with assertions.
- Run `matcher_assertions.py` (identity) after any alias/identity edit.

## Phasing
- **P1 (small):** register title (`common.py`), PandaScore `cod-mw` (`pandascore.py`), Tier-0 league
  strings (`league_tier.py`), official YouTube channel (`streams.py`). Result: CDL matches + odds +
  live state + scores + streams + picks on the board. Verify on the LIVE CDL Championship.
- **P2:** team-name aliases harvested from real board data; Kalshi winner fallback only if PS is lossy.

## Open decisions for the user
1. Display title: **"Call of Duty"** (recommended, fan-clear) vs **"CoD"** (compact).
2. Which official CDL YouTube channel is the canonical English broadcast to pin?
3. Ship P1 against the live Championship now (timely), or wait for the regular-season slate?
