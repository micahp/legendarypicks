# Esports discovery — how we pull people into titles they don't already watch

Status: brainstorm / direction (captured 2026-07-01, Micah). Not a build spec yet — this is the
"why people click into a second esport" thesis and the coverage bar that makes it possible.

## North star
Get **all the major tournaments for all the major titles** — not just whatever Bovada happens to be
pricing that day. Comprehensive major-event coverage is the substrate; the discovery mechanics below
only work if the matches are actually on the board. (This is why the PandaScore *surface* block
matters — see `logs/ESPORTS-BUG-TRACKER.md` Class G: PandaScore knows about pro/qualifier matches
Bovada drops, and we now add them instead of losing them.)

## The three discovery mechanics (Micah's call: these + playoffs are the main ways)

### 1. Cross-title orgs — "follow a name you already know into a new title"
Big orgs field teams across many esports. A fan who knows **FaZe** from Call of Duty, or **G2** /
**Falcons** from wherever they first saw them, will click a FaZe/G2/Falcons match in a title they've
never watched *because the name is familiar*. The org is the bridge into the game.
- Examples the user cited: **Team Falcons** (very multi-title — R6, CS2, Dota 2, Valorant, LoL, CoD…),
  **G2 Esports** (LoL, CS2, Valorant, Rocket League…), **FaZe Clan** (iconic in CoD; also CS2, etc.).
- Product shapes this could take: an **org page** ("here's everyone Falcons is fielding right now,
  across every title"), an org filter/follow, "you watched FaZe in CoD → FaZe is live in CS2 in 20m".
- TODO: build a **verified org → titles/rosters map** rather than hardcoding from memory — exact
  title-per-org changes every season (e.g. don't assume an org is in CDL just because it's famous).
  PandaScore carries team/org data across titles; that's the likely source for a real mapping.

### 2. Game mode — the Search & Destroy thread
Micah is a big **Search & Destroy** fan, and the S&D *format* exists across titles under different
names. "If you love S&D, here's the same thing in three other games" is a mode-based on-ramp:
- **CoD** — Search & Destroy (plant/defuse, one life per round)
- **CS2** — Bomb defusal (the canonical plant/defuse)
- **Valorant** — Spike (plant/defuse)
- **R6 Siege** — Bomb / defuse objective
All one family: attack vs defend, plant the objective, no respawns. Surfacing/tagging by **mode**
(not just by title) lets someone follow the *style of game* they like across the whole catalog.

### 3. Playoffs — the highest-stakes entry point
Playoffs/finals are where stakes, storylines, and viewership peak — the best moment to hook a new
viewer. Bias the board toward **playoff/finals** matches as the headline "what to watch." (We already
demote minor qualifiers below real-league live matches via `minorLeague` sort — the inverse instinct;
playoffs should get the *promotion* end of that.)

## Coverage bar — major titles × major circuits (the checklist to actually hit)
Titles we currently model (`_ESPORTS_TITLES`): LoL, Valorant, CS2, Dota 2, Rainbow Six, King of Glory.
Rough "majors" to make sure land on the board (verify per season, not from memory):
- **LoL** — LCK / LEC / LPL / LTA, MSI, Worlds
- **Valorant** — VCT (Americas / EMEA / Pacific / China), Masters, Champions
- **CS2** — the Majors, BLAST, ESL Pro League / IEM, CCT
- **Dota 2** — The International, DreamLeague, ESL One, the qualifiers feeding them
- **R6 Siege** — Six Invitational, the R6 Majors, regional leagues
- **King of Glory** — KPL / world events
- **CoD (CDL)** — **DECISION (Micah, Jul 1): we WILL add CoD.** Currently excluded from the esports
  slate (it's on the main scoreboard), but it's central to this thesis (S&D, FaZe/Falcons/G2). Next
  CoD match looks to be **~July 16, 2026** — so this is **deferred to after the current work**, no
  rush to build before then. Open item to resolve during the build: confirm the data source — does
  PandaScore cover CDL, or do we need another feed (per the recon, CoD had no official free feed;
  CitoAPI ~$25/mo was the fallback — see [[project_lp_esports_niche_direction]]).

## Open questions / next steps (not committed, just parked)
- Per-title tournament-coverage audit: for each title above, is the major circuit actually landing on
  `/api/esports/upcoming`? Where's the drop-off (Bovada gap vs PandaScore gap vs our surface logic)?
- Verified **org → titles** dataset (mechanic 1) — the single highest-leverage build here.
- **Mode tagging** (mechanic 2) — where does mode metadata come from per title? PandaScore may not
  expose "this series is S&D vs Hardpoint"; might need per-title logic or a manual map.
- Playoff **promotion** in the sort/hero (mechanic 3) — the positive counterpart to `minorLeague`.
- **CoD/CDL — decided IN (Micah, Jul 1); build deferred to ~July 16** (next CoD match). Task when
  picked up: source CDL data (PandaScore? CitoAPI ~$25/mo? scrapes), then add it as a title +
  scoreboard→esports-hub inclusion. This is the anchor for mechanics 1 & 2 (S&D + FaZe/Falcons).

Related: `[[project_lp_esports_niche_direction]]`, `logs/ESPORTS-BUG-TRACKER.md` (Class G surface block).
