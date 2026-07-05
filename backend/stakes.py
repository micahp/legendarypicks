"""stakes.py — what each team is playing for in THIS game.

The context layer generate_game_story was starving without (the Brazil/Norway lesson: a
knockout match previewed by reciting group-stage point differentials, because group records
were the only facts the model had). Every line returned here is a mathematically certain,
data-derived fact — no speculation, so the story prompt's no-invention rule holds.

Fail-soft by contract: any error → [] and the story simply gets no stakes lines this pass.
"""
import espn_client as espn

# Leagues with a stakes model. generate_game_story uses this to decide whether a cached
# pre-stakes story is final (league unsupported) or provisional (regenerate once, with stakes).
SUPPORTED = {"wc", "mlb"}

_MLB_STANDINGS = "https://site.api.espn.com/apis/v2/sports/baseball/mlb/standings?level=3"


def for_matchup(league, ab_a, ab_b):
    """-> list of stakes strings for the two teams (either order). Empty when the league has
    no stakes model yet or data is unavailable."""
    league = (league or "").lower()
    try:
        if league == "wc":
            return _wc(ab_a, ab_b)
        if league == "mlb":
            return _mlb(ab_a, ab_b)
    except Exception:
        return []
    return []


def _ord(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


# ── World Cup ────────────────────────────────────────────────────────────────────────────
# 2026 format: 12 groups, top 2 advance plus best third-placed teams — so "eliminated" is
# only certain in extreme cases; we assert only what the table makes certain (clinched
# top-2) and otherwise state position/points plainly.

def _wc(ab_a, ab_b):
    groups = espn.group_standings("wc")
    if not groups:
        return []
    lines = []
    complete = all(r["played"] >= 3 for g in groups for r in g["rows"]) if groups else False
    for ab in (ab_a, ab_b):
        for g in groups:
            for r in g["rows"]:
                if r["abbrev"] != ab:
                    continue
                if complete:
                    lines.append(
                        f"{r['name']} reached the knockouts finishing {_ord(r['rank'])} in "
                        f"{g['group']} ({r['wins']}-{r['draws']}-{r['losses']}, {r['points']} pts, "
                        f"{'+' if r['gd'] >= 0 else ''}{r['gd']} GD).")
                else:
                    lines.append(_wc_group_scenario(g, r))
    if complete and lines:
        lines.append("This is a knockout match: single elimination — the loser goes home.")
    return lines


def _wc_group_scenario(g, r):
    rows = g["rows"]
    remaining = lambda x: max(0, 3 - x["played"])
    others = [x for x in rows if x["abbrev"] != r["abbrev"]]
    # Clinched top-2: at most one other team can still reach a points total above ours.
    can_finish_above = sum(1 for x in others if x["points"] + 3 * remaining(x) > r["points"])
    if can_finish_above <= 1 and remaining(r) >= 0:
        return (f"{r['name']} have clinched a top-2 finish in {g['group']} "
                f"({r['points']} pts with {remaining(r)} to play).")
    return (f"{r['name']} sit {_ord(r['rank'])} in {g['group']} with {r['points']} pts and "
            f"{remaining(r)} group game(s) left — top 2 advance (plus best thirds).")


# ── MLB ──────────────────────────────────────────────────────────────────────────────────

def _mlb(ab_a, ab_b):
    d = espn._get(_MLB_STANDINGS, ttl=900)
    want = {ab_a, ab_b}
    lines = []
    for lg in d.get("children", []):
        for div in lg.get("children", []) or []:
            entries = div.get("standings", {}).get("entries", [])
            div_name = (div.get("name") or "").replace("American League", "AL").replace(
                "National League", "NL")
            for i, e in enumerate(entries):
                ab = (e.get("team") or {}).get("abbreviation")
                if ab not in want:
                    continue
                stats = {s.get("type"): s.get("displayValue") for s in e.get("stats", [])}
                gb = stats.get("gamesbehind", "-")
                seed = stats.get("playoffseed")
                seed_txt = ""
                if seed and seed.isdigit():
                    s_n = int(seed)
                    seed_txt = (f"; current playoff seed {s_n}" if s_n <= 6
                                else "; currently outside the playoff picture")
                if gb in ("-", "0"):
                    lines.append(f"{ab} lead the {div_name}{seed_txt}.")
                else:
                    lines.append(f"{ab} are {_ord(i + 1)} in the {div_name}, {gb} games back{seed_txt}.")
    return lines
