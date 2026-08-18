"""Persistence: upsert collected items, reclassify, repair stored text."""
import os

from news_classifier import classify

from .fetch import _clean, _iso

def upsert(items, dry_run=False):
    if not items:
        return 0, 0
    import sqlite3
    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "picks.db")
    # Single source of truth for schema: _core's _init_db (creates news_items
    # + every other table idempotently). Fall back to the news table alone if
    # importing _core is impossible in this environment.
    try:
        from _core import _init_db as _core_init_db
        _core_init_db()
    except Exception:
        con = sqlite3.connect(db_path)
        con.execute("""
        CREATE TABLE IF NOT EXISTS news_items(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          league TEXT NOT NULL,
          layer TEXT NOT NULL,
          source TEXT NOT NULL,
          headline TEXT NOT NULL,
          body TEXT NOT NULL DEFAULT '',
          url TEXT NOT NULL UNIQUE,
          published TEXT NOT NULL DEFAULT '',
          key_player TEXT,
          conv_id TEXT,
          first_seen TEXT NOT NULL DEFAULT (datetime('now')));
        """)
        con.commit()
        con.close()
    con = sqlite3.connect(db_path)
    inserted = updated = 0
    rows_before = con.execute("SELECT count(*) FROM news_items").fetchone()[0]
    written = 0
    for it in items:
        if not it.get("url"):
            continue
        if dry_run:
            continue
        before = con.total_changes  # noqa: F841 (kept for the delta below)
        con.execute(
            """INSERT INTO news_items(league, layer, source, headline, body, url, published, key_player, conv_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET
                 league=excluded.league, headline=excluded.headline, body=excluded.body,
                 published=excluded.published,
                 layer=excluded.layer, key_player=excluded.key_player, source=excluded.source,
                 conv_id=excluded.conv_id""",
            (it["league"], it["layer"], it["source"], it["headline"], it["body"],
             it["url"], it["published"], it.get("key_player"), it.get("conv_id")),
        )
        written += 1
        # NOT total_changes: SQLite counts an ON CONFLICT DO UPDATE as one
        # change exactly like an insert, so every run reported "N new, 0
        # refreshed" — including a re-run seconds later that inserted nothing
        # (2026-08-10). A count of the table either side is the honest measure;
        # anything else silently turns "we collected nothing new" into "337 new".
        pass
    con.commit()
    rows_after = con.execute("SELECT count(*) FROM news_items").fetchone()[0]
    con.close()
    inserted = rows_after - rows_before
    updated = written - inserted
    return inserted, updated

def reclassify_existing(dry_run=False):
    """Re-run the classifier over stored rows (headline+body) and update
    league/layer/key_player — items that fell out of the live feeds keep their
    old classification otherwise (e.g. the Giants-broadcaster MLB fix)."""
    import sqlite3
    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "picks.db")
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT id, headline, body, source FROM news_items WHERE url != ''").fetchall()
    changed = 0
    for rid, headline, body, source in rows:
        src_league = source.replace("espn-", "") if source.startswith("espn-") else None
        cls = classify((headline or "") + " " + (body or ""), src_league)
        if not dry_run:
            cur = con.execute(
                "UPDATE news_items SET league=?, layer=?, key_player=? WHERE id=?",
                (cls["league"], cls["layer"], cls.get("key_player"), rid))
            changed += cur.rowcount
        else:
            changed += 1
    con.commit()
    con.close()
    print("Reclassified %d rows%s" % (changed, " (dry run)" if dry_run else ""))

def repair_stored_text(dry_run=False):
    """Re-clean headline/body and re-normalize published for stored rows.

    The collector now cleans on the way in; rows collected before that carry
    the raw publisher text (`Purdue&#8217;s`) and mixed date shapes (RFC 822
    from three feeds, ISO from the rest), and `published` is sorted as TEXT —
    so "Thu, 06 Aug..." outranked every ISO row regardless of date. No network.
    """
    import sqlite3
    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "picks.db")
    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT id, headline, body, published FROM news_items").fetchall()
    text_fixed = date_fixed = 0
    for rid, headline, body, published in rows:
        h, b, p = _clean(headline), _clean(body), _iso(published)
        if h != (headline or "") or b != (body or ""):
            text_fixed += 1
        if p != (published or ""):
            date_fixed += 1
        if not dry_run and (h != headline or b != body or p != published):
            con.execute(
                "UPDATE news_items SET headline=?, body=?, published=? WHERE id=?",
                (h, b, p, rid))
    con.commit()
    con.close()
    print("Repaired text on %d rows, dates on %d rows (%d scanned)%s"
          % (text_fixed, date_fixed, len(rows), " (dry run)" if dry_run else ""))
