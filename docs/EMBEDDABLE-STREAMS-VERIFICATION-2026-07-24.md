# Embeddable streams — empirical verification (2026-07-24)

> ## UPDATE 2026-10-07: audio lenience tiers, and the IPTV channels we can reach
> Added at Micah's request. The 2026-07-24 findings below are unchanged and still stand.
>
> ### Audio: the three tiers of lenience (Micah, 2026-10-03; full text `PLAYBOOK-radio-directory.md` section 0)
> 1. **Lenient leagues first, whatever their size.** Leagues and clubs that put their own audio out
>    free and unblocked: MLS and Leagues Cup, USL Championship and League One, NWSL, WNBA, MiLB,
>    college programs, NHL (free home and away audio in its own app), talkSPORT / BBC for English
>    soccer where reachable.
> 2. **Everyone else, when a free official route exists.** NFL, NBA, MLB local stations that stream
>    the game on their own page or on iHeartRadio / Audacy, shown with their blackout note.
> 3. **Take it down when asked.** A rights holder's request removes the entry the same day, logged in
>    `takedowns.json` so it is never re-added.
>
> The routing rule (same playbook, section 1): every listen action sends the user to the publisher
> (station page, team page, iHeartRadio / Audacy / TuneIn page or their official embed). We never
> host or re-stream the audio.
>
> ### IPTV: channels reachable from the prod server, measured 2026-10-07 ~22:45Z
> **Status: internal only.** Per the 2026-10-03 decision (`prediction-market-trading/docs/PLAY-BY-PLAY-SOURCES.md`)
> these are unauthorized re-streams used only to transcribe commentary for the trading agents;
> nothing in LegendaryPicks links to or plays them. Listing them here is NOT a decision to show
> them on the site; that would be a new decision for Micah.
>
> Quality is **measured**, not the label: ffprobe on a live segment of the best variant (width x
> height, frame rate, real bitrate), plus one frame looked at by eye. iptv-org's "(720p)" names are
> often wrong: FS1 is labelled 720p and is 1080p60. The playlist's own `RESOLUTION` matched the
> measurement on every stream checked, but a declared 1080p can still be a slate (CBS below).
>
> | Channel | Sport seen live | Measured | Proven how |
> |---|---|---|---|
> | FS1 | MLB playoffs, NCAAF | 1080p60, 6.5 Mbps | 2,359 transcript rows, 10-03 to 10-07 |
> | Tennis Channel 2 | ATP / WTA Asian swing | 1080p30, 4.5 Mbps | 2,638 transcript rows, 10-04 to 10-07 |
> | ESPNU | NCAAF | 720p60, 1.9 Mbps | 607 transcript rows, 10-03 to 10-04 |
> | NBC (iptv-org WTLV) | NFL SNF | 720p30, 2.8 Mbps | 93 transcript rows, 10-05 |
> | ESPN | live channel (ad break) | 720p60, 4.2 Mbps | live picture only |
> | ESPN2 | live channel | 720p60, 4.8 Mbps | live picture only |
> | NBC Sports Philadelphia (panel path `NBC-HD`) | regional, Phillies content | 720p30, 5.0 Mbps | live picture only; it is NOT national NBC |
> | MSG | regional (Knicks / Rangers) | 1080p60, 6.1 Mbps | live picture only (ad break) |
> | NBA TV | studio show | 1080p60, 5.5 Mbps | live picture only |
> | NHL Network | network programming | 1080p30, 4.4 Mbps | live picture only |
> | CBS Sports Golazo | live soccer (Bragantino v Mirassol, 16') | 1080p60, 4.6 Mbps | live picture only |
> | Willow | live cricket (ETPL) | 1080p30, 5.3 Mbps | live picture only |
> | CBS (panel path `CBS`) | none | 1080p30, 0.6 Mbps | **dead**: "this channel is not available" slate |
>
> Not found on the FS1/ESPNU panel (`85.237.89.160:9590/usa-s/`, no public listing; 26 channel
> names tried by path): ESPNEWS, SEC Network, ACC Network, FS2, FOX, Big Ten, CBS Sports Network,
> TNT, TBS, truTV, USA, MLB Network, NFL Network, RedZone, Golf, Tennis Channel, beIN, ABC.
> Of iptv-org's 449 sports streams, 243 answered and 113 declare 1080p; most of the 1080p ones are
> free ad-supported loop channels (ESPN8 The Ocho, PGA Tour, poker), not live games.
>
> Highest quality for live sport, measured: **FS1** (1080p60, 6.5 Mbps), **MSG** (1080p60, 6.1),
> **NBA TV** (1080p60, 5.5), **CBS Sports Golazo** (1080p60, 4.6), **Willow** (1080p30, 5.3),
> **Tennis Channel 2** (1080p30, 4.5), **NHL Network** (1080p30, 4.4).


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
