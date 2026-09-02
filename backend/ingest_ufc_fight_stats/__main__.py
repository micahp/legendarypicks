"""Entry point for `python -m ingest_ufc_fight_stats`.

The 08-18 split left an `if __name__ == "__main__": main()` block in
`__init__.py`. That block does not fire for `-m`: python imports the package and
then looks for a `__main__` submodule, which did not exist, so the package was
not runnable at all. `audit_league_stats` had the identical hole and it cost two
releases, because the caller that hit it swallowed the error instead of
reporting it.

Nothing invokes this with `-m` today. It exists so that when something does, it
works rather than failing with a message about packages not being executable.
"""
import sys

from . import main

sys.exit(main())
