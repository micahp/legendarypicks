"""No database, or anything derived from one, may reach the backend build context.

This has now failed twice, the same way both times: the exclusion patterns looked
correct while a backup filename slipped past them.

  2026-08-04  `*.bak` at the context root never matched `data/picks.db.bak-...`,
              because `*` does not cross a path separator. Image hit 7.45GB.
  2026-08-11  `data/*.bak*` and `data/*.db` both missed
              `data/picks.db.pre-fantasy-null-20260805T114704284808` -- written by
              a repair script with no `.bak` suffix and a name ending in a digit.
              0.93GB reached the context again.

Reviewing the pattern list by eye is what failed. This asserts the OUTCOME
instead: take every real file in `backend/data` and require the patterns to
exclude it. A new backup naming convention that nobody remembers to add a
pattern for fails here rather than in a 7GB image.

docker-compose bind-mounts ./backend/data over /app/data at runtime, so excluding
every database from the image is correct -- the live DB is never served from it.
"""
import fnmatch
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# Anything matching these IS a database or derived from one, and must be excluded.
DB_SHAPED = ("picks.db", "picks.dev.db", ".db", ".bak", ".sqlite")


def _patterns():
    with open(os.path.join(HERE, ".dockerignore")) as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


def _excluded(rel, patterns):
    """Go's filepath.Match, as Docker applies it: `*` does not cross `/`, so a
    pattern only matches a path with the same number of separators."""
    for p in patterns:
        if fnmatch.fnmatch(rel, p) and rel.count("/") == p.count("/"):
            return p
    return None


def _db_shaped(name):
    return any(k in name for k in DB_SHAPED)


def test_no_database_file_reaches_the_build_context():
    if not os.path.isdir(DATA):
        return  # nothing to check in a bare checkout
    patterns = _patterns()
    leaked = []
    for name in sorted(os.listdir(DATA)):
        rel = "data/" + name
        if not os.path.isfile(os.path.join(DATA, name)):
            continue
        if not _db_shaped(name):
            continue
        if _excluded(rel, patterns) is None:
            size_mb = os.path.getsize(os.path.join(DATA, name)) / 1e6
            leaked.append("%s (%.0f MB)" % (rel, size_mb))
    assert not leaked, (
        "these database files are NOT excluded and would be baked into the "
        "backend image:\n  " + "\n  ".join(leaked) +
        "\nAdd a pattern to backend/.dockerignore that matches the NAME "
        "(e.g. data/picks.db*), not a suffix."
    )


def test_the_live_databases_are_excluded():
    """The specific regression that started all of this."""
    patterns = _patterns()
    for rel in ("data/picks.db", "data/picks.dev.db"):
        assert _excluded(rel, patterns) is not None, rel


def test_a_suffixless_backup_shape_is_covered():
    """The 2026-08-11 shape: no `.bak`, name ends in a digit. Guards the fix
    even on a checkout where no such file happens to exist right now."""
    patterns = _patterns()
    for rel in ("data/picks.db.pre-fantasy-null-20260805T114704284808",
                "data/picks.dev.db.pre-storytime-20260811T162917Z.bak",
                "data/picks.db.pre-anything-else"):
        assert _excluded(rel, patterns) is not None, rel
