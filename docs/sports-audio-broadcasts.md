# Sports audio broadcasts — a live anchor for leagues we can't show on video

## The idea (Micah's)
Live **video** for the major leagues (NBA, NFL, MLB, NHL, soccer) is rights-locked — we can't
embed it the way we embed an esports stream. But live **audio** (radio play-by-play) is a different
rights market: it's widely available for free and is already aggregated by platforms that hold the
licenses. So audio can be the **live anchor** for the big traditional leagues, paired with our live
data overlay — "listen to the call, watch the numbers." This is *only* about non-esports; esports
already has the video embed.

## What's actually tappable

### TuneIn — the strongest option
- Streams **live play-by-play for NFL, MLB, NBA, NHL, NCAA football, NCAA basketball, and Premier
  League**, plus general sports-talk radio. Free, ad-supported (Pro removes ads).
- Has a **[Broadcasters API](https://tunein.com/broadcasters/api/)** and embeddable players, so a
  station/stream can be surfaced programmatically.
- TuneIn carries the licensing with the leagues/broadcasters — so using *their* feed is the legal
  path, vs. trying to source a raw stream ourselves.

### iHeartRadio — secondary
- Thousands of live AM/FM + online stations including local **sports radio with live play-by-play**.
- Similar model (licensed aggregator); embeddable player.

### League / team direct
- Most NBA/NHL/NFL teams stream their **radio broadcast** free on team sites / league apps / TuneIn.
- **MLB** audio (Gameday Audio) is good but **paywalled** (MLB.tv/At Bat).
- National vs local: some feeds are team-specific (home/away radio), not a single national call —
  matching the right feed to a given game takes a small crosswalk.

## How it fits Legendary Picks
The product was never the broadcast — it's the **data layer**. Audio just gives the big leagues a
live "anchor" so the second-screen experience works where video can't:

> **Audio play-by-play (TuneIn/iHeart) + our live win%, player-vs-line tracking, and "moment that
> matters."** You listen to the game and watch the data turn — same loop as the esports video view,
> just an audio anchor instead of video.

It also pairs with the **non-live** mode we already have: even without audio, the projection-vs-line
board works pre-game; audio makes it *live* for NBA/NFL/MLB without a video license.

## Honest caveats (verify before building)
1. **Embedding terms.** TuneIn/iHeart players are embeddable, but confirm their ToS allows it on a
   commercial site; the stream carries *their* ads (we don't strip them, we monetize around).
2. **Game-to-feed crosswalk.** Radio feeds are often per-team, not per-game — need a small mapping
   (team → live station) to attach the right call to the right matchup.
3. **MLB audio is paid** — likely skip or link out.
4. **Latency/availability** varies by league and local market/blackouts.

## Verdict
Audio is a genuinely good unlock for the **big US leagues** (NBA, NFL, NHL) where video is off the
table — a free/licensed live anchor via TuneIn, with our data overlay as the actual product. Build
order: prove the data overlay first (esports/MSI, live), then add the **TuneIn audio anchor** for one
big league (NBA is cleanest — free team radio, large audience) as the traditional-sports counterpart.

**Sources:** [TuneIn sports radio](https://tunein.com/radio/sports/), [TuneIn Broadcasters API](https://tunein.com/broadcasters/api/), [iHeartRadio via TuneIn](https://tunein.com/radio/Stream-iHeartRadio-c100005513/).
