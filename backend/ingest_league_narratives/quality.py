"""quality helpers from the narrative pipeline."""
import re
import json
import os
import sys
import sqlite3
import datetime
import hashlib
import argparse

from .roles import is_social, post_role  # noqa: E402
from .topic_words import _norm_url, _squash_title  # noqa: E402

# Words that mark a card as making an ALLEGATION about people rather than
# reporting an event: an accusation, a punishment, a legal or disciplinary
# process. A card like that is exactly the kind that must not rest on anonymous
# social chatter.
_ALLEGATION_WORDS = (
    "harass", "racist", "racial", "abuse", "misconduct", "assault",
    "allegation", "alleged", "accus", "investigat", "probe", "lawsuit",
    "sued", "arrest", "charged", "suspend", "banned", "fired", "misconduct",
    "scandal", "circumvent", "cheat", "fraud",
)

def had_publisher_material(items):
    """True when the card was written with published reporting in front of it.

    Facts come from published reporting; social supplies the fan voice and
    nothing more (Micah, 2026-08-10). But requiring the MODEL to cite is the
    wrong lever: asking for it dropped 11 of 14 otherwise-good cards because a
    JSON field went missing, which is a worse failure than the one it prevents.
    Whether a publisher item was in the pool is something WE can verify, so we
    check that instead — and allegations, the dangerous class, still have to
    cite one (see unsupported_allegation).
    """
    return any(not is_social(it) for it in items)

def unsupported_allegation(gen):
    """True when a card makes an allegation about people and cites nobody.

    2026-08-10: an anonymous post claiming Inter Miami had suspended Messi and
    Suarez over racial-harassment allegations — never confirmed by the club,
    the league or any outlet — was written up as fact and served. The prompt
    now forbids it, but a prompt is a request. This is the refusal: if a card
    alleges something about people and no publisher item backs it, it does not
    serve, whatever the model returned.
    """
    if gen.get("source_count"):
        return False
    text = ("%s %s" % (gen.get("narrative", ""), gen.get("paragraph", ""))).lower()
    return any(w in text for w in _ALLEGATION_WORDS)

def _squash(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())

def _outlet_vocab(con, _cache={}):
    """Every outlet name this corpus knows, from our own rows.

    Built from the data rather than hand-listed, because the names that need
    catching are precisely the ones nobody thought to list: `rawchili.com` is a
    scraper that republishes other outlets through bot accounts, and it reached
    a card as "Raw Chili and other outlets". Sources give us the mastheads we
    ingest; URL hosts give us the ones we only ever see LINKED from a post,
    which is the whole problem class.
    """
    if "v" not in _cache:
        names = set()
        for (s,) in con.execute("SELECT DISTINCT source FROM news_items"):
            if s:
                names.add(_squash(s))
        for (u,) in con.execute(
                "SELECT DISTINCT url FROM news_items WHERE url != ''"):
            host = _domain_of(u)
            if host:
                # "www.pcgamesn.com" -> "pcgamesn": the name a writer would use.
                names.add(_squash(host.rsplit(".", 1)[0].split(".")[-1]))
        # Domains written INSIDE a post, which the url column never sees: a
        # bluesky row's url is its bsky permalink, so `rawchili.com` and
        # `pcgamesn.com` — the two outlets cards actually miscredited — appear
        # only in the post text. Harvesting urls alone missed both, which would
        # have made this check pass on the very cases it was written for.
        for (h,) in con.execute(
                "SELECT DISTINCT headline FROM news_items WHERE headline != ''"):
            for dom in _INLINE_DOMAIN.findall(h or ""):
                names.add(_squash(dom.rsplit(".", 1)[0].split(".")[-1]))
        # Short names collide with ordinary words ("as", "si", "the sun"), and a
        # false positive here is a warning about nothing on every future run.
        _cache["v"] = {n for n in names if len(n) >= 6} - _NOT_OUTLETS
    return _cache["v"]

_NOT_OUTLETS = {"bluesky", "xsearch", "twitter", "reddit", "google",
                "newsgoogle", "youtube", "nitter"}

# A domain written in running text, e.g. "https://www.rawchili.com/nfl/961970/"
# or a bare "zooomsports.com" — the form a post links in.
_INLINE_DOMAIN = re.compile(
    r"(?:https?://)?(?:www\.)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)

# The verbs that turn a proper noun into a claim of provenance.
_REPORTING_VERBS = {
    "reported", "report", "reports", "reporting", "said", "says", "wrote",
    "writes", "covered", "confirmed", "confirms", "noted", "notes", "quoted",
    "detailed", "published", "broke", "argued", "argues", "listed", "profiled",
    "highlighted", "described", "revealed", "added", "claimed", "announced",
}

def _domain_of(url):
    from urllib.parse import urlparse
    try:
        host = (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host

# Verbs a PARTICIPANT uses to speak for itself. "LA Galaxy confirmed on Aug 8
# that Edwin Cerrillo was transferred" is the club announcing its own business —
# the actor in the story, not a newsroom observing it — and lagalaxy.com is in
# the outlet vocabulary because we ingest the club's feed. Excluded from the
# name-drop count, kept in `uncited_outlets`, where "Raw Chili said" is exactly
# the false claim of provenance that check exists to catch.
_SELF_REPORTING_VERBS = {"confirmed", "confirms", "announced", "added",
                         "claimed", "revealed"}

_OBSERVER_VERBS = _REPORTING_VERBS - _SELF_REPORTING_VERBS

_VOICE_SUBJECTS = ("fans", "fan", "supporters", "critics", "posts", "viewers",
                   "commenters", "many", "some", "observers", "people")

def speakers_shown(shown):
    """The items in a prompt pool that are a PERSON talking — role `voice`.

    Reclassifies rather than trusting a flag, so there is one definition of a
    speaker and callers cannot drift from it. The titles come from the pool's
    own articles, exactly as `_prompt_items` builds them, so an outlet's post of
    a story sitting beside it still resolves to `relay`.
    """
    titles = {_squash_title(i.get("headline")) for i in shown if not is_social(i)}
    return [i for i in shown if post_role(i, titles) == "voice"]

def voice_without_speakers(gen, shown):
    """True when the card speaks for fans and no fan was in the pool.

    The last hole the provenance checks left open. Everything upstream governs
    where a claim may COME from; nothing asked whether the party a sentence
    attributes to actually said anything. "Fans argue X" therefore walked X
    past the publisher requirement — the check reads the speech act, sees an
    attribution, and passes, while the reader is told a constituency exists.

    A card is entitled to a fan sentence when real posts back it and not
    otherwise: with the pool's whole social lane made of repost bots, the only
    honest answer is to write nothing about fans. Silence is available and
    correct — most of these cards have a publisher anchor and need no chorus.

    Reported, not fatal, and deliberately crude: it asks only whether a speaker
    was present, not whether this particular sentence is the one they spoke.
    A card that passes can still misquote the pool; a card that fails has
    nobody to misquote.

    A SPEAKER IS `voice`, NOT `is_social`. Written against the old boolean, this
    read "was any item a post?" — and once rostered reporting moved into the
    anchors, a pool holding Schefter and no fan answered yes, so "Fans argue X"
    passed a check whose entire job was to catch it. Every population the role
    classifier separates out is one this question must not accept: a reporter is
    not a constituency, and neither is a repost bot or a brand desk.
    """
    fv = (gen.get("fan_voice") or "").strip()
    if not fv:
        return False
    words = set(re.findall(r"[a-z]+", fv.lower()))
    if not words & set(_VOICE_SUBJECTS):
        return False
    return not speakers_shown(shown)

def credited_outlets(gen, vocab):
    """Every masthead the card ATTRIBUTES something to, cited or not.

    `uncited_outlets` asks whether an attribution is HONEST. This asks whether
    it should be there at all, which is a different question and the one that
    was never posed. Measured 2026-08-12 across the 14 live cards: **45
    attributions, every card carrying at least one**, five in the UFC card
    alone — "Sherdog reported… Yahoo Sports covered… The Times of India laid
    out… Bloody Elbow reported… Fox Sports said…". Every one was accurate, so
    every existing check passed. Micah: "im having a really hard time with us
    name dropping publishers."

    The receipt chips under the card already carry provenance. Repeating it in
    the prose puts the newsroom in the subject slot that belongs to the player,
    the club or the league, and turns a story about the sport into a summary of
    who wrote about the sport.

    Attribution, not mention: shares the proper-noun-plus-reporting-verb matcher
    with `uncited_outlets`, so "FC Cincinnati host Santos Laguna" and "the LA
    Galaxy moved Edwin Cerrillo" do not count against cards that never claimed
    a source — both clubs run websites that are in the vocabulary.
    """
    return sorted(vocab & _attributed_names(gen, _OBSERVER_VERBS))

def uncited_outlets(gen, vocab):
    """Outlets the card NAMES but does not cite. A card claiming provenance it
    does not hold.

    Measured 2026-08-12, before the pool fix: `nba-expansion` and
    `nhl-salary-cap` both credited "Raw Chili" — a content farm reposting other
    people's articles through `@rawnba`/`@rawnfl` bots — and `esports-worlds`
    credited PCGamesN for a report we never read, all three while serving
    `source_count = 0`. Naming a masthead is an assertion of provenance; making
    it with no receipt is the prose form of the same defect the receipt chips
    were built to prevent.

    Reported, never used to delete a card. Chatter-only cards are a deliberate
    feature (Micah) and a wrong ATTRIBUTION is a reason to fix the sentence, not
    to drop the conversation.
    """
    named = vocab & _attributed_names(gen)
    cited = set()
    for s in gen.get("sources") or []:
        cited.add(_squash(s.get("source")))
        host = _domain_of(s.get("url", ""))
        if host:
            cited.add(_squash(host.rsplit(".", 1)[0].split(".")[-1]))
        # The receipt's own headline counts as an alias for its outlet. We
        # ingest The Athletic under `source = "the new york times"` (the NYT
        # owns it and the feed is nytimes.com), so a card correctly citing that
        # row and correctly writing "The Athletic reported" looked like a
        # miscredit. The headline ends "- The Athletic", which settles it
        # without a hand-maintained ownership map.
        cited.add(_squash(s.get("headline")))
    return sorted(n for n in named
                  if not any(n in c or c in n for c in cited if c))

def _attributed_names(gen, verbs=None):
    """The proper nouns this card CREDITS something to, squashed for lookup.

    An attribution, not a mention — a name only counts when a reporting verb
    sits beside it. Shared by `uncited_outlets` (is the credit honest?) and
    `credited_outlets` (should the credit be there at all?), so the two can
    never disagree about what the card claimed. They differ only in `verbs`:
    the honesty check takes anything that asserts provenance, the name-drop
    count takes only what an OBSERVER can say.
    """
    verbs = _REPORTING_VERBS if verbs is None else verbs
    # Match CAPITALISED runs of 1-3 words, not a squashed blob. Squashing the
    # whole prose flagged `nba-kawhi-cap` for "complex" — the ordinary English
    # word in "the already complex case" — against complex.com. A masthead in
    # running prose is capitalised; "complex" is not, and "El Paso Inc." is.
    text = " ".join(str(gen.get(f) or "") for f in
                    ("narrative", "paragraph", "fan_voice"))
    tokens = re.findall(r"[A-Za-z0-9.'&]+", text)
    lower = [t.lower().strip(".") for t in tokens]
    phrases = set()
    for i, tok in enumerate(tokens):
        if not tok[:1].isupper():
            continue
        for n in (1, 2, 3):
            if i + n > len(tokens):
                continue
            # Only an ATTRIBUTION counts. Naming a team or an event is not
            # crediting a publisher, and both run websites that land in the
            # vocabulary: "the LA Galaxy moved Edwin Cerrillo" was flagged
            # against lagalaxy.com, and "Esports World Cup 2026 adds Lenovo"
            # against esportsworldcup.com. Neither card was claiming a source.
            # Stop at the end of the sentence. "…of the Esports World Cup 2026.
            # Dust2.us listed BetBoom…" put a reporting verb three tokens after
            # an event name that belongs to the previous sentence entirely.
            after = []
            for tok_after in tokens[i + n:i + n + 3]:
                after.append(tok_after.lower().strip("."))
                if tok_after.endswith("."):
                    break
            before = lower[max(0, i - 3):i]
            attributed = (
                any(w in verbs for w in after)
                or any(w in ("report", "reports", "outlet", "outlets") for w in after)
                or any(w in ("according", "per", "via", "cited", "citing")
                       for w in before)
                # PASSIVE attribution, which the active patterns above all
                # missed: "as reported by The Athletic" puts the verb BEFORE
                # the masthead, so the card credited an outlet and the check
                # counted nothing (mls-ligamx-spending, 2026-08-12).
                or ("by" in before and any(w in verbs for w in before)))
            if attributed:
                phrases.add(_squash("".join(tokens[i:i + n])))
    return phrases

def _drafts(blob, field):
    """The alternates the model offered for one field, cleaned.

    A model that ignores the drafts instruction, or emits a string where a list
    belongs, must not break a run — it just means selection has nothing to pick
    from and the model's own final ships, which is the old behaviour.
    """
    raw = blob.get(field + "_drafts")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(d).strip() for d in raw if str(d or "").strip()]

def _cited_sources(items, parsed):
    """Resolve the model's cited source_urls to the real-article receipts.
    Only URLs that are actually in the (non-bluesky) items become chips — a
    hallucinated URL never reaches the card (Micah, 2026-08-09)."""
    real = {it["url"]: it for it in items
            if not is_social(it) and it.get("url")}
    out = []
    seen = set()

    def _add(it):
        if it and it["url"] not in seen and not is_social(it):
            seen.add(it["url"])
            # `published` is the PUBLISHER's timestamp, carried onto the receipt so
            # the card can be dated by when its story last moved rather than by
            # when this job happened to run. Sorting a feed on generation time put
            # days-old cards back on top every scheduled run (Micah, 2026-08-11).
            out.append({"headline": it["headline"], "url": it["url"],
                        "source": it["source"],
                        "published": it.get("published") or ""})

    # By ITEM NUMBER first. The model sees a numbered list, and citing "1, 4" is
    # something it gets right; reproducing a 90-character URL exactly is not,
    # and an exact-match lookup drops a near-miss silently — 9 of 12 cards
    # served no receipts while holding 3-6 real articles each (2026-08-10).
    ids = parsed.get("source_ids") or []
    if isinstance(ids, (int, str)):
        ids = [ids]
    for n in ids:
        try:
            idx = int(str(n).strip().lstrip("#")) - 1
        except ValueError:
            continue
        if 0 <= idx < len(items):
            _add(items[idx])

    # URLs still accepted, normalised so a trailing slash is not a miss — see
    # _norm_url, which must NOT drop the query string.
    by_norm = {_norm_url(u): it for u, it in real.items()}
    cited = parsed.get("source_urls") or []
    if isinstance(cited, str):
        cited = [cited]
    for url in cited:
        _add(real.get(url) or by_norm.get(_norm_url(url)))
    return out
