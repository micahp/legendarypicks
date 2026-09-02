"""Entry point for `python -m ingest_league_narratives`.

The 2026-08-18 split turned `ingest_league_narratives.py` into a package, and
`scripts/news-collect.sh` kept calling the deleted file. Every news run since has
logged:

    can't open file 'ingest_league_narratives.py': [Errno 2] No such file or directory
    WARN: ingest_league_narratives.py exited 2 after 0s

so the conversation-card step has produced nothing since the split. Found 2026-08-19.

Same trap as `bovada_scraper`: the package's `if __name__ == "__main__"` guard in
`__init__.py` only fires for `python path/to/__init__.py`, never for `python -m package`.
"""
from .cli import main

raise SystemExit(main())
