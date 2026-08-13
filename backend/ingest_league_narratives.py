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
import hashlib
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _core import (REPORTER_ROSTER, SOCIAL_SOURCES,  # noqa: E402
                   _deepseek_chat, _init_db)
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


_MIN_TOPIC_LEN = 2   # was 4, which threw away the word naming the conversation


def _significant(text):
    """The words in `text` that can identify a topic.

    The length floor used to be 4, applied on BOTH sides — to the seed and to
    every headline — so a word had to be five characters to exist at all. That
    discarded the word the conversation is NAMED for: `nfl-turf-grass` kept
    `grass` and lost **turf**; `nhl-salary-cap` and `mlb-salary-cap` kept
    `salary` and lost **cap**. Measured 2026-08-12 across the 14 live
    conversations, restoring them moved 10 of 14 to a higher top score with
    fewer candidates tied on it (turf 1/25 -> 3/11, cap 1/22 -> 3/18).

    A floor that low needs the common short words named instead of guessed at,
    which is what `_STOPWORDS` is for.
    """
    return {w for w in _norm_words(text or "")
            if len(w) > _MIN_TOPIC_LEN
            and w not in _GENERIC_WORDS and w not in _STOPWORDS}


def _topic_words(conv):
    """The words that identify one conversation, from its seed and title.

    Module-level rather than a closure because anchor routing has to compute it
    for a conversation's SIBLINGS, not just for itself (see `_better_home`).
    """
    return _significant("%s %s" % (conv["seed"], conv["title"]))


def _topic_hits(headline, topic_words):
    return len(topic_words & _significant(headline))


def weak_seed(headline, topic_words, tied):
    """Did the SEED pick this winner, or did recency pick it?

    A tie at the top is a finding, not a result: when the best candidates all
    score the same the sort falls through to recency, and the card is built
    from "the most recent league article containing one common word".

    Measured on the raw seed hits, never on the composite `_score`
    (`3*topic + 2*entity`) — the question is whether the SEED discriminated,
    and a composite of 3 is one topic word doing all the work. And a one-word
    seed can never land more than one hit, so demanding two convicts it for a
    ceiling it cannot clear.
    """
    hits = _topic_hits(headline, topic_words)
    want = max(1, min(2, len(topic_words)))
    return hits < want or tied >= _TIE_ALARM


def _better_home(con, conv, headline, own_entities=(), _cache={}):
    """The sibling conversation this anchor belongs to more than `conv`, or None.

    Each card used to score the league feed on its own, with no idea its
    siblings existed. So one story could win a place in several pools at once,
    and the newest copy of it then led every card that took it. That is how
    Messi's father's death — which has its own card, `mls-messi-absence`, 34
    tagged items deep — also opened the Leagues Cup SCOUTING card, three weeks
    after Micah split them apart precisely so it would not (see the note on
    news_conversations.mls-messi-absence, 2026-08-10).

    Note the near miss: URL-level dedupe across pools finds NOTHING here (0 of
    130 anchors are shared). The cards were not holding the same article, they
    were holding the same STORY through different articles. So routing has to
    compare subjects, not urls.

    Strictly higher wins, so a tie leaves the anchor where it is: this decides
    which conversation owns a story, and it should only move one when another
    conversation is a clearly better fit.

    An anchor that touches THIS conversation's own chatter is never routed away,
    whatever a sibling scores. Word counts alone cannot separate an incidental
    match from a core one — "Inter Miami finalizing $15M Berterame transfer"
    matches `mls-ligamx-spending` on one word (transfer, its whole subject, and
    the very deal its conv note cites as evidence) and `mls-messi-absence` on
    two (inter, miami — a club name that card's seed happens to carry). Counting
    words, the transfer card loses its own headline story. Its chatter is the
    tiebreak: the spending conversation is demonstrably talking about this deal,
    and the Leagues Cup scouting chatter never mentions Messi at all.
    """
    # The bridge must be evidence BEYOND the seed, or it is circular. "Leagues
    # Cup" is an entity in the scouting conversation's chatter, and it is also
    # that conversation's own seed word — so every Messi fixture story bridged
    # on it and the guard readmitted exactly what routing had just removed. An
    # entity whose words are already the conversation's topic words carries no
    # information about whether THIS story belongs here.
    own_words = _topic_words(conv)
    bridge = {e for e in own_entities if not (_norm_words(e) & own_words)}
    if bridge and entities(headline or "") & bridge:
        return None
    league = conv["league"]
    if league not in _cache:
        _cache[league] = [dict(r) for r in con.execute(
            "SELECT id, league, seed, title FROM news_conversations "
            "WHERE league=? AND active=1", (league,)).fetchall()]
    mine = _topic_hits(headline, _topic_words(conv))
    best, best_score = None, mine
    for other in _cache[league]:
        if other["id"] == conv["id"]:
            continue
        score = _topic_hits(headline, _topic_words(other))
        if score > best_score:
            best, best_score = other["id"], score
    return best


_MAX_SOURCES = 12
_MIN_ITEMS = 2  # fewer than this and there's no "chatter" to summarize
_BATCH_MAX_TOKENS = 24000  # reasoning shares this budget; 10000 truncated 13 cards
_BATCH_CHUNK = 4           # fallback width when the wide batch will not parse
_ANCHORS = 6               # real articles shown per card, best-scoring first
_TIE_ALARM = 8             # candidates tied at the top score = the seed did nothing
# Words that are in every seed and every headline, so a hit on them means
# nothing. Same lesson as the classifier's substring bug.
_GENERIC_WORDS = {"deal", "deals", "talks", "rights", "season", "league",
                  "team", "teams", "game", "games", "news", "player",
                  "players", "sports", "picture", "debate", "case", "about",
                  "after", "before", "their", "there", "these", "those"}

# The short common words, named explicitly. Length used to stand in for
# significance — anything of four characters or fewer was assumed to be a
# stopword, which is true of "the" and "with" and false of "turf", "cap",
# "NIL" and "cup". Naming them is the only way to keep the short words that
# carry a topic while dropping the short words that carry nothing.
_STOPWORDS = {
    "the", "and", "for", "was", "are", "his", "her", "its", "new", "two",
    "one", "out", "off", "not", "but", "who", "how", "why", "all", "has",
    "had", "him", "she", "they", "won", "top", "big", "set", "say", "says",
    "get", "got", "now", "can", "will", "from", "with", "this", "that",
    "have", "been", "more", "than", "over", "into", "just", "when", "what",
    "said", "year", "week", "day", "days", "time", "back", "down", "here",
    "him", "make", "made", "take", "takes", "look", "looks", "could", "would",
    "should", "amid", "still", "next", "last", "first", "full", "way",
}

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
    "THE OUTLET IS NOT THE STORY (Micah, 2026-08-12). The source chips under "
    "the card already say who reported it, so the prose does not have to. A "
    "paragraph built out of \"Bleacher Report reported… Yahoo Sports quoted… "
    "Axios reported…\" is a media-monitoring digest, not a story about the "
    "sport, and it puts the newsroom in the subject slot where the player, the "
    "club or the league belongs. Write the FACT as the subject: \"The Patriots' "
    "surface at Gillette Stadium was ruled noncompliant\", never \"Bleacher "
    "Report reported the Patriots' surface was ruled noncompliant\". Name a "
    "masthead ONLY when who reported it is itself the fact — one outlet's "
    "exclusive that nobody else has matched, a claim another outlet disputes, a "
    "report the league or the player has denied. That is rare. MOST CARDS "
    "SHOULD NAME NO OUTLET AT ALL, and no card should name more than one. "
    "NAME ONLY OUTLETS YOU ARE CITING. When you do name one, it must be one of "
    "the numbered publisher items and you must list it in source_ids. A social "
    "post that "
    "LINKS to an outlet is not that outlet reporting to you: you have read the "
    "post, not the article, so write \"posts cited a report that…\" and name no "
    "masthead. Never credit the account, aggregator or site that reposted "
    "someone else's article as though it were the publisher. "
    "A PUBLISHED CONFIRMATION OUTRANKS A RUMOUR, INCLUDING ITS TENSE. When a "
    "publisher item says a move is DONE and the posts still call it pending, "
    "the move is done: write it in the past tense and drop the hedge. Do not "
    "call something \"unconfirmed\" or \"reportedly\" or \"being finalized\" "
    "when a numbered publisher item in your own list confirms it, and do not "
    "carry an old superlative (\"currently leads the league\") past the date "
    "the publisher items support. Check the dates on the items: they are given "
    "to you for this. "
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
    "ATTRIBUTION IS NOT VERIFICATION (Micah, 2026-08-13). \"Fans argue…\" does "
    "not make a claim safe to carry — it only moves who is blamed for it. If a "
    "figure, a transfer, a contract or an allegation is not in a publisher "
    "item, putting it in a fan's mouth does not get it into the card. Attribute "
    "only what a numbered post actually SAYS, and never invent the "
    "constituency: if no post in your list is a person talking, write no fan "
    "sentence at all and leave fan_voice empty. That is a normal outcome, not a "
    "failure — most of these cards have a real story to tell without a chorus. "
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
    "now. If the best evidence for a conversation is old, say WHEN - \'reported "
    "last year\', \'in the 2025 tournament\', \'since last season\' - and let "
    "the recent items carry the present tense. Date it, do not credit it: the "
    "reader needs to know the claim is a year old, not which masthead made it. "
    "Never imply an old article is a current development. "
    "THE ITEMS ARE SPLIT INTO DEVELOPMENTS AND BACKGROUND. The narrative "
    "sentence must be anchored on a DEVELOPMENT. A BACKGROUND item is what is "
    "ALREADY TRUE — it may explain why the development matters, and it may "
    "never supply the verb that makes the card sound like news. Above all, "
    "never announce a background item as though it were beginning now: if a "
    "year-old feature said a competition IS BECOMING a scouting stage, then "
    "today it already IS one, and the new results are evidence of it maturing "
    "- write that it is deepening, holding or being borne out, not that it is "
    "starting. When every item is background, write the standing state of "
    "play in the present tense and do not manufacture a development. "
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
    topic_words = _topic_words(conv)

    def _score(row, extra_entities=()):
        head = row["headline"] or ""
        words = _significant(head)
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

    # A TIE AT THE TOP is a finding, not a result. When the best-scoring
    # candidates all score the same, the sort falls through to recency and the
    # card is built from "the most recent league article containing one common
    # word" — which is exactly how `esports worlds` produced a card about the
    # Esports World Cup instead of League of Legends Worlds: 57 articles tied
    # at 1, because `esports` matches everything in the esports league and
    # "Esports World Cup" also catches `worlds`. Nothing failed; the seed
    # simply did no work, and no run said so (Micah, 2026-08-12: "worlds does
    # seem too generic").
    if scored:
        top = scored[0][0]
        tied = sum(1 for t in scored if t[0] == top)
        seed_hits = _topic_hits(scored[0][2]["headline"], topic_words)
        if weak_seed(scored[0][2]["headline"], topic_words, tied):
            print("    WEAK SEED: %s — best candidate matches %d seed word(s), "
                  "%d tied at that rank (ranking fell through to recency); "
                  "topic words: %s"
                  % (conv_id, seed_hits, tied,
                     ",".join(sorted(topic_words)) or "none"))

    # Route: an anchor that fits a sibling conversation better belongs to that
    # sibling, not to both. Dropped OUT LOUD — a card quietly annexing another
    # card's story is exactly the failure this pass exists to stop, so a silent
    # drop would hide the fix working as surely as it hid the bug.
    kept_anchors = []
    for _s, _p, r in scored:
        if len(kept_anchors) >= _ANCHORS:
            break
        owner = _better_home(con, conv, r["headline"], topic_entities)
        if owner:
            print("    route: %s -> %s | %s" % (
                conv["id"], owner, (r["headline"] or "")[:70]))
            continue
        kept_anchors.append(r)
    out.extend(kept_anchors)
    return out


_BODY_CHARS = 600
_PROMPT_ITEMS = 10   # how many pool items reach the model, per card
_SHOW_ANCHORS = 6    # of those, reserved for published articles

# Hosts that serve posts, whatever the row's `source` column happens to say.
_SOCIAL_HOSTS = ("bsky.app", "bsky.social", "twitter.com", "x.com", "nitter",
                 "mastodon", "threads.net", "reddit.com", "t.co")


def is_social(it):
    """True when this item is a POST, not published reporting.

    Membership in `SOCIAL_SOURCES` is checked first, then the SHAPE of the item,
    because the name list has already failed once in the way that matters: `x`
    was not in it while 855 rows carried that source, so every tweet in the
    corpus counted as a verified publisher. A tweet with a false claim reached a
    card as fact that way (Micah, 2026-08-12), and the same hole let two tweets
    into the publisher half of the MLS spending pool.

    Adding the missing string would fix those 855 rows and leave the mechanism
    intact for the next feed someone adds. So this also refuses anything that
    LOOKS like a post — our collector prefixes every one with `[@handle]`, and
    social hosts are recognisable in the URL — and a caller can report the
    disagreement rather than silently trusting the column
    (see `social_leaks`). An item only has to look like a post ONCE, anywhere,
    to be kept out of the receipts.
    """
    if (it.get("source") or "") in SOCIAL_SOURCES:
        return True
    if (it.get("headline") or "").lstrip().startswith("[@"):
        return True
    url = (it.get("url") or "").lower()
    return any(h in url for h in _SOCIAL_HOSTS)


def social_leaks(items):
    """Items the `source` column calls published but that are posts by shape.

    Every one of these is a row that would have been served as a receipt. This
    is the loud half of `is_social`: the guard stops them silently, and this
    reports them so the source list actually gets fixed instead of the guard
    quietly carrying the hole forever.
    """
    return [it for it in items
            if (it.get("source") or "") not in SOCIAL_SOURCES and is_social(it)]


_LINK_RE = re.compile(r"https?://\S+")
_HANDLE_RE = re.compile(r"^\s*\[@([^\]]+)\]\s*")


def post_text(it):
    """A post's own words: the headline with the collector's `[@handle]` cut off."""
    h = it.get("headline") or ""
    m = _HANDLE_RE.match(h)
    return h[m.end():] if m else h


def post_handle(it):
    """The account that posted, or "" for anything that is not a post."""
    m = _HANDLE_RE.match(it.get("headline") or "")
    return m.group(1) if m else ""


# Selling, not reporting. A brand desk's posts are roughly half promotion, and
# promotion is the one kind of social content with a MOTIVE to overstate.
_PROMO_MARKERS = ("sign up", "promo code", "use code", "download the app",
                  "odds on", "bet now", "deposit", "sponsored", "giveaway",
                  "enter to win", "link in bio", "available now on")


def is_promo(it):
    """True when the post exists to sell something."""
    text = post_text(it).lower()
    return any(m in text for m in _PROMO_MARKERS)


# A reporter claiming a story as their own, not handing it to someone else.
# Kept to words that assert firsthand sourcing: "Report:" and "ICYMI:" and
# "Opinion:" are the opposite and stay relays.
_FIRSTHAND_MARKERS = ("sources", "source", "breaking", "exclusive", "update")


def is_relay(it, published_titles=()):
    """True when the post CARRIES someone else's story rather than asserting one.

    The distinction that replaces "is this a tweet?", which was the wrong
    question twice over (Micah, 2026-08-13: "youre right abiut the buckets but
    wrong abiut who falls into them"). A named reporter posting firsthand IS the
    reporting — the outlet's article is downstream of them. A bot pasting an
    article's lede is not reporting at any volume. Platform predicts neither.

    Three shapes, all mechanical, none keyed on the account name:

      * prose CONTINUING past an outbound link — a person links at the end of
        what they wanted to say, a scraper pastes the lede after it. This is
        what `rawnfl`/`rawnba`/`rawchili` do: 10 of 46 social items reaching
        the model, including the `rawnfl` repost that put "Supporters point to
        LSU's reported nine-figure media-rights deal" in a card when no
        publisher item mentioned LSU at all;
      * an explicit retweet marker — "RT by @AdamSchefter: Happy to have EB
        back" is Schefter passing something along, not Schefter reporting, and
        a roster entry must not launder it into a receipt;
      * the story is already in the pool as a publisher item — how `[@cnbc.com]`
        posting CNBC's own article sat beside the `cnbc` item and spent a fan
        slot saying the same thing twice.

    Name-keying was tried first and rejected the same day: "the handle is a
    domain" catches `[@cnbc.com]` and also `[@mothmaam.online]`, a real fan
    whose 25-part video series on salary-cap circumvention is the entire fan
    voice of the Kawhi card. Bluesky lets a person be their own domain. Both
    outlet accounts are caught by the duplicate test anyway, which is evidence
    rather than a guess.
    """
    text = post_text(it)
    if re.match(r"^\s*RT by @", text, re.I) or re.match(r"^\s*RT @", text, re.I):
        return True
    # Attribution IN THE TEXT, with no link to give it away. A desk writing
    # "Schefter: Laremy Tunsil unlikely to play" is passing on someone else's
    # scoop, and the link-shaped tests never see it.
    #
    # `Word:` is not always an attribution, and reading it as one demoted the
    # highest-value post in the corpus: Ian Rapoport's "Sources: The #Patriots
    # have agreed to terms with their standout TE Hunter Henry on a 2-year
    # contract" is his OWN scoop, and `Sources:` is the signature of firsthand
    # reporting rather than a hand-off. The carve-out is deliberately tiny —
    # only a rostered account, only these markers — because the same prefix on
    # an unrostered account is a headline bot ("Opinion:", "Feed:", "Final:",
    # all measured in this corpus) and the fan lane is where a headline bot
    # does its damage. An unknown account keeps failing closed into `relay`.
    prefix = re.match(r"^\s*([A-Z][A-Za-z.\-]+)\s*:", text)
    firsthand = (prefix and prefix.group(1).lower() in _FIRSTHAND_MARKERS
                 and post_handle(it) in REPORTER_ROSTER)
    if (prefix and not firsthand) or re.search(r"\b(via|per|h/t)\s+@?[A-Z]", text):
        return True
    m = _LINK_RE.search(text)
    # Prose CONTINUING past an outbound link is scraped article body.
    if m and text[m.end():].strip():
        return True
    # An outlet posting its own story, matched on the story rather than on the
    # account. 40 characters of squashed headline, either way round, because a
    # post may trim a long headline or append the section label the feed adds.
    body = _squash_title(_LINK_RE.sub("", text))[:40]
    return bool(body) and any(body in t or t[:40] in body
                              for t in published_titles if t)


def post_role(it, published_titles=()):
    """What this item IS: publisher | reporting | relay | promo | voice.

    One function so the roles cannot drift apart, and cheap enough to run over
    the whole corpus: four mechanical signals, no model call.

      publisher  a real article from the news feeds. Citable, as always.
      reporting  a ROSTERED account asserting something firsthand. Citable, and
                 the chip names the person and their outlet.
      relay      carrying someone else's story. Never a receipt — crediting the
                 account that reposted an article is crediting a scraper for
                 another newsroom's work — but a pointer to reporting we are
                 missing, which is what 200 distinct rawchili stories turned
                 out to be.
      desk       a brand account aggregating other people's reporting. Not a
                 receipt and not a fan — see the note in the body.
      promo      selling. Dropped.
      voice      a person reacting. The fan lane, and only this.

    Order matters: relay and promo are tested BEFORE the roster, so a rostered
    reporter's retweet or ad read cannot inherit their credibility. The roster
    is an upgrade applied to firsthand assertions only.
    """
    if not is_social(it):
        return "publisher"
    if is_promo(it):
        return "promo"
    if is_relay(it, published_titles):
        return "relay"
    if post_handle(it) in REPORTER_ROSTER:
        return "reporting"
    # VOICE IS NOT THE FALLBACK. Making it the default is the same fail-open
    # shape the roster was built to avoid, one lane over: the roster refuses to
    # trust an unknown account with a receipt, and then the leftover branch
    # handed that same account to the model as a fan. `@UnderdogNFL` — a desk
    # posting "JK Dobbins left practice with trainers Monday", 83 items a day —
    # came out as a supporter (measured 2026-08-13, before this branch).
    #
    # Nothing here is keyed on the name. HOW THE ITEM ENTERED THE CORPUS says
    # which lane it belongs to, and the collector already knows: `x` rows are
    # timelines we chose to follow, so they are publications by construction and
    # can never be a stranger reacting. `bluesky`/`x-search` rows are keyword
    # searches of the open network, which is where the public actually is. A
    # desk is not a receipt and not a fan; it is aggregation, and it sits with
    # the relays until something earns it a place on the roster.
    if (it.get("source") or "") not in ("bluesky", "x-search"):
        return "desk"
    return "voice"


def _content_words(s):
    return {w for w in re.findall(r"[a-z]{4,}", (s or "").lower())
            if w not in _CORROB_STOP}


_CORROB_STOP = {"this", "that", "with", "from", "have", "will", "been", "says",
                "said", "after", "about", "their", "they", "there", "were",
                "would", "could", "more", "than", "into", "over", "just"}


def corroboration(it, corpus, min_overlap=4):
    """`corroborated` when an INDEPENDENT source carries the same claim, else
    `single-source`.

    Deliberately separate from `REPORTER_ROSTER`, and computed the same way for
    a Hall-of-Famer and a stranger: a trust list that also decided what counted
    as confirmation could confirm itself. A wrong roster entry can cost us a
    story; it must never be able to make an unmatched claim read as verified.

    Measured across the corpus 2026-08-13, over the eight rostered reporters:
    81 posts corroborated, 222 single-source. That 73% is the product argument
    for carrying them at all — it is reporting our publisher feeds do not have —
    and it is exactly why the state has to be SHOWN rather than hidden. Being
    first is worth nothing if a reader cannot tell it apart from being
    confirmed, so the card says which one it is.
    """
    w = _content_words(post_text(it))
    if len(w) < 3:
        return "unknown"
    handle = post_handle(it)
    for other in corpus:
        if other is it or (other.get("url") or "") == (it.get("url") or ""):
            continue
        # Independence, not merely difference: the same desk repeating itself
        # on two feeds is one source, and a reporter cannot corroborate their
        # own post.
        if handle and post_handle(other) == handle:
            continue
        if len(w & _content_words(post_text(other))) >= min_overlap:
            return "corroborated"
    return "single-source"


def _squash_title(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _prompt_items(items, limit=_PROMPT_ITEMS):
    """The EXACT list the model is shown — published articles first.

    Two defects lived in the four lines this replaces, both measured on dev
    2026-08-12.

    **The model was never shown the reporting.** `_load_chatter` returns social
    chatter first (up to 12) and appends the publisher anchors after it, and the
    prompt took `[:10]`. So for any conversation with a busy social lane, the
    anchors fell off the end and the card was written from bluesky alone. Six of
    fourteen conversations were in that state, and they are EXACTLY the six
    cards serving `source_count = 0`:

        esports-worlds  mls-ligamx-spending  mls-messi-absence
        nba-expansion   nfl-media-rights     nhl-salary-cap

    The spending card called a completed transfer "unconfirmed social reports"
    while The Athletic, USA Today and mlssoccer.com sat in its pool unread. That
    is `published-first` §1 exactly: we had the published fact and used the
    chatter about it. Reserving anchor slots is the fix — a card may still be
    chatter-only, but only when there is genuinely nothing published to show it.

    **Citations resolved against the wrong list.** The prompt numbered the
    DEDUPED items while `_cited_sources` indexed the raw pool, so every number
    after a dropped duplicate pointed one article too early. Two of fourteen
    conversations were misaligned — mlb-salary-cap's "#7" was a Skubal salary-cap
    piece in the prompt and a bluesky post in the resolver. A wrong receipt is
    worse than no receipt: it is a citation to something that does not say it.
    Callers now number and resolve against this one list.
    """
    seen, uniq = set(), []
    for it in items:
        # The collector stores the same post from several feeds; duplicates
        # crowded a real injury item out of the window once already.
        h = (it["headline"] or "").strip()
        if h in seen:
            continue
        seen.add(h)
        uniq.append(it)
    articles = [i for i in uniq if not is_social(i)]
    titles = {_squash_title(i.get("headline")) for i in articles}
    roles = {id(i): post_role(i, titles) for i in uniq}
    # Rostered reporting sits with the ANCHORS, not with the chatter. Schefter
    # breaking a trade is the story, and shelving it in the fan lane is how a
    # card ends up citing the writeup of a scoop we already had.
    anchors = articles + [i for i in uniq if roles[id(i)] == "reporting"]
    # The chatter lane is for VOICE and nothing else. A repost bot and an
    # outlet's own account are carrying an article, not saying anything, and
    # handing them to the model under "what fans are saying" is how a card
    # acquires supporters who do not exist (see `post_role`). Deduping on the
    # raw headline above cannot catch them: the collector's `[@handle]` prefix
    # means an outlet's post of its own story never string-matches the
    # publisher item beside it.
    chatter = [i for i in uniq if roles[id(i)] == "voice"]
    n_anchor = min(len(anchors), _SHOW_ANCHORS)
    n_chat = min(len(chatter), limit - n_anchor)
    # Slots the chatter did not need go back to the anchors, never wasted.
    n_anchor = min(len(anchors), limit - n_chat)
    return anchors[:n_anchor] + chatter[:n_chat]


_FRESH_DAYS = 21     # newer than this is a DEVELOPMENT; older is BACKGROUND


def _age_days(it, today=None):
    """Days between an item's publish date and today. None when undated."""
    when = (it.get("published") or "")[:10]
    try:
        pub = datetime.date.fromisoformat(when)
    except ValueError:
        return None
    return ((today or datetime.date.today()) - pub).days


def is_background(it, today=None):
    """True when this item describes an already-established state, not news.

    The distinction the card kept getting wrong. A 2025 ESPN feature titled
    "How Leagues Cup is becoming a hotbed for global scouting" scored highest
    in its conversation — it is the single most on-topic article we hold — so
    it supplied the card's one-sentence hook, and the card announced that the
    Leagues Cup "becomes a global scouting stage" in August 2026. Micah:
    "as if that article that talked about it being a proving ground didn't
    come out last year. Leagues Cup is already a proving ground and them
    signing him is proof. it's maturing."

    Relevance ranking has no opinion about time, so the oldest item in a pool
    can be its strongest, and nothing downstream noticed the tense was a year
    late. An undated item is treated as background: we cannot claim it is new.
    """
    age = _age_days(it, today)
    return age is None or age > _FRESH_DAYS


def split_by_age(items, today=None):
    """(developments, background), each as (index, item) with the index the
    item holds in `items` — the number the prompt shows and `_cited_sources`
    resolves against. Grouping must never renumber."""
    fresh, old = [], []
    for i, it in enumerate(items):
        (old if is_background(it, today) else fresh).append((i, it))
    return fresh, old


def stale_anchor(gen, shown, today=None):
    """True when a card cites ONLY background while fresh reporting was in
    front of it — the shape that dated the Leagues Cup card by a year.

    Reported, never fatal: a card standing entirely on background can be
    correct (the state of play has not moved). It is a finding when there were
    developments available and the card reached past them anyway.

    Only PUBLISHED developments count. A social post can never legitimately
    become a source chip — that is what the SOCIAL LEAK check exists to stop —
    so a pool whose only fresh items are posts leaves the card no citable
    development, and citing background is then the correct answer rather than
    a defect. Measured 2026-08-12: `mls-leaguescup-proving` was flagged with
    three developments in front of it, all three of them bluesky/x posts, while
    the card was already carrying them properly as fan voice ("posts note
    Santos Laguna has lost three straight"). A check that demands a citation
    the rules forbid is asking for the leak.
    """
    cited = {(s.get("url") or "") for s in gen.get("sources") or []}
    if not cited:
        return False
    fresh, _old = split_by_age(shown, today)
    fresh = [(i, it) for i, it in fresh if not is_social(it)]
    if not fresh:
        return False
    return not any((it.get("url") or "") in cited for _i, it in fresh)


def pool_key(shown, marks=""):
    """Fingerprint of the material a card was written from.

    Same fingerprint means the same items and the same editor marks, so
    regenerating can only produce different WORDS for an unchanged story. The
    urls, not the count: an item swapped for another of equal age would leave a
    count identical and the story different.
    """
    urls = sorted((it.get("url") or "") for it in shown)
    h = hashlib.sha1()
    h.update("\n".join(urls).encode("utf-8"))
    h.update(b"\x00")
    h.update((marks or "").encode("utf-8"))
    return h.hexdigest()


def newest_item(shown):
    """The publish timestamp of the freshest item shown, '' if none is dated."""
    return max([(it.get("published") or "") for it in shown] or [""])


def _numbered(items, limit=None, today=None):
    """The item list as the model sees it, split into DEVELOPMENTS and
    BACKGROUND.

    Real articles carry an EXCERPT of their body, not just a headline. The
    argument lives in the body: a 7,500-character ESPN feature quoting MLS
    executives on the record reached the model as a single headline, so the
    card could not use one quote or figure from it (2026-08-10). Bluesky posts
    are already their own full text and need no excerpt.

    The DATE alone was not enough. Every item already carried its publish date
    and the instruction to mind it, and the card still wrote a year-old feature
    as today's development — a date on line 1 of ten is a fact the model has to
    act on, a header it has to read past. The two groups say which items the
    present tense belongs to. Numbering is the item's index in `items` either
    way, because `_cited_sources` resolves citations by that number.
    """
    lines = {}
    for i, it in enumerate(items if limit is None else items[:limit]):
        real = not is_social(it)
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
        lines[i] = line
    shown = (items if limit is None else items[:limit])
    fresh, old = split_by_age(shown, today)
    out = []
    if fresh:
        out.append("DEVELOPMENTS — new since the last card. The news is here:")
        out += [lines[i] for i, _it in fresh]
    if old:
        out.append("BACKGROUND — already established, reported %d+ days ago. "
                   "Context only, never the news:" % _FRESH_DAYS)
        out += [lines[i] for i, _it in old]
    if not fresh:
        out.append("(NOTHING NEW. Every item above is background — write the "
                   "state of play, not a development.)")
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
    # Same selection as the batch path, so citation numbers mean the same thing
    # on both — and so a single-conversation run cannot be shown a different
    # pool than a batched one.
    items = _prompt_items(items)
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
        numbered = _numbered(_prompt_items(items))
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
    ap.add_argument("--force", action="store_true",
                    help="regenerate even when the item pool has not changed")
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
    leaks = unchanged = 0
    for conv in convs:
        items = _load_chatter(con, conv)
        # A post that the `source` column calls published would be served as a
        # receipt. Say so — the guard keeps it out of the anchors either way,
        # but a silent guard means the source list never gets corrected.
        # Count the voice this conversation actually has. A card with none is
        # not an error — it just has no business writing a fan sentence — but
        # it is worth seeing, because a lane that is all bots means the
        # collector is following aggregators instead of people.
        shown = _prompt_items(items)
        if not speakers_shown(shown):
            print("    NO VOICE: %s — every post in the pool carries an "
                  "article; the card must not speak for fans" % conv["id"])
        for it in social_leaks(shown):
            leaks += 1
            print("    SOCIAL LEAK: source=%r is a post, not a publisher | %s"
                  % (it.get("source"), (it.get("headline") or "")[:60]))
        if len(items) < _MIN_ITEMS:
            print("  %-18s skipped (%d sources < %d)" % (conv["id"], len(items), _MIN_ITEMS))
            continue
        marks = _editor_marks(con, conv["id"])
        # Nothing new to say → say the same thing. A rewrite off an unchanged
        # pool can only change the WORDS, and a card whose title moves nightly
        # while the story stands still teaches a reader that a change means
        # nothing (Micah, 2026-08-12). --force regenerates anyway, which is what
        # you want after changing the prompt.
        key = pool_key(_prompt_items(items), marks)
        served = con.execute(
            "SELECT pool_key, generated_at FROM news_narratives WHERE conv_id=?",
            (conv["id"],)).fetchone()
        if served and served["pool_key"] == key and not args.force:
            unchanged += 1
            print("  %-18s unchanged — no new items since %s"
                  % (conv["id"], served["generated_at"]))
            continue
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
                # Resolve against the list the PROMPT numbered, not the raw
                # pool — see _prompt_items. These had drifted apart.
                sources = _cited_sources(_prompt_items(items), entry)
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

    written = unattributed = ignored = stale = voiceless = 0
    namedrops = piled = 0
    for conv, items, marks in loaded:
        # The items the model was actually shown — every check below is
        # about what it saw, not about what sat unread in the pool.
        shown = _prompt_items(items)
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
        # Judged on what the model was SHOWN, not on what sat unread in
        # the pool — the gate has to ask about the material the card was
        # actually written from.
        if not had_publisher_material(shown):
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
            """INSERT INTO news_narratives(conv_id, league, title, narrative, fan_voice, paragraph, sources, source_count, pool_key, newest_item)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(conv_id) DO UPDATE SET
                league=excluded.league, title=excluded.title,
                narrative=excluded.narrative, fan_voice=excluded.fan_voice,
                paragraph=excluded.paragraph, sources=excluded.sources,
                source_count=excluded.source_count,
                pool_key=excluded.pool_key, newest_item=excluded.newest_item,
                generated_at=datetime('now')""",
            (conv["id"], conv["league"], conv["title"], gen["narrative"],
             gen.get("fan_voice", ""), gen.get("paragraph", ""),
             json.dumps(gen["sources"]), gen["source_count"],
             pool_key(shown, marks), newest_item(shown)),
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
        # Provenance the card claims in prose but cannot show. Reported, never
        # fatal — see uncited_outlets.
        loose = uncited_outlets(gen, _outlet_vocab(con))
        if loose:
            unattributed += 1
            print("    UNCITED OUTLET: names %s with no receipt for it"
                  % ", ".join(loose))
        # Mastheads in the subject slot. The chips already carry provenance, so
        # a second one is a digest of who wrote about the sport rather than a
        # story about it. Counted, never fatal — one attribution can be
        # legitimate when the reporting is itself the fact.
        credited = credited_outlets(gen, _outlet_vocab(con))
        namedrops += len(credited)
        if len(credited) > 1:
            piled += 1
            print("    MASTHEAD PILE-UP: attributes to %d outlets — %s"
                  % (len(credited), ", ".join(credited)))
        # A card that had reporting in front of it and cited none of it. Not
        # fatal either, but it is the signature of the six blind pools, so it
        # must be visible if it comes back.
        if not gen["source_count"] and had_publisher_material(shown):
            ignored += 1
            print("    IGNORED %d publisher items — card cites nothing"
                  % sum(1 for i in shown if not is_social(i)))
        # A card that reached past this week's reporting to stand on an old
        # article — how a 2025 feature became an August 2026 development.
        if stale_anchor(gen, shown):
            stale += 1
            print("    STALE ANCHOR: cites only background while %d "
                  "development(s) were shown"
                  % len(split_by_age(shown)[0]))
        # A constituency the card invented. Every other check governs where a
        # claim may come from; this one asks whether the party being quoted
        # was ever in the room.
        if voice_without_speakers(gen, shown):
            voiceless += 1
            print("    NO SPEAKER: speaks for fans with no post in the pool "
                  "| %s" % (gen.get("fan_voice") or "")[:70])
    con.commit()
    con.close()
    print("Wrote %d conversation cards to news_narratives (%d unchanged, "
          "not rewritten)" % (written, unchanged))
    # Zero has to be said out loud, or "no warnings" and "never checked" look
    # identical in the log.
    print("Checks: %d social leaks, %d cards naming an uncited outlet, "
          "%d cards ignoring their own publisher items, "
          "%d cards anchored on background while newer reporting was shown, "
          "%d masthead attributions across %d cards piling them up, "
          "%d cards speaking for fans who were never in the pool"
          % (leaks, unattributed, ignored, stale, namedrops, piled, voiceless))


if __name__ == "__main__":
    main()
