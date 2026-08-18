"""topic_words helpers from the narrative pipeline."""
import re
import json
import os
import sys
import sqlite3
import datetime
import hashlib
import argparse


_MIN_TOPIC_LEN = 2   # was 4, which threw away the word naming the conversation

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

_TIE_ALARM = 8             # candidates tied at the top score = the seed did nothing

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

def _squash_title(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())
