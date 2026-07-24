# Embeddable streams — empirical verification (2026-07-24)

**Status:** verified findings, supersedes specific claims in two earlier research docs.
**Corrects:** `Free_Sports__Esports_Streams_for_Embedding.md` (video) and
`sports-audio-broadcasts.md` (audio). Both of those were desk research with no reachability
testing; several of their central claims do not survive contact with the actual endpoints.
Their strategic framing still stands — this doc only replaces the factual claims.

## Why this exists

Both prior docs asserted what is embeddable without ever fetching anything. This pass actually
hit every endpoint and classified the results. The headline correction: **the doc's #1 video pick
(PWHL) does not stream games on YouTube at all**, and **the audio path works but not the way the
audio doc describes** — you embed their player, you do not extract their stream.

## Method (reproducible, costs nothing)

- **YouTube**: reused the existing zero-quota scraper `_channel_streams()` in
  `backend/routers/esports/yt_live_resolver.py` — it parses a channel's `/streams` tab from
  `ytInitialData` and returns `{videoId, title, status}` where status is `live`/`upcoming`/`past`.
  Costs **zero** Data API quota. Titles were then classified full-event vs talk/press/reaction,
  because "channel has broadcasts" is not the same as "channel streams games."
  (The Data API `search.list` path is unusable for this — 100 units/call, and the shared key hit
  its daily quota after ~8 probes.)
- **TuneIn**: unauthenticated OPML API — `Browse.ashx`, `Search.ashx`, `Tune.ashx`, `render=json`.
- **iHeart**: unauthenticated `us.api.iheart.com/api/v3/search/all` +
  `api/v2/content/liveStations/{id}`.
- **Embeddability**: checked response headers for `X-Frame-Options` / CSP `frame-ancestors` — the
  only thing that actually decides whether an iframe will render.
- **Audio liveness**: time-bounded `curl` + `file(1)` to confirm real codec bytes, not just a 200.

Note on why local playback checks aren't required: `yt_live_resolver.py:24` records that embeds
load in the **user's** browser from a residential IP, so this host's datacenter bot-wall does not
affect production embeds.

## VIDEO — verified

Counts are broadcasts on the channel's `/streams` tab at time of check.

| League | Broadcasts | Full events | Live status | Verdict |
|---|---|---|---|---|
| **FIBA** (`@FIBA`) | 30 | **30 / 30** | **30 upcoming scheduled** | **Best pick.** Live full games today (`LIVE - Ireland v Netherlands \| FIBA U18 EuroBasket 2026`), zero talk padding, year-round international calendar |
| **PPA Tour** (pickleball) | 29 | **26 / 29** | archive (between events) | Real multi-court full sessions (`The LT Open (Championship Court) - Saturday Morning`) |
| **Major League Pickleball** | 30 | yes | archive | Real full playoff events on Grandstand court |
| **Call of Duty League** | 30 | yes | season ended 2026-07-19 | Full Championship Weekend day broadcasts. **Already wired in prod** (`streams.py` rule candidate `("call-of-duty", None, [("web", ".../@CODLeague/live")])`) |
| **ATP Challenger** (`@ATPChallengerTV`) | 1 | 1 | archive | Real (`Challenger Vancouver Live Stream Centre Court and Cambie`) but **only one broadcast** — Challenger coverage is fragmented across per-tournament channels, so it needs per-tournament resolution, not one channel |

## VIDEO — claims that FAILED verification

| Claim | Source | Reality |
|---|---|---|
| "**All PWHL games** are streamed on the League's YouTube channel" | prior doc, its top recommendation | **False.** Across all 30 broadcasts: **1** full event, **21** are reaction shows / draft / expansion announcements. PWHL games are not on that channel. If they stream anywhere free it is `thepwhl.com` — unverified |
| NWSL as a video source | evaluated this pass | **No full matches.** 15 "game-like" titles are all *pregame shows* (`NWSL Pregame Show \| Washington Spirit vs Portland Thorns`) plus press conferences / media day. Matches are on ESPN/Prime/Scripps |
| PLL (lacrosse) | evaluated this pass | **Press conferences only** — 30 broadcasts, all `Press Conference`. Games are on ESPN |
| NLL (lacrosse) | evaluated this pass | 2023–24 **junior and draft** content, no current pro games |
| **UFA** (ultimate frisbee) — "free game every Friday" | prior doc | **Unverifiable.** No working channel handle found (tried `@WatchUFA`, `@theaudl`, `@UltimateFrisbeeAssociation`, `@ufaultimate`, `@AUDLtv`). Not a "no" — an unknown |
| **DRL** (drone racing) | prior doc | **Handle is wrong.** The doc's lead resolves to `@DRLRacing`, an unrelated Tamil-language cricket/movie channel. Real DRL channel unresolved |

Also unresolved: **USL** (tried `@USLSoccer`, `@uslchampionship`, `@USL`). The prior doc's
**FIBA** and **CDL** entries are the two that held up.

## AUDIO — TuneIn verified (the prior doc's primary pick, confirmed)

All of this works with **no auth**:

| Piece | Result |
|---|---|
OPML API | `Browse.ashx?c=sports`, `Search.ashx?query=`, `Tune.ashx?id=` — all 200, `render=json` |
Team → station crosswalk | Works. Search surfaces dedicated team stations (`Boston Bruins` = `s137387`, subtext "Live stream every Boston…") and flagships (`ESPN LA 710` = `s32301`, `WFAN` = `s28671`, `670 The Score`) |
Stream metadata | `Tune.ashx` returns `url`, `bitrate`, `media_type`, `reliability`, `is_direct` |
Real audio | **Confirmed.** `ESPN LA 710` served 177KB of `audio/mpeg`; `file(1)` = MPEG ADTS layer III, 64kbps mono. 3/5 sampled stations direct-played (`audio/mpeg`, `audio/aacp`) |
**Embed player** | **Confirmed on 4/4 stations tested**: `tunein.com/embed/player/{guide_id}/` → HTTP 200 with **zero** frame-blocking headers (no `X-Frame-Options`, no CSP `frame-ancestors`) |

### The correction that matters: embed the player, do not extract the stream

The 2 of 5 stations that didn't direct-play returned `audio/x-scpls` (a PLS playlist). Resolving
one exposed why that path is a dead end:

- inner URL is `streamtheworld.com` carrying **`tdtok` and `partnertok` JWTs** minted for
  `DIST=TuneIn` with `"trusted_partner":true` and embedded lat/long
- those tokens are **time-bound and issued to TuneIn's player**, not to us
- fetching that inner stream directly **refused connection** (`http=000`) anyway

So raw extraction is simultaneously fragile (expiring tokens), partially blocked, and exactly the
licensing problem the audio doc flagged as caveat #1. **The iframe embed is the defensible path**
and it works uniformly across all stations including the PLS-backed ones. It also settles the ads
question cleanly: their player carries their ads, we monetize around it, we strip nothing.

## AUDIO — iHeart also verified (secondary, and already proven in-house)

- Unauthenticated `us.api.iheart.com/api/v3/search/all` finds team stations
  (`AM 570 KLAC — Dodgers Radio for Los Angeles`, `KFAN 100.3 — Audio Home For Minnesota Sports`).
- `api/v2/content/liveStations/{id}` returns `secure_hls_stream`; KLAC's HLS playlist returned
  **200 with real audio**.
- This is the **same mechanism already running in production-adjacent code**:
  `prediction-market-trading/broadcast_alpha.py` captures the World Cup feed from
  `stream.revma.ihrhls.com` via direct ffmpeg (`WC_STREAM` default `zc11554`), no bot wall.
- Breadth via keyword search is modest and uneven: football ~26 stations, basketball ~10,
  baseball ~9, hockey ~1 (most NHL flagships sit on Audacy/ESPN affiliates, a different platform,
  untested).

TuneIn is the stronger of the two for this use case: explicit team stations, a per-stream
`reliability` score, and a sanctioned embed endpoint.

## Coverage caveat that survives from the audio doc

Both caveats in `sports-audio-broadcasts.md` hold and are the real implementation cost:

1. **Feeds are per-team, not per-game.** These are 24/7 stations — `ESPN LA 710` plays fine right
   now in the NBA offseason because it's studio talk, not a game. Live play-by-play only exists
   inside game windows, so you need a **team → station map plus a schedule gate** to know whether
   the audio is a game or a talk show. `broadcast_alpha.py`'s `watch-wc` already implements exactly
   this shape (ESPN schedule + lead-time window) and is the pattern to copy.
2. **MLB audio is paywalled** (Gameday Audio) — skip or link out.

## What's still unexplored

Not checked at all this pass, in rough order of promise: league-owned HLS (**FIFA+** free full
matches, **EHFTV** handball, **Courtside 1891** FIBA's own platform, **Volleyball World**,
**World Rugby**, **thepwhl.com** — the likeliest home of actual PWHL games), Facebook/X streams,
and Audacy for the NHL flagship gap. FAST services (Tubi/Pluto/Samsung TV+) carry live sports but
are generally not iframe-embeddable.

## Recommended order

1. **FIBA video** — the only verified source with live full games scheduled *today*, and it needs
   no new plumbing: `streams.py` already supports a `youtube` platform with rule candidates.
2. **TuneIn audio for one big league** via iframe embed — matches the audio doc's own build advice
   (it suggested NBA as cleanest). Needs the team→station crosswalk + schedule gate.
3. **Pickleball (PPA/MLP)** when their season resumes — genuinely free full-event coverage.

Everything here was verified on 2026-07-24; stream availability and channel handles drift, so
re-run the method above before relying on any single row.
