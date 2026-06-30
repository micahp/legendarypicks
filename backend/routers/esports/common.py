"""common.py — shared utilities for the esports package."""


def _amer_to_p(american):
    o = float(american)
    return (-o) / (-o + 100) if o < 0 else 100 / (o + 100)


def _norm_team(n):
    toks = [t for t in (n or "").lower().replace(".", " ").split()
            if t not in ("gaming", "esports", "e-sports", "club", "team", "gc", "the")]
    return " ".join(toks)


def _strip_name(n):
    """Normalize a team name for dedup and cross-source matching.

    Lowercase + strip ALL non-alphanumerics so spacing/punctuation diffs collapse:
    'Game Hunters' == 'GameHunters' == 'gamehunters'.
    """
    import re
    return re.sub(r"[^a-z0-9]", "", (n or "").lower())


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
}

# Display title -> slug (reverse of _ESPORTS_TITLES).
_TITLE_SLUG = {v: k for k, v in _ESPORTS_TITLES.items()}

# GRID title label -> our title slug (for watch-link lookup on GRID-sourced results).
_GRID_LABEL_SLUG = {"CS2": "counter-strike-2", "Dota 2": "dota-2"}
