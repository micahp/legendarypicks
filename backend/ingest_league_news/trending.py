"""Article-derived social queries (trending_queries)."""
from news_classifier import entities

def trending_queries(article_items, limit=12):
    """Search social for what the ARTICLES are about this run.

    Micah, 2026-08-10: "maybe we use topics in the articles we find in that run
    and search social media about them." This is the third leg of the corpus:
    seeded queries follow topics we named, open league queries sample broadly,
    and these follow the news itself — so chatter arrives on a story the day it
    breaks instead of only where a seed happens to sit.

    A topic must appear in TWO different articles to qualify: one headline is an
    event, two is a story.
    """
    from collections import Counter
    counts = Counter()
    for it in article_items:
        if it.get("source") == "bluesky":
            continue
        if (it.get("headline") or "").startswith("FETCH ERROR"):
            continue
        for e in entities(it.get("headline", "")):
            counts[e] += 1
    return [(None, e) for e, n in counts.most_common(limit * 3) if n >= 2][:limit]
