"""Command-line entry point for the league-news collector."""
import argparse

from news_classifier import classify

from .collect import (
    ALL_BLUESKY_QUERIES,
    OPEN_QUERIES,
    collect_bluesky,
    collect_news_search,
    collect_x,
    tag_conversations,
)
from .conversations import sync_conversations
from .fetch import (
    ESPN_NEWS,
    RSS_FEEDS,
    _ESPN_LEAGUE_HINT,
    collect_espn,
    collect_rss,
    fetch_espn_story,
)
from .store import reclassify_existing, repair_stored_text, upsert
from .trending import trending_queries

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues",
                    default="nfl,mlb,mls,ncaaf,nba,nhl,ufc,leaguescup,ligamx",
                    help="comma list of ESPN leagues to collect")
    ap.add_argument("--no-espn", action="store_true")
    ap.add_argument("--no-rss", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reclassify", action="store_true",
                    help="re-run the classifier over stored rows (no network)")
    ap.add_argument("--repair-text", action="store_true",
                    help="re-clean stored headline/body + normalize published (no network)")
    ap.add_argument("--sync-conversations", action="store_true",
                    help="write the built-in conversation defaults into the DB")
    ap.add_argument("--x-only", action="store_true",
                    help="collect only the X timelines (cheap, run hourly)")
    ap.add_argument("--ingest-story", default="",
                    help="ESPN article URL or id -> full body into news_items")
    args = ap.parse_args()

    if args.x_only:
        # X accounts post far faster than the nightly cadence: @UnderdogNFL
        # runs ~83 posts/day against a 20-post RSS window, so the feed only
        # holds about six hours and a daily run sees a quarter of it. This path
        # is 10 requests, no ESPN, no bluesky, no model — cheap enough to run
        # every few hours (2026-08-10).
        items = collect_x()
        errors = [i for i in items if i["headline"].startswith("FETCH ERROR")]
        for e in errors:
            print("  FETCH FAILURE: %s" % e["headline"][:100])
        for it in items:
            it.update(classify(it["headline"] + " " + it["body"],
                               it.get("league_hint")))
        print("  matched %d posts to a conversation" % tag_conversations(items))
        if args.dry_run:
            print("DRY RUN — %d x posts" % len(items))
            return
        print("x-only: collected %d, wrote %d new / %d refreshed"
              % (len(items), *upsert(items)))
        return

    if args.ingest_story:
        it = fetch_espn_story(args.ingest_story)
        if not it:
            print("no story found for %s" % args.ingest_story)
            return
        it.update(classify(it["headline"] + " " + it["body"], None))
        print("  %s [%s/%s] %d chars" % (it["headline"][:70], it["league"],
                                         it["layer"], len(it["body"])))
        if not args.dry_run:
            print("  wrote %d new, %d refreshed" % upsert([it]))
        return

    if args.sync_conversations:
        sync_conversations()
        return

    if args.reclassify:
        reclassify_existing(dry_run=args.dry_run)
        return

    if args.repair_text:
        repair_stored_text(dry_run=args.dry_run)
        return

    leagues = [l.strip() for l in args.leagues.split(",") if l.strip() in ESPN_NEWS]

    print("League news ingest — request budget per host (espn-request-budget doctrine):")
    print("  site.api.espn.com: %d  (host_budget=20, disk cache -> re-runs cost 0)" % len(leagues))
    if not args.no_rss:
        print("  deadspin.com: 1 | awfulannouncing.com: 1 | fansided.com: 1 | sbnation.com: 1")
    print("  api.bsky.app: %d (%d seeded + %d open)"
          % (len(ALL_BLUESKY_QUERIES) + len(OPEN_QUERIES),
             len(ALL_BLUESKY_QUERIES), len(OPEN_QUERIES)))

    all_items = []
    if not args.no_espn:
        all_items += collect_espn(leagues)
        print("  collected %d from espn" % sum(1 for i in all_items if i["source"].startswith("espn-")))
    if not args.no_rss:
        before = len(all_items)
        all_items += collect_rss()
        for name, _url in RSS_FEEDS:
            n = sum(1 for i in all_items[before:] if i["source"] == name)
            print("  collected %d from %s" % (n, name))
    before = len(all_items)
    trending = trending_queries(all_items)
    if trending:
        print("  article-derived social queries: %s"
              % ", ".join(q for _c, q in trending))
    all_items += collect_bluesky(trending)
    print("  collected %d from bluesky" % (len(all_items) - before))
    before = len(all_items)
    x_items = collect_x()
    all_items += x_items
    if x_items:
        print("  collected %d from x" % len(x_items))
    # collect_x_search() is deliberately NOT called. It works — one Google query
    # per seed returns ~95 on-topic X posts — but Google hands us the post text
    # and a redirect and nothing else: no author, no handle, no permalink. Trust
    # cannot be established even in principle, and on 2026-08-10 one of those
    # posts put "Inter Miami suspends Messi" on a card, contradicting publisher
    # items in the same pool. Micah: "we need trustworthy sources and can't
    # expect the model to fact check every post." Facts come from publishers.
    before = len(all_items)
    all_items += collect_news_search()
    print("  collected %d topic-matched articles from google news"
          % (len(all_items) - before))

    # A failed fetch is recorded as an item with an empty url, and upsert skips
    # exactly those rows — so a source that died looked identical to a source
    # with no news: no row, no error, no log line. Say it out loud instead
    # (2026-08-09: a conversation collected nothing and nothing reported it).
    errors = [i for i in all_items if i["headline"].startswith("FETCH ERROR")]
    if errors:
        from collections import Counter as _C
        print("  FETCH FAILURES (not stored, not counted above):")
        for src, n in _C(i["source"] for i in errors).most_common():
            first = next(i["headline"] for i in errors if i["source"] == src)
            print("    %-16s %d  %s" % (src, n, first[:90]))

    for it in all_items:
        src_league = it["source"].replace("espn-", "") if it["source"].startswith("espn-") else None
        if src_league in _ESPN_LEAGUE_HINT:
            src_league = _ESPN_LEAGUE_HINT[src_league]
        # An account that IS a league desk tells us the league outright.
        if it.get("league_hint"):
            src_league = it["league_hint"]
        cls = classify(it["headline"] + " " + it["body"], src_league)
        it.update(cls)

    print("  matched %d x posts to a conversation" % tag_conversations(all_items))

    if args.dry_run:
        from collections import Counter
        print("DRY RUN — %d items collected" % len(all_items))
        print("  by source:", dict(Counter(i["source"] for i in all_items)))
        print("  by layer:", dict(Counter(i["layer"] for i in all_items)))
        return

    inserted, updated = upsert(all_items)
    print("Wrote %d new, %d refreshed rows to news_items" % (inserted, updated))
