"""Entry point for `python -m bovada_scraper`.

This exists because the 2026-08-18 split turned `bovada_scraper.py` into a package and
**three systemd units kept pointing at the deleted file**:

    legendarypicks-props.service        all --ingest      every 30 min
    legendarypicks-props-prod.service   all --ingest      every 30 min
    legendarypicks-mlb-capture.service  mlb --capture

Every run since the split failed with `can't open file
'/root/legendarypicks/backend/bovada_scraper.py': [Errno 2] No such file or directory`, so
props stopped refreshing on both databases and nothing surfaced it except a red unit nobody
was reading. Found 2026-08-19 while chasing a different report.

`__init__.py` carries an `if __name__ == "__main__": main()` guard, which reads like an
entry point and is not one: that guard only fires for `python path/to/__init__.py`, never
for `python -m package`. Hence this file, which is the form that actually works.
"""
from .cli import main

raise SystemExit(main())
