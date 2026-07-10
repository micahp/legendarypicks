"""Team identity, display normalization, and crest alignment for esports matches.

This module owns the cross-source answer to "are these the same team?" and the narrowly verified
metadata repairs that depend on that identity policy.  It intentionally does not own clustering,
source I/O, or match state transitions.
"""

import re

from .common import _canon_team_x, _canon_tokens
from .pandascore import _ps_enrich


# Affix-match residual policy (ALLOWLIST, not blocklist).  Unknown suffixes fail closed so distinct
# squads such as G2/G2 HEL and MIBR/MIBR LOS never collapse merely because one name is an affix.
_MERGE_OK_SUFFIX = frozenset({"stars", "galaxy", "kia", "globant", "w7m"})
_VOWELS = frozenset("aeiou")
_MAP_SUFFIX_RE = re.compile(r"\s*[-–—]?\s*l?map\s*\d+\s*$", re.IGNORECASE)


def _residual_droppable(residual):
    """Return whether every residual token is an approved generic or sponsor suffix."""
    for token in residual:
        if token not in _MERGE_OK_SUFFIX:
            return False
    return True


def _ckey(name):
    return _canon_team_x(name or "")


def _consonant_skeleton(key):
    """Return a vowel-elided canonical key used for mechanical abbreviations such as LVLUP."""
    return "".join(character for character in key if character not in _VOWELS)


def _is_subsequence(shorter, longer):
    """Return whether every character of ``shorter`` occurs in ``longer`` in order."""
    characters = iter(longer)
    return all(character in characters for character in shorter)


def _same_team(left, right):
    """Return whether two labels identify the same team under the shared cross-source policy.

    Accepted evidence is canonical equality, a guarded anagram typo, an approved word-token affix,
    a tiny plural/truncation tail, or a vowel-elided abbreviation.  Unknown affixes fail closed.
    """
    left_key, right_key = _ckey(left), _ckey(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    if len(left_key) >= 4 and len(right_key) >= 4 and sorted(left_key) == sorted(right_key):
        return True

    left_tokens, right_tokens = _canon_tokens(left), _canon_tokens(right)
    shorter_tokens, longer_tokens = ((left_tokens, right_tokens)
                                     if len(left_tokens) <= len(right_tokens)
                                     else (right_tokens, left_tokens))
    if shorter_tokens and len(shorter_tokens) < len(longer_tokens):
        residual = (longer_tokens[len(shorter_tokens):]
                    if longer_tokens[:len(shorter_tokens)] == shorter_tokens else
                    longer_tokens[:len(longer_tokens) - len(shorter_tokens)]
                    if longer_tokens[len(longer_tokens) - len(shorter_tokens):] == shorter_tokens
                    else None)
        if residual is not None and _residual_droppable(residual):
            return True

    shorter_key, longer_key = ((left_key, right_key)
                               if len(left_key) <= len(right_key)
                               else (right_key, left_key))
    if (len(shorter_key) >= 6 and longer_key.startswith(shorter_key)
            and len(longer_key) - len(shorter_key) <= 2):
        return True

    left_skeleton = _consonant_skeleton(left_key)
    right_skeleton = _consonant_skeleton(right_key)
    if (len(left_skeleton) >= 4 and left_skeleton == right_skeleton
            and left_key != right_key and _is_subsequence(shorter_key, longer_key)):
        return True
    return False


def _same_pair(a1, b1, a2, b2):
    return ((_same_team(a1, a2) and _same_team(b1, b2))
            or (_same_team(a1, b2) and _same_team(b1, a2)))


def _strip_map_suffix(name):
    """Remove a trailing Bovada map-market marker from a display label."""
    return _MAP_SUFFIX_RE.sub("", name or "").strip()


def _is_map_market(match):
    """Return whether both sides identify a Bovada map market rather than a series match."""
    team_a, team_b = match.get("teamA") or "", match.get("teamB") or ""
    return bool(_MAP_SUFFIX_RE.search(team_a) and _MAP_SUFFIX_RE.search(team_b))


_RES_ARCHIVE_LEAGUE_FIXES = {
    frozenset({_ckey("Arch"), _ckey("Virtus.pro")}):
        "RES Showdown Europe Fall 2026 — East European Open Qualifier",
    frozenset({_ckey("Metanoia Wolves"), _ckey("Bounty Hunters")}):
        "RES Showdown South America Fall 2026 — Open Qualifier #2",
}


def _normalize_match_metadata(match):
    """Apply verified archive-label repairs and remove map-marker display contamination."""
    if (match.get("league") or "").strip().lower() == "res showdown fall 2025":
        pair = frozenset({_ckey(match.get("teamA")), _ckey(match.get("teamB"))})
        if pair in _RES_ARCHIVE_LEAGUE_FIXES:
            match["league"] = _RES_ARCHIVE_LEAGUE_FIXES[pair]
    match["teamA"] = _strip_map_suffix(match.get("teamA"))
    match["teamB"] = _strip_map_suffix(match.get("teamB"))
    if match.get("favorite") and match["favorite"].get("name"):
        match["favorite"] = dict(match["favorite"])
        match["favorite"]["name"] = _strip_map_suffix(match["favorite"]["name"])
    return match


def _repair_logos_by_psid(match):
    """Re-align stored crests to the authoritative PandaScore team orientation.

    Stable PandaScore ids are preferred.  Legacy rows without an id fall back to name-based enrich
    so a previously reversed crest can be corrected rather than frozen into the results store.
    """
    team_a, team_b = match.get("teamA", ""), match.get("teamB", "")
    if not (team_a and team_b):
        return match
    ps_id = match.get("psId") or match.get("_ps_id")
    enriched = None
    if ps_id:
        enriched = _ps_enrich(team_a, team_b, include_running=True,
                              near_ms=match.get("startTime"), league=match.get("league"),
                              ps_id=ps_id)
    if not enriched:
        enriched = _ps_enrich(team_a, team_b, include_running=True,
                              near_ms=match.get("startTime"), league=match.get("league"))
    if not enriched:
        return match

    logo_a, logo_b = enriched.get("logoA"), enriched.get("logoB")
    canonical_a, canonical_b = enriched.get("canonicalA"), enriched.get("canonicalB")
    if not (logo_a and logo_b and canonical_a and canonical_b):
        return match
    new_a = (logo_a if _same_team(team_a, canonical_a) else
             logo_b if _same_team(team_a, canonical_b) else match.get("logoA"))
    new_b = (logo_b if _same_team(team_b, canonical_b) else
             logo_a if _same_team(team_b, canonical_a) else match.get("logoB"))
    if new_a != match.get("logoA") or new_b != match.get("logoB"):
        match["logoA"], match["logoB"] = new_a, new_b
    return match
