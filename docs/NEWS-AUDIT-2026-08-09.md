# News engine audit — wanted vs. built (2026-08-09)

**Scope:** every session in Claude and Hermes from 2026-08-06 to 2026-08-09 in
which Micah stated what the league news engine should do, checked line by line
against the code, the DB, and the served API.
**Sources of record:** Hermes `state.db` messages (sessions
`20260806_153001_d66b40`, `20260807_091412_052fb3`, `20260807_191323_ec511a`,
`20260808_*`) and the Claude transcripts under `.claude/projects/-root/`
(`41794ef1`, `88a7b74d`). 39 news messages, 23 distinct requirements.
**Parent docs:** `PLAN-league-news-engine.md` (the engine),
`NEWS-FEEDBACK.md` (the editor loop).

Status is measured against what is on `dev` today, not what a commit message
claims. News remains **dev-only** — `/news` is absent from production by
decision (2026-08-09).

---

## 1. The requirement ledger

| # | Wanted (date, verbatim intent) | Status | Evidence |
|---|---|---|---|
| 1 | AI news whose only job is "understand what the most important narrative is in the league", plus granular trades / staff decisions / injuries to notable players (08-06) | **Built** | `news_items.layer` = narrative/trade/staff/injury; `news_narratives` cards |
| 2 | Micah's dictated topics are the seed — Dodgers salary cap, MLS promotion/relegation, SEC (08-06) | **Built, with a gap** | `CONVERSATIONS` in `ingest_league_news.py`; adding a topic still needs a code edit |
| 3 | Twitter is unavailable — find the signal another way; check Bluesky underdog-type accounts and these blogs (08-06) | **Built** | Bluesky search + Deadspin, Awful Announcing, FanSided, SB Nation, dotesports RSS + ESPN news API |
| 4 | News page in top-level nav; Home catch-all tab, per-league tabs (08-06) | **Built** | `pages/news.tsx`, `/api/news` |
| 5 | Separate real trades from speculation — no "realistic packages for Jonathan Taylor", no "top 10 trades that should happen" (08-06) | **Built; two leaks closed today** | `news_classifier.py` `speculation` layer, never served — see §2.3 |
| 6 | LinkedIn-trending-style AI summaries of what people are talking about (08-06) | **Built** | DeepSeek pass → `news_narratives` |
| 7 | Stop showing random people's social posts; combine them into a narrative worth mentioning (08-06) | **Built** | Bluesky rows are signal only — the API filters `source != 'bluesky'`, and they never become source chips |
| 8 | Top news on the Home tab should be all narrative (08-07) | **Built** | Conversation cards lead Home; the flat item list sits under them per the later 08-08 instruction |
| 9 | Add an esports category (08-07) | **Built** | `esports-worlds`, `esports-valorant` conversations; Esports tab |
| 10 | Drop "AI-generated from 0 sources"; list the sources, "and more" past two (08-07) | **Built** | `AiNarrativeCard` renders up to 2 source chips + "and more" |
| 11 | Extrapolate beyond direct support — the packed stadium, the highlight, the lower-division energy (08-07) | **Built** | `_TEXTURE_DIMENSIONS` crossed with every seed; sport-agnostic, not per-league hardcoding |
| 12 | Keep esports off the Home tab until it is good enough (08-07) | **Built** | `homeConvs` filter in `pages/news.tsx` |
| 13 | A fan's opinion must not read as if Legendary Picks is saying it (08-07) | **Partly built — see §2.1** | Prompt demands attribution and the paragraphs carry it, but the dedicated `fan_voice` sentence is generated, stored, served — and never rendered |
| 14 | A paragraph, not bullet points and a one-liner (08-07) | **Built** | `paragraph` field is the card body |
| 15 | Save every run so versions can be compared (08-07) | **Built** | `news_narratives_runs`, 73 runs, append-only |
| 16 | The headlines all sound the same — vary them (08-07) | **Built** | One batch DeepSeek call across all conversations + explicit variety instruction; current 8 titles are varied |
| 17 | No figurative language — "cranks to a boil", "holds the line", "reality bites"; read Elements of Style; drop "procedural" (08-08) | **Built** | Those exact phrases are named as forbidden in `_SYSTEM`; the "procedural move" sentence is quoted as the counter-example |
| 18 | Put trades/staff/injuries back into "More news" with the rest of the narrative items (08-08) | **Built** | `LeagueSection` merges `narratives` + `granular`, newest first |
| 19 | Get rid of the tags (08-08) | **Built** | No layer chips render anywhere |
| 20 | Dates as 2d / 4w / 3m / 4h (08-08) | **Built; was broken for cards — fixed today** | `relativeTime()`; see §2.4. Months render `mo`, because `m` is minutes |
| 21 | Explain the source tags (08-08) | n/a | A question, answered in conversation |
| 22 | An editor's pass — "that was bad, do less of that" — without having to define the boundary (08-09) | **Built** | `news_feedback.py` + few-shot marks; documented in `NEWS-FEEDBACK.md` |
| 23 | Keep news out of production (08-09) | **Held** | `/news` is dev-only; prod has no news tables |

**Verdict: 21 of 23 delivered.** One is a rendering gap (#13), one is a
workflow gap (#2). Both are in §3.

---

## 2. Defects found in this audit

### 2.1 `fan_voice` is generated, stored, served — and never displayed

`AiNarrativeCard` renders `title`, `narrative` and `paragraph`. `ai.fan_voice`
is in the type, in the API payload, and in every run of history — nothing
renders it. It is the one sentence that exists purely to make the fan's claim
sound like the fan's claim, which is what #13 asked for. The paragraphs do
carry attribution ("fans renewed calls", "Supporters quickly responded"), so
the card is not *wrong* today — but a field that is generated on every run and
shown to no one is either a missing line or dead weight. **This is a layout
call, not a bug fix — it is left for Micah.** (§3)

### 2.2 The reader saw the raw entity — `Purdue&#8217;s new AD`

SB Nation's Atom feed escapes entities **twice**, and nothing in the collector
unescaped them, so the literal `&#8217;` reached the page. 4 headlines and 16
bodies. Fixed: `_clean()` in `ingest_league_news.py` unescapes until stable,
strips markup that reveals, collapses whitespace — applied to all three
collectors, with `--repair-text` to re-run it over stored rows.

Every text column in **both** DBs was then scanned: no other surface carried
entities. The player-news path already parses with `convert_charrefs=True`.

### 2.3 Two classes of item were reaching the board that should not

**Substring matching.** The layer rules used bare `term in text`, so `sign`
matched *assignment*, `deal` matched *dealing*, `broadcast` matched
*broadcaster*, and `out for` matched *standout forward*. 44 of the served rows
rested on a match like that — this is the "multiple tags having a false
positive" from 08-07. Now whole-word, on hyphen-normalized text.

**Speculation served under another layer.** `speculation` is checked first,
but two headline shapes never matched it and were then caught by a later rule:

- *"This Commanders-Jaguars trade package for Walker Little is needed after
  Tunsil's injury"* → served as **injury** (the rule said `packages`, plural)
- *"Way-too-early MLB offseason trade candidates"* → served as **narrative**
  (the rule said `way too early`, unhyphenated; `offseason` was a narrative rule)

Both are precisely the trade speculation rejected on 08-06. Rules added,
and bare `conference` / `major` / `offseason` / `broadcast` removed from the
narrative rules — "press conference" and "major league" appear in ordinary
wire copy. Served rows 168 → 133 on the same corpus, every transition reviewed
by hand; the 32 classifier tests still pass.

### 2.4 "Newest first" was not newest first

`_iso()` only normalized RFC 822 dates that began with a digit, so
`"Thu, 06 Aug 2026 23:00:40 +0000"` was stored raw. `published` is sorted as
**TEXT**, and letters sort above digits — so every Deadspin / FanSided /
Awful Announcing row outranked every ESPN row regardless of its date, and the
per-league `LIMIT` was cutting real news off the bottom. 658 rows were in the
wrong shape. All dates are now one shape: UTC `...THH:MM:SSZ`.

### 2.5 Every card claimed to be fresh

`generated_at` is SQLite's `datetime('now')` — naive UTC. The browser parses
that shape as **local** time, so a card generated an hour ago read as being
from the future and `relativeTime()` clamped it to "now" permanently. The API
now serves it with the offset the value actually has.

### 2.6 The cron has never run

`legendarypicks-news.timer` is enabled and first fires **2026-08-10 03:35 CDT**;
`journalctl -u legendarypicks-news.service` has no entries. Prerequisites check
out (venv python, writable log, and the DeepSeek key resolves from
`/root/.hermes/.env` without needing an env var in the unit) — but the daily
path is **unverified end-to-end** until it fires.

`scripts/news-collect.sh`, which the systemd unit executes, was **untracked**
in git while already wired into the host. It is committed now.

---

## 3. Recommendations, in the order worth doing

1. **Decide the `fan_voice` line** (§2.1). Either render it under the title as
   the attributed "what people are saying" line, or drop the field from the
   prompt and the schema. Right now the model spends tokens on a sentence
   nobody reads, and the editor's verdicts are cast on a card that does not
   include it.
2. **Watch the first cron run** (03:35 tonight), then read
   `news_feedback.py --deletions` before reading the page — a declined
   conversation silently drops its served card, and that log is the only
   record that it was serving.
3. **Topics without a code edit** (#2). The strongest conversations are the
   ones Micah dictates; each one currently needs a Python edit and a deploy.
   A `news_conversations` table + `--add-topic` closes it. This is the
   highest-leverage remaining gap in the product loop.
4. **Two cards are both titled "Salary cap"** (MLB and NHL). The `title` is the
   short label above the headline; the batch prompt varies the *narrative* but
   never sees the titles as a set.
5. **`/api/news/runs` does not expose the run `id`.** Run history is served,
   but the id you need for `--verdict` / `--serve` is CLI-only, so the API
   cannot back a review UI later without a change.
6. **Publishers not yet read**: The Athletic, Bleacher Report, Yahoo Sports
   were named on 08-06 and are not sourced. Awful Announcing is sports-*media*
   news — most of its items are broadcaster stories, which is why it needed
   the narrative-rule tightening in §2.3. Worth deciding whether it belongs.

---

## 4. What changed on disk in this pass

| Commit | What |
|---|---|
| `8dc19cf` | The editor feedback loop, committed (was uncommitted working-tree work, plus the untracked `news-collect.sh` the host already runs) |
| `114c914` | Entity + date normalization at ingest, with `--repair-text` |
| `c63add6` | Whole-word layer rules; speculation leaks closed |
| `fe132cc` | `generated_at` served as UTC |

Dev DB repaired in place: 169 rows re-cleaned, 658 dates normalized, 1,163 rows
reclassified. Nothing was pushed and production was not touched.
