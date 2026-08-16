# Capturing the booth — what it costs to listen to every game

**Audience:** investors and Micah. **Status:** costed proposal, 2026-08-10.
**Why now:** on 2026-08-09 the FS1 booth for América–Portland made a
narrative-level argument — *Leagues Cup de-risks a big cross-border signing,
because you now watch the player against both leagues regularly, while for a
smaller Liga MX club the few million coming back can make or break the season* —
that appears in **no article we can find**. We were recording the Portland radio
call at the time, a different booth, which never said it. The insight existed
for about ninety seconds and then was gone.

That is the thesis of this document: **the most valuable sports analysis is
spoken, not written, and nobody is capturing it.**

---

## 1. What this buys that scraping does not

Every competitor ingests the same things: box scores, the same wire copy, the
same handful of RSS feeds. Our own news engine does too — its corpus is 1,047
articles from ESPN and five blogs. That is a commodity input, and it means every
product built on it says roughly the same thing.

A broadcast booth is different:

- **Two to four hours per game of expert talk**, from people with team access,
  most of which is never written down anywhere.
- **The reasoning, not the result.** Box scores say what happened. The booth
  says *why it matters and what it costs* — which is exactly the layer our
  conversation cards are trying to occupy.
- **Two independent booths per game** (home and away radio) plus the national
  TV call: three takes on the same event, disagreeing in useful ways.
- **It is not indexed.** No search engine has it. That is the moat: a corpus
  that cannot be re-scraped by a competitor next week.

The counter-example from 08-09 is the point in miniature: the national booth had
the insight, the local booth did not, and neither was written down.

---

## 2. The physical setup

```
  audio sources                capture              transcribe            index
  ───────────────              ───────              ──────────            ─────
  club radio (public HTTP) ──┐
  national radio           ──┼─> ffmpeg workers ──> whisper (batched) ──> transcript store
  TV audio (subscription)  ──┘   1 proc / feed        30-60s chunks        + speaker turns
                                 tag = date_league_awayhome                       │
                                                                                  v
                                                                     signal extraction (LLM)
                                                                     -> claims, names, numbers
                                                                     -> conversation candidates
                                                                                  │
                                                                                  v
                                                                     news engine / cards
```

The pieces already exist and ran tonight: `broadcast_alpha.py` captures a stream
with ffmpeg and transcribes with faster-whisper; `20260809_LCUP_PORAME` is a real
93-chunk tape. What does not exist is scale, scheduling, and the discovery step
that turns transcripts into conversation candidates.

**Scheduling is the hard operational problem, not transcription.** You must know,
before kickoff, which feed carries which game. Tonight that took four wrong
guesses — the Timbers' own iHeart station was airing minor-league baseball, and
the app's designated Leagues Cup feed was airing a talk show. A station/feed
registry per team per league, verified by transcribing 40 seconds and checking
whether the words match the fixture, is a build item in its own right.

---

## 3. The cost, measured not guessed

### 3.1 How much audio there is

| League | Games/season | Hours/game | Hours |
|---|---:|---:|---:|
| MLB | 2,430 | 3.0 | 7,290 |
| NHL | 1,312 | 2.5 | 3,280 |
| NBA | 1,230 | 2.5 | 3,075 |
| NCAAF (FBS) | ~900 | 3.5 | 3,150 |
| MLS | 510 | 2.0 | 1,020 |
| NFL | 272 | 3.2 | 870 |
| UFC | ~42 events | 5.0 | 210 |
| **Total, one feed per game** | | | **~18,900** |
| Pre/postgame windows (+45 min/game) | | | ~6,000 |
| **Total with pre/post** | | | **~25,000 h/yr** |

Pre- and postgame are not padding — they are where the analysis lives. Tonight's
usable material was the postgame "measuring stick" segment, not the play-by-play.

### 3.2 Transcription

Measured on this box tonight (4 vCPU, faster-whisper `small`, int8, CPU only):
**40s of audio transcribed in 24s** — a real-time factor of ~0.6, so one live
feed occupies roughly 2.4 vCPU sustained.

| Approach | Unit cost | 25,000 h/yr |
|---|---|---|
| AssemblyAI batch | ~$0.12/h | **~$3,000** |
| Deepgram Nova-3 batch | $0.0043/min = $0.26/h | **~$6,500** |
| OpenAI Whisper API | $0.006/min = $0.36/h | **~$9,000** |
| Self-host GPU (2× L4 at peak, ~$0.75/h each, autoscaled) | — | **~$6,000–14,000** |

**The headline number: roughly $3,000–10,000 a year to transcribe every
professional game in North America.** Transcription is not the constraint. This
is the part investors usually assume is expensive, and it is not.

Storage is a rounding error: transcripts run ~1 MB per game-hour (25 GB/yr);
retaining the compressed audio at 32 kbps adds ~350 GB/yr, under $10/month.

### 3.3 Video subscriptions — where it actually gets expensive

| Service | Carries | ~Annual |
|---|---|---|
| [ESPN Unlimited](https://www.americantv.com/mlb-tv-to-espn-2026-prices-and-what-to-know-for-subscriptions.php) ($29.99/mo) | MLB from 2026, NFL, NBA, WNBA, college | $360 |
| YouTube TV or Fubo (~$83/mo) | FS1, TNT, CBS, NBC, regional | ~$1,000 |
| NFL Sunday Ticket (add-on) | out-of-market NFL | ~$586 |
| NBA League Pass | out-of-market NBA | ~$110 |
| MLS Season Pass (Apple) | all MLS + Leagues Cup | ~$99–149 |
| Peacock + Paramount+ | NFL/soccer/college overflow | ~$250 |
| **One full seat** | | **~$2,400–2,800/yr** |

**The trap is concurrency, not price.** Consumer subscriptions permit 2–5
simultaneous streams. Capturing 15 concurrent MLB games needs 4–8 accounts,
and automated capture violates the terms of service of essentially every one of
these platforms. Scaling the video tier is a **licensing** problem wearing a
subscription costume, and no amount of $30/month gets you out of it.

---

## 4. Why radio-first is the right answer

| | Club/national radio | TV subscriptions |
|---|---|---|
| Cost | **$0** (public HTTP streams) | ~$2,500/yr per seat |
| Concurrency | **Unlimited** | 2–5 per account |
| DRM | None | Yes |
| ToS exposure | Lower, still real | High — automated capture is prohibited |
| Feeds per game | **Two** (home + away) | One national call |
| Talk density | Very high — radio must describe everything | Lower; pictures carry the load |

Radio gets you ~80% of the corpus for ~0% of the licensing risk, and it is the
only tier that scales to every game in a league on day one.

**With the honest caveat this project learned the hard way:** on 08-09, the
national TV booth had the insight and the local radio booth did not. Radio is
the scalable base layer, not a complete substitute. A serious version captures
both, which is why the licensing question cannot be deferred forever.

---

## 5. Tiers to fund

| Tier | Coverage | Annual cost | What it proves |
|---|---|---|---|
| **0 — today** | 1 game at a time, manual | ~$0 | Works end to end; one real tape exists |
| **1 — one league, radio** | Every MLS or NFL game, both booths | **~$1–3k** | Feed registry + scheduling; first cards sourced from speech |
| **2 — all majors, radio** | ~25,000 h/yr, all 7 leagues | **~$5–15k** | The corpus nobody else has |
| **3 — radio + national TV audio** | + the national booths | **+$3k, plus legal review** | Highest-value takes; needs counsel |
| **4 — licensed** | Direct agreements | **$50k–250k+** | Rights to quote and redistribute at scale |

Tier 2 — *transcribe every professional game in North America* — lands at
**under $15,000 a year**. That is the number worth putting in front of an
investor, because it sounds impossible and it is not.

---

## 6. Legal posture — say this before you are asked

- **Capture for internal analysis** (transcribe, extract claims, never
  redistribute audio) is the defensible posture. **Rebroadcast is not**, and
  neither is publishing long verbatim passages.
- Product surfaces **derived insight with attribution** — "the FS1 booth argued
  X" — plus short quotes. That is a normal journalistic posture, not a rights
  grab.
- **Streaming ToS prohibit automated capture** on the video tier. Radio via
  public HTTP is a materially weaker restriction but not zero.
- The clean long-term answer is **Tier 4 licensing**, and the reason to build
  Tiers 1–2 first is to prove the derived product is worth paying for.

None of this is legal advice, and Tier 3+ should not ship without counsel.

---

## 7. What we would build, in order

1. **Feed registry** — team → station → stream URL, per league, with a verifier
   that transcribes 40 seconds and confirms the words match the fixture. Tonight
   proved this is the actual hard part: four candidate feeds, one correct.
2. **Scheduler** — read the fixture list, fire captures 45 minutes before
   kickoff (the runbook's own lesson: pregame is the highest-value window),
   tear down after postgame.
3. **Claim extraction** — turn transcripts into structured claims: who said it,
   what the stake is, which names and numbers appeared.
4. **Into the news engine** — claims become conversation candidates in the
   discovery pass that already exists (`docs/NEWS-DISCOVERY.md`), where a human
   approves them. A booth-sourced conversation would be the first signal in the
   product that no competitor can scrape.

---

## 8. The one-line version

Every game in North America, transcribed, for under fifteen thousand dollars a
year — a corpus of expert analysis that exists nowhere in text, feeding a
product whose competitors are all reading the same wire copy.
