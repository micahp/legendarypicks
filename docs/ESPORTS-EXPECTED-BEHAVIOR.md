# Esports page — expected behavior & invariants

**Purpose:** the single reference for how the `/esports` page is supposed to behave, so fixes don't
regress each other. Read this before editing `backend/routers/esports/*` or `pages/esports.tsx`.
When you change behavior here, update this doc in the same commit.

Last updated 2026-07-09.

---

## 0. The page at a glance

Three views over one match list (`GET /api/esports/upcoming` → `{matches, source}`):

- **Live now** — matches happening right now; the featured one auto-plays a stream, the rest are
  tap-to-watch.
- **Scheduled** — upcoming matches (`!live && !finished`).
- **Results** — finished matches (`finished`), most-recent first.

The frontend split is purely `m.live` / `m.finished` (`pages/esports.tsx`, `LiveNow`/tab logic).
Everything else — identity, state, streams, logos — is decided in the backend and must be correct
*there*.

Sources, in identity-priority order (`_ORIGIN_PRIO`): **Bovada** (odds + schedule), **PandaScore**
(status/score/winner/logos/canonical names), **GRID** (realtime CS2/Dota score + honest finished
flags), **frag.se** (live-only feed + stream pool), **Kalshi** (settled winner fallback).

---

## 1. Match state machine

One state per match, derived once in `_derive_state` (`slate.py`). States:
`scheduled | live | finished | ended_unknown`.

Invariants (each born from a real incident — do not weaken without cause):

- **State is evidence, not carry-over.** A carried/previous-cycle row contributes IDENTITY +
  schedule only — never a live flag, score, or winner. (Killed the "stale scheduled ghost" and the
  "BetBoom stale 1-0 partial" bugs.)
- **No past-start match is ever emitted as `scheduled`.** A match past its start is live, finished,
  affirmatively delayed (a source says `not_started`, capped by `_DELAYED_CAP_MS`), or
  `ended_unknown`. This is why you can't "demote" a phantom-live match to scheduled — see §2.
- **Live evidence must be FRESH** (zombie-live fix): a GRID series whose `updatedAt` stopped ticking
  (`_LIVE_FRESH_MS`), or any source still claiming live past `_MAX_LIVE_MS`, does NOT count as live.
- **"It's over" is authoritative only** (GRID.finished / PS.finished / archived result / settled
  Kalshi when no source affirms live). A winner is never derived from a partial score.
- **`ended_unknown`** = the match is genuinely over but NO source had a result. It is KEPT (shown in
  Results), never faked and never dropped, and re-tried every cycle until a result lands. Persisted
  as `resultUnknown`.

### Phantom `running` (single-channel regional leagues)
PandaScore marks BOTH back-to-back matches on one broadcast channel `running` at once (verified: LRS
`9z v Volticons` + `Maze v ZEN`, both `running`, only one actually on air). The off-air one has an
empty `streams_list`. It resolves no stream → the visibility filter drops it (see §3, §4). Do NOT
try to fix this by forcing the card to `scheduled` (violates the past-start invariant).

---

## 2. Match identity & de-duplication

Goal: exactly one card per real-world match. Two layers.

### 2a. Canonicalization (`common.py`)
`_canon_team` / `_canon_tokens` build the key everything matches on. In order:

1. **ASCII-fold diacritics** (`_fold`): `Beşiktaş` → `besiktas` (accents were previously *stripped*
   to `beikta` and lost).
2. **Generic-aware camelCase split** (`_split_camel`): re-space `TeamOrangeGaming` → `Team Orange
   Gaming`, `TheBoys` → `The Boys` **only when a segment is a generic word**, so embedded
   `Team`/`Gaming`/`The` drop. Stylized single words are left intact — `eSports`, `BakS`, `paiN`
   must NOT split (splitting them broke `BakS eSports` == `BAKS Esports`).
3. Lowercase, drop generic org words (`_TEAM_GENERIC`: gaming/esports/team/clan/gg/the/of/fc…).
   **`academy` is deliberately NOT generic** — an academy squad is a different team.
4. Resolve acronym aliases (`_TEAM_ALIASES`: `wbt→wrotberry`, `navi→natusvincere`,
   `powerranger(s)→poorrangers`, `jplay→justplayers`).
5. **`ex-` is KEPT, not stripped.** `ex-Marsborne` (the departed roster) is a DIFFERENT competitive
   entity from `Marsborne` (the org's new lineup). Liquipedia/HLTV confirmed; Micah 2026-07-09.
   Canonical keys: `exmarsborne` ≠ `marsborne`.

`slate.py:_XALIASES` adds a second alias layer for cross-source names with no lexical bridge
(`nip→ninjasinpyjamas`, `anyoneslegend/agalinternational/allgamers→agal`, `bb→betboom`).

### 2b. `_same_team` (slate.py)
"Are these the same team?" — canonical equality, exact anagram (`Dontsu`/`Donstu`), a **word-token
affix** match whose residual is a known-droppable suffix (`_MERGE_OK_SUFFIX` = stars/galaxy/kia/
globant/w7m/lmap only), or a vowel-elided abbreviation (`LVLUP`==`Level UP`, via consonant skeleton
— bidirectional, NOT "shorten the full name").

**The affix policy is a fail-closed ALLOWLIST.** An unknown residual word ⇒ SPLIT. These are
**deliberately different teams** and must stay separate (researched, Liquipedia-verified):
`MIBR` ≠ `MIBR LOS`, `G2` ≠ `G2 HEL`, `Vitality` ≠ `Vitality Rising Bees`,
`Team Secret` ≠ `Team Secret Whales`, `FaZe` ≠ `FaZe Up Next`, main ≠ `… Academy`. **Do not add
`los`/`whales`/`hel`/etc. to the allowlist.**

### 2c. Relaxed same-match merge (`_same_match_relaxed`, slate.py)
Some dupes are the same *match* cross-listed under two league strings with a team-name variant the
strict matcher (correctly) won't merge — e.g. `Yawara v Sharks` (RES Showdown) vs `YNG Sharks v
Yawara` (BLAST Open). Loosening `_same_team` to catch these would reopen the curated splits above.

Instead we use a **physical invariant: a team cannot play two matches at once.** Two same-title rows
within `_RELAXED_MERGE_MS` (10 min) that share ONE exactly-matched team (strict `_same_team`) are the
same match. The other side only needs to be a **label variant** (`_label_variant`: shares a token,
and the differing tokens contain no `_DISTINCT_SQUAD` marker — academy/ii/women/**ex**/…). This keeps
`_same_team` (and MIBR≠MIBR LOS) untouched while de-duping the physically-identical rows.

### 2d. Display name after merge
`_cluster` picks the base row by origin priority, then prefers PandaScore's canonical spelling over
Bovada's label (`Power Ranger`→`Poor Rangers`), aligned via `_same_team` so a reversed pair can't
swap names onto the wrong sides. This is why `Level UP` shows instead of `LVLUP` almost everywhere —
the only exceptions are LMap rows (§5).

### Regression guard
There is no committed unit suite; keep a positive/negative pair list when touching the matcher
(scratch harness used 2026-07-09: 21 positives incl. Beşiktaş/TeamOrange/TheBoys/JPlay/BakS, 12
negatives incl. MIBR/G2/Secret/ex-Marsborne). Every negative staying SEPARATE matters as much as the
positives merging.

---

## 3. Streams (`streams.py`, `yt_live_resolver.py`, frontend `LiveCard`)

Every source contributes CANDIDATES into one pool; the pool is ranked and the best becomes `watch`,
the rest `alternates`.

Backend rank (`_pick_stream._rank`): `(embeddable, foreign, platform[youtube<twitch<kick<web],
liveness-confidence, main+official, english)`. Note **foreign is ranked before platform**, so an
English Twitch main outranks a foreign-language YouTube co-stream — this is the desired policy
(English preferred; a foreign YouTube is NOT auto-hoisted).

Rules:
- **Twitch liveness is verified via decapi even when a source attests the stream.** Attestation goes
  stale; a decapi-confirmed-offline Twitch must never ship as live (killed the dead foreign co-stream
  `locomass22` outranking a live Kick). Kick is unverifiable from our datacenter IP (Cloudflare 403)
  → attestation-only. YouTube has no free liveness endpoint.
- **Never ship a dead link.** If every candidate is positively dark AND unattested, `_pick_stream`
  returns `None` (not an offline-flagged link). The visibility filter then drops the match if it also
  has no odds — this is what removes the phantom-`running` card (§1) instead of showing
  "no stream embedded · TWITCH ↗" on a channel that never carries that game (e.g. regional LoL
  falling back to the global `riotgames` rule).
- **YouTube resolution** confirms a real embeddable video id, fail-CLOSED (any ambiguity → None →
  Twitch/Kick wins). Multi-game tournament channels (EWC runs Valorant+Dota+CS2+ALGS at once) are
  narrowed by GAME first (`_GAME_KW`), then arena tag / team names.
- **Frontend switcher does NOT re-sort.** It uses the backend order as-is (`pages/esports.tsx`
  `LiveCard`). The backend already gives English-YouTube-first + liveness/language ordering; a fixed
  platform re-sort would (and did) hoist a dead foreign Twitch above the live Kick. Default source =
  backend primary. Featured card auto-plays index 0.

**YouTube playback:** real YouTube embeds play fine for end users (residential). The "sign in to
confirm you're not a bot" wall only hits THIS datacenter IP, so YouTube playback can't be verified
from here — but it works, and YouTube-default is correct.

---

## 4. Visibility filter (`league_tier.py`)

The board's purpose is matches you can watch or bet on. A **live/finished/ended_unknown** match with
NEITHER real odds NOR a resolved stream is dropped. A **scheduled** match is never dropped on this
basis (a market/stream often just hasn't posted). A whole-title coverage gap (e.g. Overwatch: no
Bovada markets + no stream rules) is guarded so the filter doesn't silently delete an entire title.

`/api/esports/upcoming` returns the POST-filter list, so what the API returns == what renders.

---

## 5. LMap 2 rows

Bovada lists per-map betting lines as separate events (`Power Ranger - LMap 2 vs GamerLegion -
LMap 2`) — sub-match markets, not matches (they rendered as phantom rows with absurd ~95% favorites).
They are filtered on the live Bovada path (`slate.py`, regex `\bl?map\s*\d` on the description). Any
`- LMap 2` rows still visible are **stale carried/archived rows** aging out of the 3-day results
store — they have no series result, so they show as blank/`ended_unknown` in Results, and their team
names keep the abbreviation (`LVLUP - LMap 2`). These are the same games we "have no result for."
TODO: also strip the `- LMap N` suffix / drop these from the archive path so they don't linger.

---

## 6. Results tab specifics

- A finished match shows the winner (loser dimmed) + map score when known.
- `resultUnknown` matches currently render as a bare "Final" with no score and no explanatory label —
  **the frontend does not render a "result unavailable" label** (`resultUnknown` is computed in the
  backend but unused in `esports.tsx`). Known gap: these read like broken Finals.
- **EWC (Dota especially) is the main result hole**: ~20 of the "no result shown" cards are EWC/World
  Cup, plus a handful archived as `finished` with no winner+score (should be `ended_unknown`). Root:
  no source (PS/GRID/Kalshi) returned an EWC Dota result. TODO: fix EWC result resolution; relabel a
  `finished`-with-no-result as `ended_unknown`.

---

## 7. Logos (`pandascore.py`)

Lookup order per team: feed-harvested index by canonical key (`_ps_logo_for`) → PandaScore *teams*
API fallback (`_ps_team_logo_api`) → cached to `data/esports_team_logos.json`.

Two facts that bite:
- **The API-fallback cache stores NEGATIVES permanently** ("queried once, no crest, `''`"). If a team
  was queried before its crest existed (or matched a crest-less duplicate like `ex-Marsborne`), it's
  cached empty and never retried. `marsborne`/`hive`/`syf` are currently stuck negatives; the `ex-`
  fix (§2a) means a re-query would now find the real `Marsborne` crest. TODO: expire negatives / a
  way to invalidate.
- **PandaScore genuinely lacks crests for many minor/regional teams** — of 26 missing logos audited
  2026-07-09, 22 were true PS gaps (555, Tricksters, UNO MILLE, mellren, …). Not fixable via PS.
- **Some logos exist only on tournament sites**: e.g. Poor Rangers (post-rebrand) has a crest on the
  EWC participants page but not in PS. Would need an EWC/tournament logo source to recover.

So a missing logo is *usually* genuine upstream absence, NOT a naming miss — the canonical-key index
already covers spelling variants (0 index-level naming misses in the same audit).

---

## 8. Known open follow-ups
- LMap `- LMap N` rows: strip suffix / drop from archive so they don't linger in Results (§5).
- EWC (Dota) result resolution; relabel `finished`-no-result → `ended_unknown` (§6).
- Frontend: render a "result unavailable" label for `resultUnknown` (§6).
- Logo negative-cache expiry; optional EWC/tournament logo source for Poor-Rangers-class gaps (§7).
- `Imperial v LP` dupe: "LP" = "Largados y Pelados" but too generic to alias globally — needs a
  scoped decision (§2).
