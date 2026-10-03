# Playbook: a free game-audio directory (for Codex)

**Written** 2026-10-03 for Codex to build. Owner: Micah. The product model is The Varsity Network:
one place that lists, for every game, the free official audio for both teams. We copy that format
for every league we cover. We do not consume, host or re-stream anyone's audio.

Read before writing code: `.claude/skills/honest-data-ui/SKILL.md`, `.claude/skills/fail-loudly/SKILL.md`,
`.claude/skills/measurement-is-a-claim/SKILL.md`, `docs/sports-audio-broadcasts.md`,
`docs/EMBEDDABLE-STREAMS-VERIFICATION-2026-07-24.md`.

## 1. The rule (Micah, 2026-10-03)

> As long as I'm routing people to each radio stream directly (station websites or iHeartRadio),
> I'm good.

So every listen action sends the user to the publisher: the station's own page, the team's own
page, the aggregator's page for that station (iHeartRadio, Audacy, TuneIn), or that aggregator's
own official embed player. Concretely:

- **Allowed:** an external link to an official page; the publisher's official embed player where it
  is offered for embedding (TuneIn `tunein.com/embed/player/<guide_id>/` returned 200 with no
  frame-blocking headers on 4/4 stations, 2026-07-24).
- **Not allowed:** extracting a raw `.m3u8`/`.mp3`/`.aac`/`.pls` URL and playing it in our own
  player; proxying or transcoding a stream through our backend; framing a page whose owner blocks
  framing (iHeart and Audacy pages carry frame-busting); anything that works around a geofence or a
  blackout. The 07-24 verification already found streamtheworld URLs carrying `tdtok`/`partnertok`
  tokens minted for TuneIn's own player; extraction is both fragile and a licensing problem.
- **No logos, crests or helmet art.** Team names as text and team colors as plain blocks.
- **Never fabricate a callsign, frequency or URL.** This rule already heads `backend/data/radio-mls.json`.

## 2. What already exists (do not rebuild it)

| piece | what it is | status |
|---|---|---|
| `backend/data/radio-mls.json` (authoring copy `data/radio-mls.json`) | 31 MLS clubs, 18 `verified:true` (HTTP 200 audio probe, 2026-08-27), plus a `_wc` national entry | the POC |
| `lib/radio.ts` | maps a club to `/api/stream/<key>` | **conflicts with section 1** |
| `backend/routers/games/contexts.py` (`_LCUP_RADIO`, `_load_league_radio`) | ffmpeg relay: transcodes the publisher stream to MP3, one ffmpeg per listener | **conflicts with section 1** |
| `components/ListenLive.tsx`, `components/Game/BoothFeed.tsx` | the player UI and the booth transcript panel | keep the UI |
| `docs/sports-audio-broadcasts.md` | the strategy; caveats: feeds are per TEAM not per GAME, MLB audio is paywalled | read it |

**Decision for Micah before Codex touches it:** the ffmpeg relay re-streams station audio through
our server, which is not "routing people directly". Options: (a) replace the relay with link-outs and
official embeds, (b) keep it for the 18 verified MLS streams as-is, (c) keep it only for the booth
transcript pipeline (internal, not served to users). Codex does not change the relay until Micah picks.

## 3. League by league: what to check, not what to assume

Everything in this table came from a general web summary, not from us. Each claim is a lead; an
entry ships only with the evidence in section 5.

| league (ours) | likely free official source | known risk to verify |
|---|---|---|
| MLS (`mls`), Leagues Cup (`lcup`) | club pages, local English and Spanish stations | already 18/31 verified |
| NHL (`nhl`) | NHL app home/away radio, free | app-only: a link to the app or nhl.com page, not a stream |
| MLB (`mlb`) | local flagship stations | out-of-market audio is a paid MLB product; station web streams often substitute or black out game audio |
| NFL (`nfl`) | local flagship stations, NFL app (in-market only) | geofenced; national primetime on Westwood One affiliates |
| NBA (`nba`), WNBA (`wnba`) | local flagship stations | NBA out-of-market is paid; WNBA reportedly more open |
| NCAAF (`ncaaf`), NCAAB | school athletic site radio pages, Learfield's Varsity Network | link to the school's own listen page; Varsity is the format we copy |
| World Cup (`wc`) | `_wc` iHeart FOX Sports entry exists | event-only |
| EPL / UCL | talkSPORT, BBC Radio 5 Live | geofencing outside the UK; check from this box |

Priority order: finish MLS (13 unverified clubs), then NCAAF (Saturday volume, school-run pages), then
NHL (one league-wide source), then the rest.

## 4. Data shape

Follow the POC: one JSON per league in `backend/data/` (`radio-<league>.json`, authoring copy in
`data/`), keyed by **our** team code (the codes in `backend/team_codes.py`). Each team carries a list
of sources, home and away feeds come from looking up both teams of a game, and national feeds sit
under a `_national` key.

```json
{"_meta": {"updated": "2026-10-03", "league": "ncaaf", "note": "..."},
 "TEX": {"sources": [
   {"kind": "team_page", "label": "Longhorn Network Radio", "url": "https://...",
    "language": "en", "callsign": null, "verified_at": "2026-10-03T18:00:00Z",
    "verified_by": "http 200, page names the game broadcast", "blackout_risk": "unknown"}]}}
```

`kind` is one of `station_page`, `team_page`, `aggregator_page`, `official_embed`. There is no `stream`
field for new leagues (section 1). `blackout_risk` is `none`, `geofenced`, `paid_out_of_market` or
`unknown`, and the UI says it plainly.

## 5. Evidence per entry (fail loudly)

An entry is `verified` only with all of: the URL answered 200 from this box on the stated date; the
page names the team's game broadcast (not just the station); the publisher is the station, the team,
the school or the aggregator's page for that station. Record which check passed in `verified_by`.
Anything less ships as unverified and renders nothing. A team with no verified source shows no
listen button, never a guessed one.

Health check: a cron (or the existing ingest registry, `backend/ingest_registry.py`) re-probes each
verified URL weekly and the day of a game, and flips `verified` off with the failure on any non-200.
Do not claim a broadcast is live; "Listen on WBNS 97.1" is a fact, "LIVE" is not one we can check.

## 6. UI (honest-data-ui)

On the game page and the scores card: for each team, its sources as quiet text links in the team's
color, the language, and the blackout note when it is not `none`. External links open a new tab
(`rel="noopener"`). No logos. No accent color for presence; the accent marks absence ("no free
broadcast found") only where that absence is the information.

## 7. Scope lock for Codex

May create or edit: `backend/data/radio-*.json`, `data/radio-*.json`, a new `backend/radio_directory.py`
(loader + probe), a new route file `backend/routers/radio.py` registered the way other routers are,
`lib/radio.ts`, `components/ListenLive.tsx`, a new `components/RadioSources.tsx`, and tests for each.
Must not edit: `backend/_core.py`, `backend/espn_client/*`, `backend/routers/games/contexts.py` (until
Micah's decision in section 2), systemd units, timers, cron, settings, or anything under
`/root/prediction-market-trading`. Do not restart dev servers. Separate commits per league. Do not
push or release; Micah reviews.

## 8. Acceptance

- Every listen action opens an official page or official embed; zero raw stream URLs in new files.
- MLS: the 13 unverified clubs each end verified with evidence or explicitly unverified with the reason.
- NCAAF: every AP Top 25 school (current list: `prediction-market-trading/data/orderflow/_ncaaf_top25.json`)
  has a verified source or a recorded reason it has none.
- A test fails if any new source lacks `verified_by`, or if any new league file carries a `stream` field.
- Screenshots of the game page at 390px with and without a verified source.
