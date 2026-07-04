# Per-game league registry — esports live board

**Date:** 2026-07-04 (rev 2 — upgraded taxonomy). Snapshot of every league/tournament string on
the live board (`/api/esports/upcoming`, 289 matches) plus known rotators (BetBoom, Gamers Club,
CDL), classified per game. Purpose: ground the tier sort in what each league IS *within its own
game*, and pre-classify each game's absent majors so they sort correctly the day they return.

## Classification (upgraded from Major/Feeder/Noise — grounded in real industry convention)

The original 3-bucket scheme (Official/Major, Minor/Feeder, Noise) collapsed two genuinely
different things into "Feeder": a real regional pro league (VCL, Prime League) and a nascent
amateur pilot league (TESFED) aren't the same level, even though both are "below Major." Verified
against how the industry actually tiers competition before finalizing this:

- [Liquipedia:Tiers](https://liquipedia.net/starcraft2/Liquipedia:Tiers) — the real cross-game
  convention is a 5-level **S/A/B/C/D-Tier** scale (S = outstanding prize pool, offline, best teams
  worldwide; A = high-level online/regional; B = smaller prize+prestige but still high-level
  competition; C = very small prize pool, little prestige; D lower still).
- [CS2 Valve Regional Standings](https://www.esports.net/wiki/guides/valve-regional-standings-explained/)
  — Valve's own Tier-1/Tier-2 split is narrower and specific to Major-qualifying invites, not a
  general taxonomy — confirms tiering is inherently game/purpose-specific, not one universal rule.
- [Category:Showmatch Tournaments (CoD Esports wiki)](https://cod-esports.fandom.com/wiki/Category:Showmatch_Tournaments)
  — showmatches are an explicit, SEPARATE category from tiered competitive tournaments industry-wide,
  not a lower rung of "amateur." Confirms BetBoom Streamers Battle needed its own bucket, not just
  "worse than TESFED."

**Four tiers** (maps our board onto that real S/A → B/C → D → Showmatch shape):

| # | Name | Definition | Roughly maps to |
|---|---|---|---|
| **0** | **Major/Pro** | The top circuit FOR THAT GAME — international flagship, or (where a game has no higher international layer) the game's own premier league | S/A-Tier |
| **1** | **Semi-Pro/Minor** | Real, officially-sanctioned organized competition, real orgs/paid players, genuinely building toward or feeding the top circuit, but not itself the top | B/C-Tier |
| **2** | **Amateur/Development** | Organized competition but grassroots/nascent/qualifier-stage — real stakes, unproven or unrecognized teams, explicitly a development/pilot ladder | C/D-Tier |
| **3** | **Novelty/Exhibition** | Not on the competitive ladder at all — showmatches, streamer/celebrity events, entertainment-first | Showmatch (separate) |

Qualifier-demotion rule (kept, generalized): a league string containing "qualifier"/"last chance"
is capped at **Amateur/Development (tier 2)** regardless of its parent event's tier — a qualifier
bracket is the entry-level rung of that event's ladder, not the event itself.

Current implementation: `backend/routers/esports/league_tier.py` (global keyword tuples, tier
0–3 — the numeric range is unchanged by this taxonomy upgrade, only the per-league classification
and its NAMES are refined). This doc remains the source-of-truth input for the per-title
`_LEAGUE_REGISTRY` restructure — see "Next step" at the bottom.

---

## CS2

*Odds: Bovada books it. Streams: good coverage. Live data: GRID Open Access.*

| League | Tier | Why |
|---|---|---|
| Gamers Club Liga Série A | **0 Major/Pro** | Brazil's flagship domestic league — real established orgs, recurring seasons since the 2020s; not on board today |
| CCT (League / Challengers / Contenders, EU + SA) | **1 Semi-Pro/Minor** | An explicit Contenders→Challengers development LADDER with real stakes and often near-pro rosters grinding toward the top CCT bracket — organized and paid, just not the top |
| European Pro League (base rounds) | **1 Semi-Pro/Minor** | Recurring named league with real orgs and seasons; Valve ranks it C-Tier (modest prestige, still B/C not D) |
| RES Showdown | **2 Amateur/Development** | B-Tier BLAST Premier Rising QUALIFIER (HLTV-verified, `8b9631f`) — organized entry point into a real ladder, but obscure/unrecognized participants (Fluxo, Shinden) consistent with development-stage, not yet Semi-Pro |
| XSE Pro League | **2 Amateur/Development** | Rosters dominated by "ex-"/Academy/reserve-squad teams — a development circuit by roster composition |
| United21 | **2 Amateur/Development** | Confirmed C-Tier, explicitly labeled a "CS2 Minor," Division 1/2 amateur-development structure |
| TESFED League | **2 Amateur/Development** | Turkish federation's FIRST-EVER CS2 league, explicitly run as a "pilot for future competitions" — nascent domestic development |
| European Pro League — qualifier rounds (e.g. "Series 8 Closed Qualifier") | **2 Amateur/Development** | Qualifier-demotion rule — the entry rung below EPL's base rounds |
| BetBoom Streamers Battle | **3 Novelty/Exhibition** | Confirmed: online Russian CS2 SHOWMATCH, teams are famous STREAMERS (Team Aunkere/shoke/hooch/Burger), not pro players |

**Landmine:** zero Tier-0 CS2 on the board (July player break + EWC). BLAST Premier, ESL Pro
League, IEM, and CS2 Majors are all **unclassified** — they'd default to tier 2 and sort below CCT
the day they return. Pre-classify: `blast`, `esl pro league`, `iem` / `intel extreme masters`,
`major` (CS2-scoped) → **0 Major/Pro**.

## Dota 2

*Odds: partial. Streams: partial. Live data: STRATZ/OpenDota (free).*

| League | Tier | Why |
|---|---|---|
| Esports World Cup (Groups A–D) | **0 Major/Pro** | The marquee international right now (50 matches; 0 odds / 0 streams — pipeline coverage gap, not a quality signal) |
| European Pro League S39 | **2 Amateur/Development** | Liquipedia ranks it Tier-3 for Dota specifically — genuinely lower here than in CS2 (**game-relative**: same league, different real tier per game) |
| EWC Qualifiers | **2 Amateur/Development** | Qualifier-demotion rule |

Absent majors to pre-classify: The International (`the international`), ESL One, DreamLeague, PGL
events → **0 Major/Pro**.

## LoL

| League | Tier | Why |
|---|---|---|
| Mid Season Invitational | **0 Major/Pro** | Riot international flagship (8/8 odds+streams) |
| Esports World Cup | **0 Major/Pro** | International crossover |
| LRS / LRN (LATAM) | **1 Semi-Pro/Minor** | Riot-run official regional leagues feeding LTA — real orgs, paid players, legitimate ERL-equivalent tier |
| Prime League (DACH) | **1 Semi-Pro/Minor** | Official Riot-sanctioned ERL, feeds EMEA Masters |
| HLL (Greece) | **1 Semi-Pro/Minor** | Same ERL structure as Prime League, smaller market — still official/paid, not amateur |

Absent majors to pre-classify: LEC, LCK, LPL, LTA, Worlds, First Stand → **0 Major/Pro**. Same
landmine as CS2: today LCK would default to tier 2 and sort **below** Prime League.

## Valorant

| League | Tier | Why |
|---|---|---|
| Esports World Cup | **0 Major/Pro** | 14/14 odds+streams — the board's best-covered event |
| VCL (all regions; bare "Vcl" and "Valorant Challengers League Japan" are the same circuit) | **1 Semi-Pro/Minor** | Riot's official global 2nd-tier circuit, direct promotion path to VCT International |
| VCT Game Changers | **1 Semi-Pro/Minor** *(flagged, borderline)* | Officially Riot-sanctioned, real prize pools/orgs — kept alongside VCL rather than demoted to Amateur on the evidence available; revisit if participant-level data suggests otherwise |

Absent majors to pre-classify: VCT International leagues (Americas/EMEA/Pacific/CN), Masters,
Champions → **0 Major/Pro**. Bare `vct` appears in **no** keyword list today — only "challengers"
and "game changers" match, so a "VCT Americas" string would default to tier 2.

## Overwatch

| League | Tier | Why |
|---|---|---|
| OCS regional stages (Korea/EMEA/NA/China/Pacific) | **0 Major/Pro** | Blizzard's flagship — real orgs (Dallas Fuel, Team Liquid); this IS the top circuit for this game, "regional" labeling notwithstanding |
| OCS Last Chance Qualifier | **2 Amateur/Development** | Qualifier-demotion rule |

Whole title is a pipeline coverage gap: 0 odds (Bovada doesn't book OW), 0 streams (no rules in
streams.py). Protected from the visibility filter by `_title_has_any_signal`.

## Rainbow Six

| League | Tier | Why |
|---|---|---|
| NAL / SAL / CN League ("China") / MENA / APAC | **0 Major/Pro** | Ubisoft's official regional-pro structure — this is the top circuit for R6 below the international events; same league family under five inconsistent labels |

Absent majors to pre-classify: Six Invitational, R6 Majors → **0 Major/Pro**.

## King of Glory

| League | Tier | Why |
|---|---|---|
| KPL Summer | **0 Major/Pro** | Tencent's premier league for the title, 8/8 odds+streams |

## Call of Duty (title lands ~mid-July)

| League | Tier | Why |
|---|---|---|
| CDL / CoD Champs | **0 Major/Pro** | Already pre-classified in `_TIER0_KW`, ready |

---

## Structural findings

1. **Tier is game-relative but stored globally.** OCS / KPL / R6 regionals are the TOP circuit for
   their own games (tier 0) despite being "regional"; European Pro League is Semi-Pro/Minor (1) in
   CS2 but Amateur/Development (2) in Dota (Liquipedia Tier-3 there) — same literal league string,
   different real tier depending on title.
2. **Every game's actual majors except EWC/MSI/CDL are unclassified.** LCK, VCT International,
   BLAST/ESL/IEM, TI, Six Invitational all default to tier 2 the day they appear — sorting below
   keyword-matched Semi-Pro leagues like CCT and Prime League.
3. **The old 3-bucket scheme conflated Semi-Pro and Amateur.** CCT/European Pro League (real
   development ladders with organized orgs and paid rosters) and TESFED/United21/XSE (nascent
   pilot/development-squad circuits) were both "Feeder" — now split (1) vs (2), matching how
   Liquipedia's B/C-Tier vs C/D-Tier actually separates them.
4. **Showmatch is a real, separate industry category**, not a lower amateur rung — confirmed via
   the CoD Esports wiki's own dedicated Showmatch category. BetBoom Streamers Battle now has its
   own tier (3) rather than sharing a bucket with genuine (if nascent) competitive leagues.

## Next step (implementation)

Restructure `league_tier.py`'s four flat keyword tuples into a per-title registry, using the
tiers above (numeric range 0-3 unchanged, only the per-league assignments and the tier NAMES
change — `_TIER0_KW`→Major/Pro, a new split between Semi-Pro/Minor and Amateur/Development where
the old table only had one "Feeder" bucket):

```python
_LEAGUE_REGISTRY = {
    "CS2":   [("blast", 0), ("esl pro league", 0), ("iem", 0), ("major", 0),
              ("gamers club", 0), ("liga série a", 0), ("liga serie a", 0),
              ("cct", 1), ("european pro league", 1),
              ("res showdown", 2), ("xse", 2), ("united21", 2), ("united 21", 2), ("tesfed", 2),
              ("streamers battle", 3)],
    "Dota 2": [("esports world cup", 0), ("the international", 0), ("esl one", 0),
               ("dreamleague", 0), ("pgl", 0), ("european pro league", 2)],
    "LoL":    [("mid season invitational", 0), ("esports world cup", 0),
               ("lec", 0), ("lck", 0), ("lpl", 0), ("lta", 0), ("worlds", 0), ("first stand", 0),
               ("lrs", 1), ("lrn", 1), ("liga regional", 1), ("prime league", 1), ("hll", 1)],
    "Valorant": [("esports world cup", 0),
                 ("vct international", 0), ("masters", 0), ("champions", 0),
                 ("vcl", 1), ("valorant challengers league", 1), ("game changers", 1)],
    "Overwatch": [("ocs", 0), ("last chance", 2)],
    "Rainbow Six": [("six invitational", 0), ("r6 major", 0),
                    ("north america league", 0), ("north american league", 0),
                    ("south america league", 0), ("cn league", 0),
                    ("china", 0), ("mena", 0), ("apac", 0)],
    "King of Glory": [("kpl", 0)],
    # CoD not yet on board; pre-seed via the existing global _TIER0_KW ("cdl"/"cod champs")
}
```

`_league_tier(title, league)` checks the title's list first (first match wins, ordered
specific→generic), falls back to the existing global keywords for unknown titles, and keeps the
qualifier-demotion rule global (caps any "qualifier"/"last chance" match at tier 2 regardless of
which list matched). This kills the `_TIER1_R6_BARE_REGIONS` special case (becomes normal
per-title entries), fixes EPL's tier in Dota, splits Semi-Pro from Amateur per the upgraded
taxonomy, and makes the board sort correctly the day the real majors come back. Contained edit to
one file; `_sort_key` itself doesn't change.
