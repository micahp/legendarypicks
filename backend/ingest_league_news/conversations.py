"""Conversations: the dictated seed list, DB-backed loading, and the
derived query lists (CONVERSATIONS, CONVERSATION_QUERIES)."""
import os

# Conversations — Micah's dictated narratives ARE the seed (2026-08-07):
# "dodgers salary cap" and "mls relegation promotion" are the two canonical
# examples of what an important conversation looks like. Each conversation is
# its own card on the site and gets to breathe — we do NOT merge them into one
# league summary. Add new conversations HERE (e.g. NFL turf vs grass, 2026-08-07).
# `title` is the short human label; `seed` is the query that anchors it.
_DEFAULT_CONVERSATIONS = [
    {"id": "mlb-salary-cap", "league": "mlb", "title": "Salary cap debate",
     "seed": "dodgers salary cap"},
    {"id": "mls-pro-rel", "league": "mls", "title": "Promotion/relegation",
     "seed": "mls relegation promotion"},
    # Seeded 2026-08-09 from the FS1 booth during América–Portland (Leagues Cup):
    # MLS clubs are spending real transfer fees on Liga MX players, and the
    # broadcast's argument was that Leagues Cup makes that spend SAFER — you now
    # watch the player against both leagues' opposition on a regular basis — while
    # for a smaller Liga MX club the few million coming back can make or break a
    # season. Receipts in the window: Berterame Monterrey->Inter Miami ~$15M,
    # Bogusz Cruz Azul->Houston ~$10M.
    {"id": "mls-ligamx-spending", "league": "mls", "title": "Cross-border spending",
     "seed": "MLS Liga MX transfer"},
    {"id": "nfl-media-rights", "league": "nfl", "title": "Media rights talks",
     "seed": "nfl media rights deal"},
    {"id": "nfl-turf-grass", "league": "nfl", "title": "Turf vs. grass",
     "seed": "nfl turf grass"},
    {"id": "nba-expansion", "league": "nba", "title": "Expansion",
     "seed": "nba expansion"},
    # Added 2026-08-09 from evidence in the collected feed (Pablo Torre
    # bombshell + Stephen A. "banishment" call): a live, recurring NBA
    # conversation distinct from expansion. Seeded only because 3+ collected
    # items recur on it — not a dictated narrative this time.
    {"id": "nba-kawhi-cap", "league": "nba", "title": "Kawhi salary-cap case",
     "seed": "Kawhi Leonard salary cap circumvention Clippers"},
    {"id": "nhl-salary-cap", "league": "nhl", "title": "Salary cap",
     "seed": "nhl salary cap"},
    {"id": "ufc-title-fight", "league": "ufc", "title": "Title picture",
     "seed": "ufc title fight"},
    {"id": "ncaaf-realignment", "league": "ncaaf", "title": "Realignment",
     "seed": "ncaaf conference realignment"},
    {"id": "esports-worlds", "league": "esports", "title": "Worlds",
     "seed": "esports worlds"},
    {"id": "esports-valorant", "league": "esports", "title": "Valorant",
     "seed": "valorant champions"},
]

def load_conversations():
    """Conversations come from `news_conversations`, not from this file.

    A topic must not need a code edit and a deploy (Micah, 2026-08-10) — and
    the DB rows are also what the discovery pass learns from, since an approved
    topic is a positive label (see discover_topics.py). The list above is the
    seed data for a fresh DB and the fallback when the table is empty or
    unreachable; `--sync-conversations` writes it in.
    """
    try:
        import sqlite3
        db_path = os.environ.get("LP_DB_PATH") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "picks.db")
        con = sqlite3.connect(db_path)
        rows = con.execute(
            """SELECT id, league, title, seed FROM news_conversations
               WHERE active=1 ORDER BY created_at""").fetchall()
        con.close()
        if rows:
            return [{"id": r[0], "league": r[1], "title": r[2], "seed": r[3]}
                    for r in rows]
    except Exception:
        pass
    return list(_DEFAULT_CONVERSATIONS)

def sync_conversations():
    """Write the built-in defaults into news_conversations (idempotent)."""
    import sqlite3
    from _core import _init_db as _core_init_db
    _core_init_db()
    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "picks.db")
    con = sqlite3.connect(db_path)
    n = 0
    for c in _DEFAULT_CONVERSATIONS:
        cur = con.execute(
            """INSERT INTO news_conversations(id, league, title, seed, origin)
               VALUES (?,?,?,?, 'dictated') ON CONFLICT(id) DO NOTHING""",
            (c["id"], c["league"], c["title"], c["seed"]))
        n += cur.rowcount
    con.commit()
    total = con.execute("SELECT count(*) FROM news_conversations WHERE active=1").fetchone()[0]
    con.close()
    print("Synced %d new conversations (%d active)" % (n, total))

CONVERSATIONS = load_conversations()

# Generic texture dimensions: the ways a story shows up in fans' lives. Any
# conversation's seed is searched against these to find the ADJACENT
# conversation — the packed stadium, the lower-division energy, the highlight
# clip, the player quote — because those posts carry the story's keywords too
# (Micah, 2026-08-07). This list is sport-agnostic; it is not per-league
# hardcoding.
_TEXTURE_DIMENSIONS = [
    "stadium",
    "attendance",
    "fans",
    "lower division",
    "highlight",
]

# Each (conversation, dimension) pair is its own bluesky query, tagged with the
# conversation so collected items can be attributed back to it.
def _conversation_queries() -> list:
    out = []
    for conv in CONVERSATIONS:
        out.append((conv["id"], conv["seed"]))
        for dim in _TEXTURE_DIMENSIONS:
            out.append((conv["id"], "%s %s" % (conv["seed"], dim)))
    return out

CONVERSATION_QUERIES = _conversation_queries()
