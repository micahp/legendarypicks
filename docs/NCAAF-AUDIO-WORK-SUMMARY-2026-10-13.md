# NCAAF audio work summary

**Date:** 2026-10-13

## What changed

Added 72 playable Varsity Network feeds to `data/radio-listen.json`, keyed by the ESPN team codes used by the scoreboard. Extended `lib/gameAudio.ts` to recognize NCAAF and let the existing game audio control select a matchup’s home or away team feed. Added coverage to `components/Scores/GameCard.audio.test.tsx`, including a live Iowa State–BYU playback case.

## Discovery and coverage

The search covered the 138 schools on the FBS roster, rather than just the AP Top 25. It found qualifying Varsity football event records for 77 schools: 72 direct stream URLs passed playback checks, and five URLs failed and were excluded. The other 61 schools had no qualifying record in the Varsity catalog records searched; that does not establish that they lack radio coverage from another source. The configured feeds comprise 51 MP3 and 21 AAC streams.

Each configured URL was checked with `ffprobe` and a three-second `ffmpeg` decode. The Iowa State–BYU URL recovered from the prior session log was `https://img.leanstream.co/IM7901-MP3` and is included. The first live query’s 20 audio records (eight football feeds across seven games) were only a snapshot; the broader search used published and upcoming event records.

## Verification

- All 72 configured stream URLs passed codec detection and a short decode; five discovered URLs failed and remain documented separately.
- The focused TypeScript compile for `lib/gameAudio.ts` passed.
- `components/Scores/GameCard.audio.test.tsx` passed: 12 tests. Jest emitted a React `act()` warning.
- `git diff --check` and the inventory-to-configuration audit passed.

## Files and limitations

The code and feed data are in `data/radio-listen.json`, `lib/gameAudio.ts`, and `components/Scores/GameCard.audio.test.tsx`. The complete feed list, failed URLs, event pages, and schools without a qualifying record are in [NCAAF audio streams](NCAAF-AUDIO-STREAMS.md).

These are event-linked publisher feeds and may change between games, so the inventory should be refreshed against future Varsity schedules. No changes were pushed or deployed, no services were restarted, and the main checkout was left untouched.
