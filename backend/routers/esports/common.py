"""common.py — shared utilities for the esports package."""

import re
import unicodedata


def _fold(s):
    """ASCII-fold diacritics so accented spellings collapse to their base letters BEFORE the
    non-alphanumeric strip drops them entirely: 'Beşiktaş' would otherwise strip to 'beikta' (the
    ş's vanish) instead of matching 'Besiktas'. NFKD splits a letter from its combining marks; we
    drop the marks and keep the base."""
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def _split_camel(s):
    """Re-space a camelCase name ONLY when doing so separates out a GENERIC word — so a Bovada-style
    concatenation like 'TeamOrangeGaming'/'TheBoys' becomes 'Team Orange Gaming'/'The Boys' and the
    embedded generics drop, WITHOUT touching stylized single words. Splitting unconditionally would
    wreck common esports capitalizations: 'eSports'->'e Sports', 'BakS'->'Bak S', 'paiN'->'pai N'.
    So we segment on camel boundaries, and re-space only if a segment is itself a generic word;
    otherwise the original string is returned untouched."""
    segs = re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|[0-9]+", s or "")
    if any(seg.lower() in _TEAM_GENERIC for seg in segs):
        return " ".join(segs)
    return s or ""


def _amer_to_p(american):
    o = float(american)
    return (-o) / (-o + 100) if o < 0 else 100 / (o + 100)


def _norm_team(n):
    toks = [t for t in (n or "").lower().replace(".", " ").split()
            if t not in ("gaming", "esports", "e-sports", "club", "team", "gc", "the")]
    return " ".join(toks)


def _strip_name(n):
    """Normalize a team name for dedup and cross-source matching.

    ASCII-fold diacritics, lowercase, then strip ALL non-alphanumerics so spacing/punctuation/accent
    diffs collapse: 'Game Hunters' == 'GameHunters' == 'gamehunters', 'Beşiktaş' == 'Besiktas'.
    """
    return re.sub(r"[^a-z0-9]", "", _fold(n).lower())


# Generic org words that don't identify a team — dropped when building the canonical dedup/logo key
# so 'AION Esports' == 'Team AION', 'FaZe Clan' == 'FaZe', 'INFURITY Gaming' == 'Infurity'.
# 'academy' is intentionally NOT here — an org's academy squad is a DIFFERENT team from its main one.
_TEAM_GENERIC = {"gaming", "esports", "esport", "club", "team", "clan", "gc", "gg", "the", "of", "fc"}

# Acronym / short-code -> canonical full name, for cross-source pairs with NO shared substring (a
# GRID/PandaScore short code vs the full Bovada name — 'WBT' has nothing in common with 'Wrotberry').
# Keep NARROW and explicit: a wrong entry here silently merges two different teams. Values are matched
# after generic-word stripping (i.e. already lowercased, punctuation-free).
_TEAM_ALIASES = {
    "wbt": "wrotberry",
    "navi": "natusvincere",  # NAVI == Natus Vincere (so 'NAVI Junior' matches 'Natus Vincere Junior')
    # EWC 2026 Dota: the real team is "Poor Rangers" (Liquipedia-verified 2026-07-06). Bovada
    # labels them "Power Ranger", which duplicated their GamerLegion match on the schedule.
    "powerranger": "poorrangers",
    "powerrangers": "poorrangers",
    "jplay": "justplayers",  # 'JPlay' == 'Just Players' (Bovada vs PS label, verified dup 2026-07-09)
}


def _canon_tokens(n):
    """The canonical WORD-tokens of a name: ASCII-fold accents, split camelCase, lowercase, drop
    generic org words, resolve known acronym aliases. Kept separate from the joined key so a matcher
    can align on word boundaries instead of substrings of the concatenated key — 'gam' (GAM Esports)
    must not match INSIDE 'gamerlegion'. Fold+camel-split run FIRST so 'Beşiktaş'=='Besiktas' and the
    embedded generics in 'TeamOrangeGaming'/'TheBoys' are separated out and dropped."""
    # NOTE: the 'ex-' prefix is KEPT (kept as its own token), NOT stripped. 'ex-Marsborne' is the
    # DEPARTED roster and a different competitive entity from the org 'Marsborne' (which fields a new
    # lineup) — Micah 2026-07-09, Liquipedia/HLTV confirmed. Stripping it wrongly merged the two and
    # let the crest-less ex- entry mask the org's real logo.
    s = _split_camel(_fold(n)).lower().replace(".", " ")
    toks = [t for t in re.split(r"[^a-z0-9]+", s) if t and t not in _TEAM_GENERIC]
    # Expand known acronyms per-token ('NAVI Junior' -> natusvincere+junior).
    return [_TEAM_ALIASES.get(t, t) for t in toks]


def _canon_team(n):
    """Canonical identity key for DEDUP + logo lookup — stricter than `_strip_name`: lowercase, drop
    generic org words, resolve known acronyms, strip punctuation. 'AION Esports'/'Team AION' -> 'aion';
    'FaZe Clan'/'FaZe' -> 'faze'; 'WBT' -> 'wrotberry'.

    NOT for enrich matching (that's `_team_match`, kept conservative on purpose): this is the final
    merge key, where an over-collapse shows a wrong logo, not a wrong result. Falls back to the plain
    stripped name if generic-word removal would empty it (e.g. a team literally called 'Team')."""
    # whole-key acronym resolves a bare code ('WBT' -> wrotberry) that per-token expansion can't.
    key = "".join(_canon_tokens(n)) or _strip_name(n)
    return _TEAM_ALIASES.get(key, key)


# Cross-source aliases with no LEXICAL bridge — different words for the same org that each source
# spells its own way. Applied ONLY to the WHOLE canonical key (not per-token like _TEAM_ALIASES), so
# a short code like 'bb'/'nip' can't over-expand when it appears as an inner token of another name.
# Lives here (not slate) so BOTH the clustering matcher (slate `_ckey`) AND the PandaScore result
# matcher (`_ps_enrich`) bridge them — otherwise a card resolves its dup but never its result, or
# vice-versa (the 'Anyone's Legend' / 'SYF' no-result cards, 2026-07-09). Confirmed on live data:
#   NIP <-> Ninjas in Pyjamas;  AG.AL Intl / AllGamers / Anyone's Legend (one EWC Valorant squad,
#   three source spellings);  BB Team <-> BetBoom;  SYF <-> SYGaming (KoG King Pro League).
_XALIASES = {
    "nip": "ninjasinpyjamas",
    "agalinternational": "agal",
    "allgamers": "agal",
    "anyoneslegend": "agal",
    "bb": "betboom",
    "syf": "sy",
}


def _canon_team_x(n):
    """`_canon_team` plus the cross-source whole-key alias layer (`_XALIASES`). Use this for CROSS-
    SOURCE identity (Bovada<->PandaScore<->Kalshi<->GRID); plain `_canon_team` stays the base key."""
    return _XALIASES.get(_canon_team(n), _canon_team(n))


def _slug_to_name(slug):
    return " ".join(w.capitalize() for w in (slug or "").split("-"))


def _team_match(a, b):
    """True if two team names likely refer to the same team (sub/superstring after norm)."""
    na, nb = _norm_team(a), _norm_team(b)
    if na == nb:
        return True
    if na and nb:
        if na in nb or nb in na:
            return True
        wa, wb = set(na.split()), set(nb.split())
        if wa and wb:
            common = wa & wb
            if len(common) >= 2 or common == wa or common == wb:
                return True
    return False


_ESPORTS_TITLES = {
    "league-of-legends": "LoL",
    "valorant": "Valorant",
    "counter-strike-2": "CS2",
    "dota-2": "Dota 2",
    "rainbow-six": "Rainbow Six",
    "king-of-glory": "King of Glory",
    "overwatch": "Overwatch",
    # Bovada esports coupon path is `call-of-duty/<league>` (e.g. call-of-duty/cdl-championship);
    # path_parts[1] == "call-of-duty" is the title_slug that gates entry (slate_sources.py). This
    # display string is keyed EVERYWHERE downstream (picks/crowd/settlement _key) — do not rename.
    "call-of-duty": "Call of Duty",
}

# Display title -> slug (reverse of _ESPORTS_TITLES).
_TITLE_SLUG = {v: k for k, v in _ESPORTS_TITLES.items()}

# GRID title label -> our title slug (for watch-link lookup on GRID-sourced results).
_GRID_LABEL_SLUG = {"CS2": "counter-strike-2", "Dota 2": "dota-2"}
