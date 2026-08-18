"""URL normalization and topic-word analysis for narrative ingestion."""

import re

from .constants import _GENERIC_WORDS, _MIN_TOPIC_LEN, _STOPWORDS, _TIE_ALARM


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