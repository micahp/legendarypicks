"""league_tier.py — CANDIDATE: league prestige tier + odds-or-stream visibility filter.

Additive to slate.py. Replaces the 4-keyword `_MINOR_LEAGUE_KW` binary demotion with a graded
tier (0=marquee international, 1=regional pro, 2=challengers/development, 3=minor/amateur/novelty)
grounded in what each league actually IS (researched below, not pattern-matched blind), plus a
separate odds-or-stream VISIBILITY FILTER per the user's refined ask: the board's purpose is
matches you can watch or bet on — a match with neither is out entirely once it's live/finished
(never for SCHEDULED — a market/stream often just hasn't posted yet).

Tier and filter are ORTHOGONAL: tier governs sort order among visible matches; the filter governs
whether a match is visible at all. A Tier-1 league (e.g. Gamers Club Liga Série A) can still have
an individual finished match nobody streamed or booked — that specific match is filtered, the
league's other matches are not.

---------------------------------------------------------------------------------------------
TIER TABLE — real league strings currently on :8095, classified from research (Liquipedia /
Esports Charts / GosuGamers / official org sites), not guessed:

TIER 0 — flagship international (crosses regions, the actual marquee event):
  - Esports World Cup (group stage / main event — NOT its qualifiers, see demotion rule below)
  - Mid Season Invitational (LoL) — Riot's international flagship
  - Call of Duty League / CDL / CoD Champs — not in the current feed (title lands ~mid-Jul per
    project notes); pre-classified so it's covered the moment PandaScore/Bovada add the title.

TIER 1 — real regional pro leagues (legitimate top-flight or clear 2nd-flight; still "real
competition" even though regional, per the user's framing):
  - VCL / "Vcl" / "Valorant Challengers League <region>" (Brazil/NA/LatAm-N/LatAm-S/SEA/EMEA/
    Japan) — UNIFIED as one tier despite different literal strings on the board. Researched:
    VCL is Riot's official global 2nd-tier Valorant circuit (B-Tier on Liquipedia in every
    region including Japan) with a *direct* promotion path to VCT International Stage-2
    playoffs as of the 2026 format (Ascension was removed) — Japan's "Valorant Challengers
    League Japan" is not a lesser competition than "VCL — Brazil", it is the SAME tier under a
    fuller name. Treating them differently because Bovada and PandaScore happen to spell the
    league string differently would be exactly the "pattern-match blindly" trap flagged in the
    ask — deviated from the coordinator's example grouping here, flagged explicitly.
  - LRS / LRN (Liga Regional Sur / Norte, LoL LATAM) — A-Tier, Riot-run regional top flight.
  - Prime League (DACH LoL ERL) — feeds EMEA Masters (LoL's Tier-2 international), legitimate
    top-flight regional league with roster/residency requirements.
  - European Pro League (CS2 + Dota 2) — kept Tier 1 per the coordinator's steer: it's a
    persistent named league with seasons (not a one-off bracket), BUT flagged honestly: Valve
    ranks its CS2 side C-Tier and Liquipedia ranks its Dota 2 side Tier-3 — external tier
    systems place it lower than "top-flight". Sits at the Tier-1/2 boundary; kept at 1 because
    it's organized recurring league play, not a qualifier/bracket, and demoted like everything
    else when its OWN qualifier rounds run ("Series 8 Closed Qualifier" -> forced to Tier 2, see
    the qualifier-demotion rule).
  - OCS (Overwatch Champions Series) regional stages (Group Stage/Playoffs/Seeding Decider) —
    Blizzard's official top competitive circuit, real pro orgs (Dallas Fuel, Team Liquid, Weibo
    Gaming...). "Last Chance Qualifier" sub-stage demoted to Tier 2 (see rule).
  - Rainbow Six regional leagues: North America League, South America League, CN League,
    "China", Mena, Apac Asia — all FIVE are the same Ubisoft-official regional-pro-league
    structure (A-Tier), just labeled inconsistently across sources ("China"/"CN League" are the
    same league). Unified as one tier rather than treated as 5 different leagues by string.
  - Gamers Club Liga Série A — Brazil's flagship recurring domestic CS2 league (real orgs,
    monthly seasons since 2020s); C-Tier globally, but that's normal for a domestic league —
    it's still top-of-region.
  - HLL (Hellenic Legends League) — Greece's official LoL ERL, feeds EMEA Masters.
  - Kpl Summer (King of Glory) — KPL is Tencent's premier top-flight league for the title
    (analogous to LPL for LoL) — arguably tier-0-equivalent WITHIN King of Glory, but since it's
    a single-region league (not an international crossover event like EWC/MSI), kept at Tier 1
    for cross-title comparability.

TIER 2 — Challengers / 2nd-tier / qualifier / development leagues (organized competition,
genuinely lower stakes than the leagues above):
  - CCT (all series: "Cct League", "Cct Europe Challengers", "CCT 2026 Challengers Europe
    Series N", "CCT ... Contenders Europe Series N", "CCT ... South America Series N") —
    confirmed C-Tier / Valve-Tier-2, EXPLICITLY built as a Contenders->Challengers development
    ladder feeding into the top CCT bracket (Liquipedia: "16 teams from open qualifiers... top 2
    advance to Challengers").
  - Xse / XSE Pro League — rosters are dominated by "ex-"/Academy/reserve-squad teams
    (ex-MANA, ex-Sashi Academy) consistent with a development circuit; no independent tier
    citation found, classified by structure/roster evidence.
  - TESFED League — confirmed: Turkish esports federation's FIRST-EVER CS2 league, explicitly
    run as a "pilot for future competitions" — nascent domestic development league.
  - United21 / "United 21" — confirmed C-Tier, explicit Division 1/2 amateur-development
    structure, labeled a "CS2 Minor" on Esports Charts.
  - OCS "Last Chance Qualifier" sub-stage — literally a qualifier bracket within OCS.
  - VCT Game Changers (Japan or any region) — separate identity-based circuit, lower general
    coverage/stakes than the main VCL/VCT ladder; classified dev-tier per the coordinator's
    offered judgment call.
  - RES Showdown (all seasons) — CORRECTED post-verification (2026-07-04, user found the actual
    HLTV event page): confirmed via Liquipedia (RLG/RES/Showdown) + HLTV
    (events/8594/res-showdown-2-blast-premier-rising-event) as a real RLG-organized B-Tier /
    Valve Tier-1 QUALIFIER for BLAST Premier Rising — structurally the same class as CCT's
    qualifier ladder, not a novelty event. Originally misfiled Tier 3 by the generic "showdown"
    keyword below (a name-pattern-match, exactly the blind-classification trap this system was
    built to avoid) — moved here to Tier 2 and the keyword removed.
  - Anything ending up here via the qualifier-demotion rule (see below).

TIER 3 — minor / amateur / novelty (not real competitive stakes):
  - BetBoom Streamers Battle — CONFIRMED via research: an online Russian CS2 SHOWMATCH
    organized by Gabe Media/ESforce, teams composed of FAMOUS STREAMERS, not pro players
    (team names are streamer handles: "Team Aunkere", "Team shoke", "Team hooch", "Team
    Burger"). Exactly the novelty/entertainment event the user suspected.
  - Legacy keyword catches kept as a floor: "amateur", "nation cup", "nations cup" (unchanged
    from the old _MINOR_LEAGUE_KW; nothing on the current board hits these, kept for safety).

QUALIFIER-DEMOTION RULE: a league string containing "qualifier" is capped at Tier 2 regardless of
its base league's tier — a qualifier is inherently lower-stakes than the event it's qualifying
INTO. This is what correctly separates "Esports World Cup — 2026 (Group A)" (Tier 0, real EWC
group-stage match) from "Esports World Cup Qualifiers" (Tier 2, a bracket trying to reach EWC),
and "European Pro League — Series 8 Closed Qualifier" (Tier 2) from ordinary EPL rounds (Tier 1).

NOT integrated (flagged as future enhancement, out of scope for this pass): PandaScore's own
per-match `tier` field (pandascore.py:_ps_match_tier, 's'/'a'/'b'/'c'/'') could corroborate Tier 0
detection for titles/leagues not in the string table below. Skipped here because the ask said to
ground the classifier in the REAL league-name strings first, and the string table above already
covers 100% of what's live on the board — wiring in PS tier would need passing the raw PS match
dict through to output-shaping (currently discarded after enrich), a bigger change than this
additive pass calls for.
"""

import re

_TIER0_KW = ("esports world cup", "mid season invitational",
             "call of duty league", " cdl ", "cod champs")

_TIER1_KW = ("vcl", "valorant challengers league", "lrs", "lrn", "liga regional",
             "prime league", "european pro league", "ocs", "north america league",
             "north american league", "south america league", "cn league",
             "gamers club", "liga série a", "liga serie a", "hll", "kpl")

# Rainbow Six's regional-league labels don't share a common substring with the _TIER1_KW list
# above ("China", "Mena", "Apac Asia" carry no league-family word) — they're the SAME Ubisoft
# regional-pro-league structure as "North America League"/"South America League"/"CN League",
# just labeled by bare region name. Scoped to title=="Rainbow Six" so a bare "china"/"mena"
# substring can't misfire on some other title's league string.
_TIER1_R6_BARE_REGIONS = ("china", "mena", "apac asia", "apac")

_TIER2_KW = ("cct", "challengers", "contenders", "xse", "tesfed", "united21", "united 21",
             "game changers", "development", "qualifier", "last chance",
             # RES Showdown: confirmed via Liquipedia + HLTV a real RLG-organized B-Tier / Valve
             # Tier-1 QUALIFIER for BLAST Premier Rising (liquipedia.net/counterstrike/RLG/RES/
             # Showdown/2025/Fall; hltv.org/events/8594/res-showdown-2-blast-premier-rising-event)
             # — same class as CCT's qualifier ladder, NOT a novelty event. It was previously
             # misclassified Tier 3 by the generic "showdown" keyword below, which is exactly the
             # blind-pattern-match trap this whole system was built to avoid.
             "res showdown")

_TIER3_KW = ("streamers battle", "streamer", "showmatch", "celebrity",
             "amateur", "nation cup", "nations cup")


def _league_tier(title, league):
    """League prestige tier: 0 (marquee international) .. 3 (minor/amateur/novelty).
    Lower sorts first. Unknown/uncovered leagues default to 2 (neutral: not asserted marquee,
    not asserted minor) rather than guessing in either direction."""
    L = (league or "").lower()
    T = (title or "").lower()

    if any(kw in L for kw in _TIER3_KW):
        return 3

    # Qualifier-demotion: capped at 2 regardless of base league, checked before tier0/1 matching
    # so "Esports World Cup Qualifiers" and "... Closed Qualifier" don't ride their parent
    # league's higher tier.
    is_qualifier = any(kw in L for kw in ("qualifier", "last chance"))

    if any(kw in L for kw in _TIER0_KW):
        return 2 if is_qualifier else 0

    if any(kw in L for kw in _TIER1_KW) or (T == "rainbow six" and any(kw in L for kw in _TIER1_R6_BARE_REGIONS)):
        return 2 if is_qualifier else 1

    if any(kw in L for kw in _TIER2_KW):
        return 2

    return 2  # unknown league: neutral default, neither promoted nor buried


# Stage/round within an event — the "importance" gradient WITHIN a tier that tier alone can't see
# (an EWC Grand Final and an EWC group-stage match are both tier 0). Parsed from the league string,
# which is where the board carries the stage: "… (Group D)", "… (Playoffs)", "Last Chance
# Qualifier", "… (Group Stage)". Lower rank sorts first (more prominent). This is our stand-in for
# real match volume, which no upstream (Bovada omits it, Kalshi delists esports intraday) gives us.
_STAGE_QUAL_KW = ("qualifier", "last chance", "lcq", "play-in", "play in", "open qualifier", "wildcard")
_STAGE_PLAYOFF_KW = ("playoff", "knockout", "elimination", "bracket", "semifinal", "semi-final",
                     "quarterfinal", "quarter-final", "top 8", "top 4", "top8", "top4")
_STAGE_GROUP_KW = ("group", "regular season", "swiss", "round robin", "round-robin", "stage",
                   "season", "split", "league")


def _stage_rank(league):
    """Round-importance within an event, 0 (final) .. 3 (qualifier). Qualifier is checked FIRST so a
    'Last Chance Qualifier (Playoffs)' buckets as a qualifier (lowest stakes) rather than riding its
    internal 'playoffs' word. An unknown/stageless league ('Esports World Cup 26') defaults to 2
    (same as group) so it is neither promoted nor penalized on stage."""
    L = (league or "").lower()
    if any(k in L for k in _STAGE_QUAL_KW):
        return 3
    # Grand/event final — but not semi-/quarter-final (those are playoff rounds, rank 1).
    if "grand final" in L or ("final" in L and not any(k in L for k in
                              ("semifinal", "semi-final", "quarterfinal", "quarter-final"))):
        return 0
    if any(k in L for k in _STAGE_PLAYOFF_KW):
        return 1
    if any(k in L for k in _STAGE_GROUP_KW):
        return 2
    return 2


def _has_real_odds(m):
    """True favorite requires two-sided real Bovada prices (see slate.py's fav computation) —
    a GRID/PS-surfaced match with no Bovada listing never gets a `favorite`, correctly."""
    return bool(m.get("favorite"))


def _has_stream(m):
    """The final resolved watch link (frag/PS/hardcoded-rule) — the actual output of the whole
    streams.py pipeline, whatever platform it landed on."""
    return bool(m.get("watch"))


def _title_has_any_signal(matches):
    """{title: True/False} — does ANY match of this title currently carry odds or a stream.
    Guards the visibility filter against a whole-TITLE pipeline coverage gap (e.g. Bovada books
    no Overwatch markets and streams.py has zero Overwatch stream rules — ALL 22 live Overwatch
    matches on the real board have neither signal, including legitimate pro-org matches like
    Dallas Fuel v Team Liquid). Without this guard the filter would silently delete an entire
    title; that's a coverage gap in OUR pipeline, not evidence those matches are insignificant."""
    out = {}
    for m in matches:
        t = m.get("title")
        out[t] = out.get(t, False) or _has_real_odds(m) or _has_stream(m)
    return out


def _passes_visibility_filter(m, title_signal):
    """The user's core-purpose filter: a match you can neither watch nor bet on has no reason to
    be on the board — but ONLY once it's live/finished/ended_unknown. A SCHEDULED match is never
    filtered on this basis (a market/stream often simply hasn't posted yet; Bovada odds alone, or
    just being scheduled, means it's real and worth keeping)."""
    if m.get("state") == "scheduled" or m.get("state") is None:
        return True
    if not title_signal.get(m.get("title"), True):
        return True  # whole-title coverage gap this cycle — not a per-match quality signal
    return _has_real_odds(m) or _has_stream(m)


def _prominence(tier, stage):
    """Single descending importance score (higher = more prominent) the frontend can sort by as one
    source of truth, replacing its old two-boolean (minorLeague, online) rule that collapsed tiers.
    tier is the coarse floor (a tier-0 group match still outranks a tier-1 final); stage breaks ties
    WITHIN a tier. tier-0 grand final = 330, tier-3 qualifier = 0."""
    return (3 - tier) * 100 + (3 - stage) * 10


def _sort_key(m):
    """Sort key: (not live, tier, stage, live_no_stream, startTime).
    tier is the coarse event-prestige floor; stage is round-importance WITHIN a tier (a Grand Final
    leads its tier's group-stage matches). live_no_stream demotes a live match that STILL has no
    stream within its bucket — not necessarily minor (a stream can post seconds later), just not
    featurable THIS instant; a marquee live match with a stream still leads its tier."""
    live = bool(m.get("live"))
    tier = _league_tier(m.get("title"), m.get("league"))
    stage = _stage_rank(m.get("league"))
    live_no_stream = bool(live and not m.get("watch"))
    return (not live, tier, stage, live_no_stream, m.get("startTime") or 0)


def apply_tier_and_filter(matches):
    """Full replacement for slate.py's minorLeague-demotion + sort (lines ~845-849). Returns
    (visible_matches_sorted, dropped_matches) — dropped kept separately for verification/logging,
    never shipped in the API response."""
    title_signal = _title_has_any_signal(matches)
    visible, dropped = [], []
    for m in matches:
        m = dict(m)
        m["tier"] = _league_tier(m.get("title"), m.get("league"))
        m["stageRank"] = _stage_rank(m.get("league"))
        # `prominence` is the single importance score the frontend sorts by (tier + stage). Higher
        # = more prominent. Emitted so the client has ONE ordering signal instead of re-deriving a
        # coarser one that collapsed tier-0 and tier-1 together.
        m["prominence"] = _prominence(m["tier"], m["stageRank"])
        # Backward-compat field: old consumers reading `minorLeague` still see a sane boolean
        # (tier >= 2 — Challengers-or-below), even though `tier`/`prominence` are the real signals now.
        m["minorLeague"] = m["tier"] >= 2
        if _passes_visibility_filter(m, title_signal):
            visible.append(m)
        else:
            dropped.append(m)
    visible.sort(key=_sort_key)
    return visible, dropped
