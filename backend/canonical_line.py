"""The canonical prop line: the posted line whose two sides the sportsbook prices closest to even.

Independent of any projection. For each offer (one book, one line, both sides priced) the vig is removed by
normalising the two implied probabilities. The offer whose fair over probability is closest to 0.5 wins. A tie goes
to the lower line, then to the source name. Oracle and the Props page should both call this one function.
"""


# Pick'em apps (PrizePicks, Pick6) post this price on both sides as a placeholder, not a sportsbook price. Such a
# pair says nothing about the market, so it is never selected.
PICKEM_PLACEHOLDER = -137


def implied(american):
    """Implied probability of an American price, including the vig."""
    if american > 0:
        return 100.0 / (american + 100.0)
    return -american / (-american + 100.0)


def fair_over(over_odds, under_odds):
    """Over probability with the vig removed, or None if a price is missing or is the pick'em placeholder."""
    if over_odds is None or under_odds is None:
        return None
    if over_odds == PICKEM_PLACEHOLDER and under_odds == PICKEM_PLACEHOLDER:
        return None
    p_over, p_under = implied(over_odds), implied(under_odds)
    return p_over / (p_over + p_under)


def select(offers):
    """The canonical offer from [{line, source, over_odds, under_odds, captured_at}], or None.

    Returns the chosen offer with `p_over_fair` and `books_at_line`, the number of distinct sources posting that line.
    """
    priced = []
    for o in offers:
        p = fair_over(o["over_odds"], o["under_odds"])
        if p is not None:
            priced.append(dict(o, p_over_fair=p))
    if not priced:
        return None
    best = min(priced, key=lambda o: (abs(o["p_over_fair"] - 0.5), o["line"], o["source"]))
    books_at_line = len({o["source"] for o in priced if o["line"] == best["line"]})
    return dict(best, books_at_line=books_at_line)
