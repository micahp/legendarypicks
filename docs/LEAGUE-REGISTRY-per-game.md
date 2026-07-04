# Per-game league registry — esports live board

**Date:** 2026-07-04. Snapshot of every league/tournament string on the live board
(`/api/esports/upcoming`, 289 matches) plus known rotators (BetBoom, Gamers Club, CDL),
classified per game. Purpose: ground the tier sort in what each league IS *within its own
game*, and pre-classify each game's absent majors so they sort correctly the day they return.

Classification:
- **Official/Major** — the top circuit for that game (international marquee or the game's flagship league)
- **Minor/Feeder** — real organized competition, but second-tier / dev / qualifier for that game
- **Noise** — shouldn't be on the board (showmatches, streamer events)

Current implementation: `backend/routers/esports/league_tier.py` (global keyword tuples,
tier 0–3). This doc is the source-of-truth input for restructuring it into a per-title
registry — see "Next step" at the bottom.

---

## CS2

*Odds: Bovada books it. Streams: good coverage. Live data: GRID Open Access.*

| League | Class | Why |
|---|---|---|
| Gamers Club Liga Série A | Official (regional) | Brazil's top domestic league, real orgs; not on board today |
| RES Showdown | Feeder | B-Tier BLAST Premier Rising qualifier (HLTV-verified correction, `8b9631f`) |
| CCT (League / Challengers / Contenders, EU + SA) | Feeder | Explicit Contenders→Challengers dev ladder, Valve Tier-2 |
| European Pro League (+ Series 8 qualifiers) | Feeder | Recurring league but Valve ranks it C-Tier; qualifier rounds lower still |
| XSE Pro League | Feeder | Rosters are ex-/Academy squads — dev circuit (but 9/9 matches have odds) |
| United21 | Feeder | C-Tier, labeled a "CS2 Minor" |
| TESFED League | Feeder (borderline noise) | Turkish federation's pilot league; 1 match, no odds |
| BetBoom Streamers Battle | **Noise** | Streamer showmatch, not pro players |

**Landmine:** zero Tier-0 CS2 on the board (July player break + EWC). BLAST Premier,
ESL Pro League, IEM, and Majors are all **unclassified** — they'd default to tier 2 and
sort below CCT the day they return. Pre-classify: `blast`, `esl pro league`, `iem` /
`intel extreme masters`, `major` (CS2-scoped) → tier 0.

## Dota 2

*Odds: partial. Streams: partial. Live data: STRATZ/OpenDota (free).*

| League | Class | Why |
|---|---|---|
| Esports World Cup (Groups A–D) | **Major** | The marquee international right now (50 matches; 0 odds / 0 streams — pipeline coverage gap, not a quality signal) |
| EWC Qualifiers | Feeder | Qualifier-demotion rule, correctly |
| European Pro League S39 | Feeder | Liquipedia Tier-3 for Dota; currently held at Tier 1 by the global keyword — **misfiled for this game** |

Absent majors to pre-classify: The International (`the international`), ESL One,
DreamLeague, PGL events → tier 0.

## LoL

| League | Class | Why |
|---|---|---|
| Mid Season Invitational | **Major** | Riot international flagship (8/8 odds+streams) |
| Esports World Cup | **Major** | International crossover |
| LRS / LRN (LATAM) | Feeder | Riot-run regionals feeding LTA — official but ecosystem Tier-2 |
| Prime League (DACH) | Feeder | ERL, feeds EMEA Masters |
| HLL (Greece) | Feeder | Small ERL |

Absent majors to pre-classify: LEC, LCK, LPL, LTA, Worlds, First Stand → tier 0.
Same landmine as CS2: today LCK would default to tier 2 and sort **below** Prime League.

Note: LRS/LRN/Prime/HLL are keyword-matched tier 1 today. Within LoL's ecosystem they are
feeders (ERL / regional-league level); in the per-game registry they belong at tier 1 only
if we keep "tier 1 = real regional pro" — but they must never outrank LEC/LCK/LPL (tier 0).

## Valorant

| League | Class | Why |
|---|---|---|
| Esports World Cup | **Major** | 14/14 odds+streams — the board's best-covered event |
| VCL (all regions; bare "Vcl" and "Valorant Challengers League Japan" are the same circuit) | Feeder | Riot's official 2nd tier, direct promo path to VCT |
| VCT Game Changers | Feeder (lower) | Identity-based dev circuit |

Absent majors to pre-classify: VCT International leagues (Americas/EMEA/Pacific/CN),
Masters, Champions → tier 0. Bare `vct` appears in **no** keyword list today — only
"challengers" and "game changers" match, so a "VCT Americas" string would default to tier 2.

## Overwatch

| League | Class | Why |
|---|---|---|
| OCS regional stages (Korea/EMEA/NA/China/Pacific) | **Official — top circuit for this game** | Blizzard's flagship; real orgs (Dallas Fuel, Team Liquid) |
| OCS Last Chance Qualifier | Feeder | Qualifier bracket within OCS |

Whole title is a pipeline coverage gap: 0 odds (Bovada doesn't book OW), 0 streams (no
rules in streams.py). Protected from the visibility filter by `_title_has_any_signal`.

## Rainbow Six

| League | Class | Why |
|---|---|---|
| NAL / SAL / CN League ("China") / MENA / APAC | **Official — top circuit** | Ubisoft's regional pro structure; near-full odds+stream coverage. Same league family under five inconsistent labels |

Absent majors to pre-classify: Six Invitational, R6 Majors → tier 0.

## King of Glory

| League | Class | Why |
|---|---|---|
| KPL Summer | **Official — top circuit** | Tencent's premier league, 8/8 odds+streams |

## Call of Duty (title lands ~mid-July)

| League | Class | Why |
|---|---|---|
| CDL / CoD Champs | **Major** | Already pre-classified in `_TIER0_KW`, ready |

---

## Structural findings

1. **Tier is game-relative but stored globally.** OCS / KPL / R6 regionals are tier 1 in
   the keyword table but are the *top* of their games; European Pro League is tier 1 but is
   a *feeder* in both of its games (and Liquipedia Tier-3 in Dota).
2. **Every game's actual majors except EWC/MSI/CDL are unclassified.** LCK, VCT
   International, BLAST/ESL/IEM, TI, Six Invitational all default to tier 2 the day they
   appear — sorting below keyword-matched feeders like CCT and Prime League.

## Next step (implementation)

Restructure `league_tier.py`'s four flat keyword tuples into a per-title registry:

```python
_LEAGUE_REGISTRY = {
    "CS2":   [("blast", 0), ("esl pro league", 0), ("iem", 0), ("major", 0),
              ("gamers club", 1), ("liga série a", 1), ("liga serie a", 1),
              ("res showdown", 2), ("cct", 2), ("european pro league", 2),
              ("xse", 2), ("united21", 2), ("united 21", 2), ("tesfed", 2),
              ("streamers battle", 3)],
    "Dota 2": [("esports world cup", 0), ("the international", 0), ("esl one", 0),
               ("dreamleague", 0), ("pgl", 0), ("european pro league", 2)],
    # ... LoL, Valorant, Overwatch, Rainbow Six, King of Glory, Call of Duty per tables above
}
```

`_league_tier(title, league)` checks the title's list first (first match wins, ordered
specific→generic), falls back to the existing global keywords for unknown titles, and keeps
the qualifier-demotion rule global. This kills the `_TIER1_R6_BARE_REGIONS` special case
(becomes normal per-title entries), fixes EPL's tier in Dota, and makes the board sort
correctly the day the real majors come back. Contained edit to one file; `_sort_key` itself
doesn't change.
