"""Pick between drafts so cards on one page do not read alike.

Why this is code and not another prompt sentence
------------------------------------------------
`_SYSTEM` already carried, in capitals, "CRITICAL — vary the VOICE and
STRUCTURE across cards ... never reuse a shape you already used". Measured over
the 344 generations stored in `news_narratives_runs` between 2026-08-07 and
2026-08-13:

    fan_voice opening with a collective noun ....... 299/344   86.9%
    fan_voice opening 'Fans argue' ................... 55/344   16.0%
    headlines carrying an ' as ' subordinate ........ 122/344   35.5%

So the instruction to vary does not produce variety, and writing it again more
loudly is the approach that already failed.

Why this SELECTS instead of forbidding
--------------------------------------
Micah, 2026-08-13: "it should vary but shouldn't force it to not be able to use
the same structure ever again ... have guidelines and write a couple drafts and
compare to rubric and compare to each other and write final draft."

That is the right instrument. ' as ' is a perfectly good construction; it was a
rut at 36%, not a crime at 5%. A banned shape would make the writing worse in
the case where the shape is genuinely the clearest one. So nothing here refuses
a sentence for its form. The model writes alternates, and we only intervene
when two cards in the SAME run collide — because that collision is the thing
the reader actually sees, and it is invisible to a model judging one card.

The one exception is `SEEDED_PHRASES`: strings the old prompt supplied as
examples and the cards handed straight back (78/344 fan_voice lines, 22.7%,
opened with one of three literal example strings). That is not a style
judgment. An echoed example is the `the outlet is not the story` shape — a rule
phrased as a constraint on X teaches X — and it is scored down rather than
banned, so a draft can still win on the strength of everything else.
"""
import collections
import re

# Phrases the prompt used to supply verbatim, and the cards copied. Removed
# from `_SYSTEM`; `test_narrative_variety` asserts they stay out, so the prompt
# and this list cannot drift apart.
SEEDED_PHRASES = (
    "fans argue",
    "supporters point to",
    "critics say",
    "reignites the salary-cap debate",
    "but fan demand",
)

_COLLECTIVE = re.compile(
    r"^(fans|critics|supporters|players|observers|analysts|owners|executives|"
    r"some|many)\b", re.I)


def opening_bigram(text):
    """First two words, lowercased — the unit sameness actually shows up in."""
    return " ".join((text or "").split()[:2]).lower()


def seeded_hits(text):
    low = (text or "").lower()
    return [p for p in SEEDED_PHRASES if p in low]


def rubric_score(text, taken_openings=()):
    """How well one draft stands on its own, 0-100. Higher is better.

    Deliberately coarse. This breaks ties between drafts the model already
    judged good enough to offer; it is not a writing critic, and it must never
    be the only reason a sentence ships.
    """
    t = (text or "").strip()
    if not t:
        return 0
    score = 100
    # Echoing an example we supplied is the one hard signal.
    score -= 40 * len(seeded_hits(t))
    # A shape another card in this same run already used.
    if opening_bigram(t) in taken_openings:
        score -= 25
    # Named the constituency instead of what was said. Mild: sometimes right.
    if _COLLECTIVE.match(t):
        score -= 10
    # Two facts bolted together with ' as ' — fine occasionally, a rut in bulk.
    if re.search(r"\bas\b", t, re.I):
        score -= 5
    words = len(t.split())
    if words < 6 or words > 28:
        score -= 10
    return max(score, 0)


def choose(drafts, final, taken_openings=()):
    """Pick the sentence to ship from the model's final plus its alternates.

    The model's own final wins ties, because it saw the story and this function
    did not. An alternate is only promoted when it scores strictly higher —
    which in practice means the final collided with another card in the run or
    echoed a seeded phrase, and the model had already written something that
    did not.
    """
    candidates = [c for c in ([final] + list(drafts or [])) if (c or "").strip()]
    if not candidates:
        return final, False
    best, best_score = candidates[0], rubric_score(candidates[0], taken_openings)
    for c in candidates[1:]:
        s = rubric_score(c, taken_openings)
        if s > best_score:
            best, best_score = c, s
    return best, best is not candidates[0]


def resolve(cards):
    """Walk a run, promoting an alternate wherever a card collides.

    `cards` is an ordered list of dicts carrying `narrative`/`fan_voice` and
    optionally `narrative_drafts`/`fan_voice_drafts`. Mutates nothing; returns
    (resolved_cards, swap_lines).

    Order matters and is the batch order: the first card to use a shape keeps
    it, and later cards move. That makes the result stable for the reader and
    reproducible for us.
    """
    out, swaps = [], []
    taken = {"narrative": set(), "fan_voice": set()}
    for card in cards:
        card = dict(card)
        for field in ("narrative", "fan_voice"):
            original = card.get(field) or ""
            if not original.strip():
                continue
            picked, swapped = choose(card.get(field + "_drafts"), original, taken[field])
            if swapped:
                swaps.append(
                    "    VARIETY SWAP: %s %s — %r collided, used the alternate %r"
                    % (card.get("conv_id") or "?", field, original[:48], picked[:48]))
                card[field] = picked
            taken[field].add(opening_bigram(card[field]))
        out.append(card)
    return out, swaps


def survey(cards):
    """Structural census of one run. Numbers only; no verdict."""
    cards = [c for c in cards if (c.get("narrative") or c.get("fan_voice"))]
    heads = [c.get("narrative") or "" for c in cards]
    voices = [c.get("fan_voice") or "" for c in cards if (c.get("fan_voice") or "").strip()]
    head_big = collections.Counter(opening_bigram(h) for h in heads if h)
    voice_big = collections.Counter(opening_bigram(v) for v in voices)
    seeded = {}
    for c in cards:
        hits = sorted(set(seeded_hits(c.get("narrative")) + seeded_hits(c.get("fan_voice"))))
        if hits:
            seeded[c.get("conv_id") or "?"] = hits
    collective = sum(1 for v in voices if _COLLECTIVE.match(v))
    return {
        "n": len(cards),
        "n_voices": len(voices),
        "repeated_head_openings": {b: n for b, n in head_big.items() if n > 1 and b},
        "repeated_voice_openings": {b: n for b, n in voice_big.items() if n > 1 and b},
        "collective_openers": collective,
        "collective_share": collective / len(voices) if voices else 0.0,
        "as_clauses": sum(1 for h in heads if re.search(r"\bas\b", h, re.I)),
        "seeded": seeded,
    }


def report(cards):
    """Survey lines for the run log. Reports; never refuses.

    Zero has to be printable, or "varied fine" and "never measured" look the
    same in the log.
    """
    s = survey(cards)
    lines = []
    if s["n_voices"]:
        lines.append("    VARIETY: %d/%d fan sentences open with a collective noun (%.0f%%)"
                     % (s["collective_openers"], s["n_voices"], 100 * s["collective_share"]))
    lines.append("    VARIETY: %d/%d titles carry an ' as ' subordinate"
                 % (s["as_clauses"], s["n"]))
    for label, key in (("title", "repeated_head_openings"), ("fan", "repeated_voice_openings")):
        for bigram, n in sorted(s[key].items(), key=lambda kv: -kv[1]):
            lines.append("    VARIETY: %d %s sentences still open %r after selection"
                         % (n, label, bigram))
    for conv_id, hits in sorted(s["seeded"].items()):
        lines.append("    SEEDED PHRASE: %s echoes the prompt's own example(s): %s"
                     % (conv_id, ", ".join(repr(h) for h in hits)))
    return lines
