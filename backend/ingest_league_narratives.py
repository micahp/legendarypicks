#!/usr/bin/env python3
"""ingest_league_narratives.py — AI-generated league conversations.

Turns each CONVERSATION's collected chatter (news_items tagged with conv_id,
from Bluesky search posts + real headlines) into a two-layer card:
  - `narrative` — the NEWS ANCHOR: the official, high-importance story
    (a commissioner's decision, a signing, a rule change, a lawsuit).
  - `fan_voice` — what fans are SAYING and WANTING around it, WITH the
    evidence backing them (the packed stadium, the player quote, the
    lower-division energy). Fans have a voice: just because the league
    decided something does not mean fans agree or have stopped wanting the
    alternative, and the site shows why they're right (Micah, 2026-08-07).

Each conversation is its own row and gets to breathe — we do NOT merge all of
a league's conversations into one summary card. (The league summary is a
future pass over the conversation set, not this script's job.)

Output goes to news_narratives (one row per conv_id), served by routers/news.py.

Run AFTER ingest_league_news.py. No ESPN hosts involved; the only network is
the DeepSeek chat API (key via _core._deepseek_key, 1 call per conversation).

Usage:
  LP_DB_PATH=/path/to/db python3 ingest_league_narratives.py [--convs mls-pro-rel] [--dry-run]
"""
import argparse
import datetime
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _core import SOCIAL_SOURCES, _deepseek_chat, _init_db  # noqa: E402
from ingest_league_news import CONVERSATIONS  # noqa: E402
from news_classifier import entities  # noqa: E402

def _norm_url(u):
    """Fold the drift, keep the identity.

    This used to be `(u or "").strip().rstrip("/").split("?")[0].lower()` — which
    threw away the query string. ESPN's recap, preview and clip URLs differ ONLY
    there (`/mlb/recap?gameId=401816477`), so on the dev DB **65 news_items
    collapsed onto 3 keys**: 35 previews, 21 recaps, 9 clips. `by_norm` keeps
    whichever landed last, so a near-miss citation could attach a different
    game's recap to a card as its receipt — a citation the reader will trust.

    Safe to fold: trailing slash, host and scheme case, `utm_*` tracking
    parameters, parameter order. Not safe: the rest of the query, or path case.
    See test_news_receipt_url_identity.
    """
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    text = (u or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except ValueError:
        return text.rstrip("/")
    query = urlencode(sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_")))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                       parts.path.rstrip("/"), query, ""))


def _norm_words(text):
    """Lowercase word set, punctuation stripped."""
    return set(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())


_MAX_SOURCES = 12
_MIN_ITEMS = 2  # fewer than this and there's no "chatter" to summarize
_BATCH_MAX_TOKENS = 24000  # reasoning shares this budget; 10000 truncated 13 cards
_BATCH_CHUNK = 4           # fallback width when the wide batch will not parse
_ANCHORS = 6               # real articles shown per card, best-scoring first
# Words that are in every seed and every headline, so a hit on them means
# nothing. Same lesson as the classifier's substring bug.
_GENERIC_WORDS = {"deal", "deals", "talks", "rights", "season", "league",
                  "team", "teams", "game", "games", "news", "player",
                  "players", "sports", "picture", "debate", "case", "about",
                  "after", "before", "their", "there", "these", "those"}

# A declined/failed conversation wipes its served news_narratives row — that's
# the "some are missing now" mechanism. The full served card that vanished is
# appended here so the editor can review what was lost during the run (Micah
# 2026-08-09: "during the run it should document the full of what cards were
# deleted just log it to a file and we can read that file when we run the
# review"). Run history keeps the OLD version, but not that it was SERVED then
# dropped — this log is that record.
_DELETIONS_LOG = os.environ.get("LP_NEWS_DELETIONS_LOG") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "news-deletions.log")


def _log_deletion(con, conv, reason):
    """Append the full served card being deleted to the deletions log. Reads
    the row BEFORE the delete (same connection, pre-commit, sees the served
    state). No-op if nothing was served for the conv."""
    row = con.execute(
        """SELECT narrative, fan_voice, paragraph, sources, source_count,
                  generated_at FROM news_narratives WHERE conv_id=?""",
        (conv["id"],)).fetchone()
    if not row:
        return  # nothing served to delete
    os.makedirs(os.path.dirname(_DELETIONS_LOG), exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    block = (
        "\n[{ts}] DELETED conv={cid} league={lg} reason={reason}\n"
        "  served-since: {since}\n"
        "  narrative: {narr}\n"
        "  fan_voice: {fv}\n"
        "  paragraph: {para}\n"
        "  sources: {src}\n"
        "  source_count: {sc}\n".format(
            ts=ts, cid=conv["id"], lg=conv["league"], reason=reason,
            since=row["generated_at"], narr=row["narrative"],
            fv=row["fan_voice"], para=row["paragraph"],
            src=row["sources"], sc=row["source_count"]))
    with open(_DELETIONS_LOG, "a", encoding="utf-8") as f:
        f.write(block)

_SYSTEM = (
    "You are the narrative desk for a sports news app. You are given the "
    "chatter around ONE important conversation in a league — real headlines "
    "and what people are posting. Write the card for it as a short paragraph. "
    "NEVER STATE AN UNVERIFIED CLAIM AS FACT. Items marked UNVERIFIED SOCIAL "
    "POST show what is being SAID; the publisher items are what is KNOWN. A "
    "claim about a person — accusation, suspension, investigation, firing, "
    "injury, signing — is stated plainly only if a publisher item carries it, "
    "and where a publisher and a social post disagree the publisher is right. "
    "Otherwise say it is unconfirmed or leave it out and write from what IS "
    "supported; that is the normal case, not a failure, and never a reason to "
    "decline the conversation. "
    "ONE TOPIC PER CARD. This card covers exactly the conversation named in the "
    "header and nothing else. A card is NOT a roundup of everything happening "
    "in the league — that is a different feature. If an item in the list is "
    "about a different story, LEAVE IT OUT, even when it is dramatic and even "
    "when it is the freshest thing there: a star's bereavement does not belong "
    "in a card about scouting economics, it is its own conversation. A shorter "
    "card that stays on one subject beats a longer one that wanders. "
    "THE STORY IS ALWAYS ABOUT PEOPLE (Micah, 2026-08-10). Every power move, "
    "rule change, expansion vote, media-rights deal and transfer fee lands on "
    "someone: the player whose career it redirects, the smaller club whose "
    "season it funds, the fans who pay for the ticket or lose the team. A card "
    "that stops at the mechanism — the number, the vote, the clause — has not "
    "finished the job. Name who it happens TO and what changes for them, and "
    "make the fan experience the point rather than an afterthought. Do this in "
    "the same plain language as everything else; it is a matter of WHAT you "
    "choose to say, not of adding emotional adjectives. "
    "The paragraph must do two things: "
    "1) LEAD with the NEWS ANCHOR: the official, high-importance story "
    "(a commissioner's decision, a signing, a rule change, a lawsuit). State "
    "it plainly — this is what actually happened. "
    "2) Then carry the FAN VOICE with attribution. Fans have a voice: just "
    "because the league/commissioner decided something does not mean fans "
    "agree or have stopped wanting the alternative. Attribute their side "
    "explicitly — \"Fans argue…\", \"Supporters point to…\", \"Critics say…\" — "
    "and name the evidence (the packed stadium, the lower-division crowds, "
    "the player quote, a poll number) so the reader sees WHY they have a "
    "point. It must never sound like the app itself is making the fan's claim. "
    "`narrative` is the card's TITLE — one sentence that names the CONVERSATION "
    "anchored on the official story. Lead with the news event but frame it as "
    "the story people are talking about — the reader should see what the fight "
    "is, not just what happened. "
    "Write it in plain, literal news language (Strunk & White: omit needless "
    "words, prefer the standard to the offbeat). State who did what — subject, "
    "plain verb, object. NO idioms, NO puns, NO metaphors: never \\\"cranks the "
    "pressure cooker\\\", \\\"holds the line\\\", \\\"holds off\\\", \\\"locks in\\\", \\\"reality bites\\\", "
    "\\\"slams the door\\\", \\\"roars on\\\". \\\"Browns pick artificial turf for new "
    "stadium\\\" is right; \\\"Browns lock in turf\\\" is not. "
    "Spell out jargon — never abbreviate: write \\\"promotion and relegation\\\", "
    "not \\\"pro/rel\\\"; a reader skimming a title must not have to decode a "
    "shortened term. "
    "CRITICAL — vary the VOICE and STRUCTURE across cards. Do NOT copy the same "
    "template for every league. These are all acceptable shapes; pick the one "
    "that fits THIS conversation, and never reuse a shape you already used: "
    "- \\\"Skubal trade to Dodgers reignites the salary-cap debate\\\" (event → "
    "debate) "
    "- \\\"NHL free agency leaves proven players unsigned as cap money dries up\\\" "
    "(statement about the situation) "
    "- \\\"MLS commissioner rules out promotion and relegation, but fan demand "
    "for it grows\\\" "
    "(decision → but → fan pushback) "
    "- \\\"Worlds ticket resale prices hit $169,000 amid scalping complaints\\\" "
    "(controversy → concrete number) "
    "Vary the CADENCE too, not just the verb: some titles can use a colon, "
    "some a question, some a short clause — but all plain and literal, no "
    "figurative verbs. If two titles in the same "
    "run would open with the same kind of subject (a team, a league body, a "
    "commissioner), rephrase one so the openings differ. "
    "The title must never be a bare wire headline (\"Tigers traded Skubal to "
    "the Dodgers\"). It must name the conversation. But the phrasing, verb, and "
    "structure should feel different for each league — no two titles should "
    "read like they came off the same assembly line. "
    "`paragraph` is the BODY — the fan voice + context prose that follows "
    "the title; it must NOT restate the anchor sentence, because the title "
    "already said it. Write it like ESPN news copy: plain, everyday words "
    "(say 'deal', 'agreed', 'said', 'told' — not 'cited as a key factor', "
    "'a product of', 'adds weight to the criticism'). Name the actual people "
    "and keep the concrete numbers from the items (a player's name, a poll "
    "percentage, a count of stadiums, an injury, a dollar figure) — do NOT "
    "abstract them into summary nouns ('the imbalance', 'the criticism', "
    "'fan passion'). Spell out jargon everywhere — never write 'pro/rel' or "
    "other abbreviations in the body either; write 'promotion and relegation'. "
    "Omit needless words: no filler adjectives like "
    "'procedural', 'initial', 'formal', 'significant', 'key' when the plain "
    "noun carries it — never 'took a procedural step forward', never 'initial "
    "procedural move' ('the league took the first step toward adding a team "
    "in Las Vegas', not 'the league took the initial procedural move toward "
    "adding a franchise in Las Vegas'). When the items name several players "
    "or teams involved, name several of them — do not collapse the story "
    "into one example. If the items mention an injury to a named player, "
    "include it. It is fine to use more words and more sentences; give "
    "the prose room to flow. Do not stack three facts into one compressed "
    "sentence with colons — one fact per clause, comma-connected, and if a "
    "sentence gets crowded, split it. A longer sentence that reads easily "
    "beats a short one the reader has to unpack. "
    "Each numbered item is `N. HEADLINE [source] (published date)`; real "
    "(non-bluesky) articles carry their URL and an `excerpt:` of the article "
    "body. USE THE EXCERPTS - the named people, direct quotes and figures in "
    "them are the strongest material you have, and a card built from headlines "
    "alone will be vague. "
    "MIND THE DATES. You are told today's date. An item published months or "
    "years ago is BACKGROUND, not news: never write it as though it happened "
    "now. If the best evidence for a conversation is old, say when it was said "
    "- \'ESPN reported last year\', \'in the 2025 tournament\' - and let the "
    "recent items carry the present tense. Never imply an old article is a "
    "current development. "
    "Output STRICT JSON only: "
    '{"narrative": "<one sentence: the conversation, anchored on the news — '
    'the title; unique voice, not a repeated template>", '
    '"fan_voice": "<the attributed fan side, one sentence>", '
    '"paragraph": "<2-4 sentences of plain ESPN-style body prose — fan voice '
    'with evidence, concrete names and numbers, room to flow; do NOT repeat '
    'the narrative>", '
    '"source_ids": [<n>, ...]}, where source_ids are the NUMBERS of the REAL '
    "(non-social) items that THIS card actually grounds in — just the integers "
    "from the numbered list, e.g. [1, 4]. Only those whose content you used for "
    "the anchor or the evidence. Empty list if the card is built from social "
    "chatter with no real article. Never invent a number that is not in the "
    "list. "
    "Only if the items are truly unrelated (no shared theme at all) output "
    '{"narrative": null}. '
    "Ground ONLY in the provided items. Do not invent topics, facts, or names "
    "not present in the list. Do not speculate about what might happen. "
    "The card follows THIS conversation's theme. The user may have marked "
    "prior cards for this conversation GOOD or BAD (an editor's pass — 'more "
    "of this' / 'less of that'); where those marks appear in the prompt they "
    "show what on-theme and off-theme LOOK like here. Infer the boundary from "
    "the contrast between the good and bad examples — do not apply a fixed "
    "rule, and never just echo a bad example's wording. With no marks yet, "
    "use the conversation title as the theme."
)


def _parse_response(text):
    """Parse the model's strict-JSON answer; tolerate code fences / stray text."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _load_chatter(con, conv):
    """Items for one conversation: the tagged bluesky chatter + the league's
    recent real articles.

    The conversation's bluesky posts are tagged with conv_id by the collector
    and are the fan-voice signal. The league's recent real (non-bluesky)
    articles are added as OFFICIAL ANCHOR material the fan posts are reacting
    to — a conversation whose chatter is all social still needs the real story
    to anchor the card (MLB salary-cap had zero real articles in its tagged
    bucket, so the desk had nothing to anchor on and correctly declined rather
    than fabricate; Micah 2026-08-07).

    The anchor pool is RELEVANCE-FILTERED. "The league's 8 most recent
    articles" put Messi's father's death into the Leagues Cup scouting card,
    and the model dutifully used it — Micah, 2026-08-10: "messi is a separate
    topic ... these cards aren't like a newsletter saying everything going on
    in a league." Trusting the model to ignore off-topic material it was
    explicitly told to mine does not work; do not hand it the material.

    Relevance is bridged through the conversation's OWN chatter, not through
    seed words. Seed-word matching alone was too narrow: the pro/rel card is
    anchored by the "commissioner Berg in charge" article, whose headline
    contains neither "relegation" nor "promotion". But the chatter talks about
    Berg, so the entity bridge keeps it — and drops Messi, whom this
    conversation's chatter never mentions.
    """
    conv_id, league = conv["id"], conv["league"]

    # RANK, do not gate (Micah, 2026-08-10). A threshold worked when the pool
    # was six articles and fails at a hundred: everything clears a low bar, so
    # a BIG3 story reached the NBA-expansion card and a matchday preview took
    # over the Leagues Cup scouting card. Scoring instead means a loosely
    # related item still loses to three closely related ones.
    topic_words = {w for w in _norm_words("%s %s" % (conv["seed"], conv["title"]))
                   if len(w) > 4 and w not in _GENERIC_WORDS}

    def _score(row, extra_entities=()):
        head = row["headline"] or ""
        words = {w for w in _norm_words(head) if len(w) > 4}
        return (3 * len(topic_words & words)
                + 2 * len(entities(head) & set(extra_entities)))

    # Pass 1 — the conversation's own chatter, ranked on the seed itself. There
    # can be ~100 tagged posts now, so "most recent 12" was arbitrary.
    chatter = [dict(r) for r in con.execute(
        """SELECT headline, url, source, published, body FROM news_items
           WHERE conv_id=? AND url != '' ORDER BY published DESC LIMIT 200""",
        (conv_id,)).fetchall()]
    chatter.sort(key=lambda r: (_score(r), r["published"] or ""), reverse=True)
    out = chatter[:_MAX_SOURCES]

    # Pass 2 — anchors scored on the seed AND on the entities the best chatter
    # actually talks about. Two passes, so the entity set comes from chatter
    # that already matched the seed rather than from whatever was tagged.
    topic_entities = set()
    for r in out:
        topic_entities |= entities(r["headline"])

    seen = {r["url"] for r in out}
    # Candidates: the recent league feed PLUS anything whose headline carries a
    # seed word, at any age. Recency alone cut the ESPN scouting feature — the
    # single best source this conversation has — because it is from 2025 and
    # fell outside the 120 most recent MLS rows (2026-08-10).
    sql = ("""SELECT headline, url, source, published, body FROM news_items
              WHERE league=? AND source NOT IN ('bluesky','x-search')
                AND url != '' ORDER BY published DESC LIMIT 120""")
    rows = list(con.execute(sql, (league,)).fetchall())
    if topic_words:
        like = " OR ".join(["lower(headline) LIKE ?"] * len(topic_words))
        rows += list(con.execute(
            """SELECT headline, url, source, published, body FROM news_items
               WHERE league=? AND source NOT IN ('bluesky','x-search')
                 AND url != '' AND (%s) LIMIT 60""" % like,
            (league, *["%%%s%%" % w for w in topic_words])).fetchall())
    candidates, urls = [], set()
    for r in rows:
        if r["url"] in seen or r["url"] in urls:
            continue
        urls.add(r["url"])
        candidates.append(dict(r))
    scored = [(_score(r, topic_entities), r["published"] or "", r)
              for r in candidates]
    scored = [t for t in scored if t[0] > 0]
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    out.extend(r for _s, _p, r in scored[:_ANCHORS])
    return out


_BODY_CHARS = 600


def _numbered(items, limit=None):
    """The item list as the model sees it.

    Real articles carry an EXCERPT of their body, not just a headline. The
    argument lives in the body: a 7,500-character ESPN feature quoting MLS
    executives on the record reached the model as a single headline, so the
    card could not use one quote or figure from it (2026-08-10). Bluesky posts
    are already their own full text and need no excerpt.
    """
    out = []
    for i, it in enumerate(items if limit is None else items[:limit]):
        real = it["source"] not in SOCIAL_SOURCES
        url = (" " + it["url"]) if real and it.get("url") else ""
        # The DATE, always. The ESPN scouting feature is from 2025 and the card
        # reported it as current, because the model had no way to know (Micah,
        # 2026-08-10: "it's dated in 2025. we must include that info when
        # sending to model so it's able to understand time").
        when = (it.get("published") or "")[:10]
        stamp = (" (%s)" % when) if when else " (date unknown)"
        tag = it["source"] if real else ("UNVERIFIED SOCIAL POST/%s" % it["source"])
        line = "%d. %s [%s]%s%s" % (i + 1, it["headline"], tag, stamp, url)
        body = ((it.get("body") if isinstance(it, dict) else "") or "").strip()
        if real and body and body[:40] not in it["headline"]:
            excerpt = body[:_BODY_CHARS]
            if len(body) > _BODY_CHARS:
                excerpt += "..."
            line += "\n   excerpt: %s" % excerpt
        out.append(line)
    return "\n".join(out)


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
    return any(it["source"] not in SOCIAL_SOURCES for it in items)


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


def _cited_sources(items, parsed):
    """Resolve the model's cited source_urls to the real-article receipts.
    Only URLs that are actually in the (non-bluesky) items become chips — a
    hallucinated URL never reaches the card (Micah, 2026-08-09)."""
    real = {it["url"]: it for it in items
            if it["source"] not in SOCIAL_SOURCES and it.get("url")}
    out = []
    seen = set()

    def _add(it):
        if it and it["url"] not in seen and it["source"] not in SOCIAL_SOURCES:
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


def _editor_marks(con, conv_id):
    """The user's good/bad verdicts on prior runs of this conversation, joined
    to the run cards. These are the few-shot 'editor preferences' — Micah
    2026-08-09: 'i just want to come in as an editor every now and then and
    say that was bad do less of that, this was good do more of this'. The
    model infers the on-theme/off-theme boundary from the CONTRAST between
    good and bad cards; no hardcoded rule. Returns a block to prepend to the
    user prompt, or '' when there are no marks yet (today's behavior)."""
    rows = con.execute(
        """SELECT f.verdict, r.narrative FROM news_card_feedback f
           JOIN news_narratives_runs r ON r.id = f.run_id
           WHERE f.conv_id=? ORDER BY f.created_at DESC LIMIT 6""",
        (conv_id,)).fetchall()
    good = [r["narrative"] for r in rows if r["verdict"] == "good"]
    bad = [r["narrative"] for r in rows if r["verdict"] == "bad"]
    if not good and not bad:
        return ""
    parts = []
    if good:
        parts.append("GOOD cards for this conversation — match this kind of "
                     "framing (more of this):\n" +
                     "\n".join("- %s" % n for n in good[:3]))
    if bad:
        parts.append("BAD cards — do NOT frame it this way (less of this):\n" +
                     "\n".join("- %s" % n for n in bad[:2]))
    return "Editor marks:\n" + "\n".join(parts) + "\n\n"


def _generate(conv, items, marks=""):
    # Real (non-bluesky) items carry their URL so the model can cite the exact
    # article it grounded in; bluesky posts are signal only (never a chip).
    numbered = _numbered(items)
    user = "%sToday is %s.\n\nConversation: %s (%s)\n\nRecent chatter:\n%s" % (
        marks, datetime.date.today().isoformat(), conv["title"], conv["league"],
        numbered)
    # Social posts feed the model's signal but are never shown as receipts —
    # only real articles the model actually cited become source chips. A
    # conversation whose chatter is ALL social still gets a card — that
    # chatter IS the signal (e.g. MLS relegation/promotion talk) — it just
    # renders with no source chips rather than being dropped entirely.
    for attempt in (0, 1):
        raw = _deepseek_chat(_SYSTEM, user, max_tokens=4000)
        parsed = _parse_response(raw)
        if parsed is None:
            continue  # unparseable — retry once
        if not parsed.get("narrative"):
            return {"declined": True}
        sources = _cited_sources(items, parsed)
        return {
            "narrative": parsed["narrative"].strip(),
            "fan_voice": str(parsed.get("fan_voice") or "").strip(),
            "paragraph": str(parsed.get("paragraph") or "").strip(),
            "sources": sources,
            "source_count": len(sources),
        }
    return None


def _generate_batch(convs_with_marks):
    """One DeepSeek call for the WHOLE set of conversations.

    Per-conversation calls each see only their own chatter, so the model
    cannot coordinate variety — it grabbed the same metaphor example for
    MLB and MLS ("cranks the pressure cooker to a boil"). A batch call shows
    every conversation and every title at once, so the model must vary the
    voice and cadence across the set (Micah, 2026-08-07: "do they all sound
    the same?"). Output: {conv_id: {narrative, fan_voice, paragraph}}
    or {conv_id: null} when a conversation is genuinely unrelated chatter.
    """
    blocks = []
    for conv, items, marks in convs_with_marks:
        # Dedupe by headline first — the collector stores the same post from
        # multiple feeds (duplicate Kupp posts were crowding out the Will
        # Anderson injury item and the model never saw it).
        seen_h = set()
        unique = []
        for it in items:
            h = (it["headline"] or "").strip()
            if h in seen_h:
                continue
            seen_h.add(h)
            unique.append(it)
        numbered = _numbered(unique, limit=10)
        header = "### %s (%s) — %s" % (conv["id"], conv["league"], conv["title"])
        blocks.append(("%s%s\n%s" % (marks, header, numbered)) if marks else
                      ("%s\n%s" % (header, numbered)))
    user = (
        "Today is %s.\n\n" % datetime.date.today().isoformat() +
        "Here are ALL the conversations to write cards for. They are part of "
        "one batch: read every block, then write every card. The titles MUST "
        "be varied across the batch — different verbs, different structures, "
        "different cadence. If two cards would sound alike, rephrase one. "
        "Decline (null) only for a block whose chatter is genuinely unrelated. "
        # source_urls MUST be in this schema. It was missing, and since the
        # batch prompt's schema is what the model actually follows, nine of
        # twelve cards came back with no receipts at all while their pools held
        # three to six real articles each (2026-08-10).
        "Output STRICT JSON: {\"conv_id\": {\"narrative\": ..., \"fan_voice\": "
        "..., \"paragraph\": ..., \"source_ids\": [<n>, ...]}, ...}\n"
        "source_ids are the NUMBERS of the real (non-social) items above that "
        "THIS card actually grounds in — just the integers from the numbered "
        "list, e.g. [1, 4]. Cite every article you drew a fact from; empty "
        "list only when the card is built purely from social chatter.\n\n"
        + "\n\n".join(blocks)
    )
    for attempt in (0, 1):
        raw = _deepseek_chat(_SYSTEM, user, max_tokens=_BATCH_MAX_TOKENS)
        parsed = _parse_response(raw)
        if parsed is None:
            continue
        return parsed
    return None


def _generate_batch_chunked(convs_with_marks, size=_BATCH_CHUNK):
    """One call for the whole set, falling back to chunks if that fails.

    Measured 2026-08-10: 3 conversations parse fine, 13 come back unparseable.
    DeepSeek runs at reasoning_effort=high and reasoning shares the max_tokens
    budget, so a wide batch spends it thinking and the JSON arrives truncated.
    A whole run of stale cards is the worst outcome — worse than losing some
    cross-card title variety — so retry in chunks before giving up.
    """
    parsed = _generate_batch(convs_with_marks)
    if parsed is not None:
        return parsed
    if len(convs_with_marks) <= size:
        return None
    print("  batch of %d unparseable — retrying in chunks of %d"
          % (len(convs_with_marks), size))
    merged = {}
    for i in range(0, len(convs_with_marks), size):
        chunk = convs_with_marks[i:i + size]
        got = _generate_batch(chunk)
        if got:
            merged.update(got)
        else:
            print("    chunk %d-%d failed" % (i, i + len(chunk)))
    return merged or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--convs", default="",
                    help="comma list of conv ids to generate (default: all)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
    _init_db()
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    if args.convs:
        wanted = set(c.strip() for c in args.convs.split(",") if c.strip())
        convs = [c for c in CONVERSATIONS if c["id"] in wanted]
    else:
        convs = CONVERSATIONS

    print("Conversation generation — %d conversations (%s)" % (len(convs), "1 batch DeepSeek call" if len(convs) > 1 else "1 per-conversation call"))

    # Load chatter for every conversation once; keep the ones with enough items.
    loaded = []
    for conv in convs:
        items = _load_chatter(con, conv)
        if len(items) < _MIN_ITEMS:
            print("  %-18s skipped (%d sources < %d)" % (conv["id"], len(items), _MIN_ITEMS))
            continue
        marks = _editor_marks(con, conv["id"])
        loaded.append((conv, items, marks))

    # Batch path: ONE model call across all conversations so the model can
    # vary titles against each other (per-call generation repeats templates).
    results = {}
    if len(loaded) > 1:
        parsed = _generate_batch_chunked(loaded)
        if parsed is None:
            # A totally failed batch must NOT wipe the live cards: leave the
            # old set serving and report. Per-conversation failures below
            # still delete only that conversation's stale card.
            print("  BATCH FAILED (model returned nothing parseable after retry) — keeping existing cards")
            results = {}
            for conv, items, marks in loaded:
                results[conv["id"]] = {"declined": False, "keep": True}
        else:
            for conv, items, marks in loaded:
                entry = parsed.get(conv["id"])
                if not entry or not entry.get("narrative"):
                    results[conv["id"]] = {"declined": True}
                    continue
                sources = _cited_sources(items, entry)
                results[conv["id"]] = {
                    "narrative": entry["narrative"].strip(),
                    "fan_voice": str(entry.get("fan_voice") or "").strip(),
                    "paragraph": str(entry.get("paragraph") or "").strip(),
                    "sources": sources,
                    "source_count": len(sources),
                }
    else:
        for conv, items, marks in loaded:
            gen = _generate(conv, items, marks)
            if gen is None:
                print("  %-18s FAILED (model returned nothing parseable after retry)" % conv["id"])
                continue
            results[conv["id"]] = gen

    written = 0
    for conv, items, marks in loaded:
        gen = results.get(conv["id"])
        if gen is None or gen.get("declined"):
            # A conversation that declines/fails this run must not keep
            # serving an old card (which may carry bluesky source chips).
            # Log the full served card being dropped first, so the editor can
            # review what vanished (Micah 2026-08-09).
            reason = "model-failure" if gen is None else "model-declined"
            if not args.dry_run:
                _log_deletion(con, conv, reason)
                con.execute("DELETE FROM news_narratives WHERE conv_id=?", (conv["id"],))
            print("  %-18s no narrative worth mentioning (%s)" % (conv["id"], reason))
            continue
        if gen.get("keep"):
            continue
        # A card must rest on published reporting. Social supplies the fan
        # voice; it never supplies the facts. Micah, 2026-08-10: "we need
        # trustworthy sources and can't expect the model to fact check every
        # post." This supersedes the earlier "chatter IS the signal" allowance
        # (2026-08-07) — chatter still shapes a card, it just cannot be the only
        # thing holding one up.
        if not had_publisher_material(items):
            print("  %-18s NOT SERVED — nothing published to stand on: %s"
                  % (conv["id"], gen["narrative"][:60]))
            if not args.dry_run:
                _log_deletion(con, conv, "no-publisher-material")
                con.execute("DELETE FROM news_narratives WHERE conv_id=?", (conv["id"],))
            continue
        if unsupported_allegation(gen):
            print("  %-18s REFUSED — alleges something about people with no "
                  "publisher receipt: %s" % (conv["id"], gen["narrative"][:70]))
            if not args.dry_run:
                _log_deletion(con, conv, "unsupported-allegation")
                con.execute("DELETE FROM news_narratives WHERE conv_id=?", (conv["id"],))
            continue
        if args.dry_run:
            print("  %-18s [dry-run] %s" % (conv["id"], gen["narrative"][:80]))
            continue
        con.execute(
            """INSERT INTO news_narratives(conv_id, league, title, narrative, fan_voice, paragraph, sources, source_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(conv_id) DO UPDATE SET
                league=excluded.league, title=excluded.title,
                narrative=excluded.narrative, fan_voice=excluded.fan_voice,
                paragraph=excluded.paragraph, sources=excluded.sources,
                source_count=excluded.source_count,
                generated_at=datetime('now')""",
            (conv["id"], conv["league"], conv["title"], gen["narrative"],
             gen.get("fan_voice", ""), gen.get("paragraph", ""),
             json.dumps(gen["sources"]), gen["source_count"]),
        )
        # Append to run history — every generation is kept, never overwritten,
        # so versions can be compared (Micah, 2026-08-07).
        con.execute(
            """INSERT INTO news_narratives_runs(conv_id, league, title, narrative, fan_voice, paragraph, sources, source_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (conv["id"], conv["league"], conv["title"], gen["narrative"],
             gen.get("fan_voice", ""), gen.get("paragraph", ""),
             json.dumps(gen["sources"]), gen["source_count"]),
        )
        written += 1
        print("  %-18s %s" % (conv["id"], gen["narrative"][:80]))
    con.commit()
    con.close()
    print("Wrote %d conversation cards to news_narratives" % written)


if __name__ == "__main__":
    main()
