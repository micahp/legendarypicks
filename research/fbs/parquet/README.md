# FBS parquet cache

Downloaded SportsDataverse season Parquet releases, fetched by
`backend/fetch_fbs_parquet.py`. These are a **cache, not an artifact**: they are
re-downloadable from public URLs with no API key, and they are not committed to
git. `git status` shows them as untracked; that is expected.

To refresh or extend:

    /root/legendarypicks/backend/venv/bin/python backend/fetch_fbs_parquet.py \
        --dir research/fbs/parquet --seasons 2022,2023,2024,2025,2026

Why the Parquet releases rather than the CFBD API: the shared CFBD key on this
box exhausted its monthly quota on 2026-10-16 (HTTP 429
`{"message":"Monthly call quota exceeded."}` on every endpoint). The releases
are the bulk path and need no key at all.

Files here are large (386 MB for 2022-2026 across three releases). The audit
scripts read only the columns they need, so a partial download is not usable;
`fetch_fbs_parquet.py` verifies each file's size against the release asset and
reports a mismatch rather than silently using a truncated file.

## What was measured from these files, 2026-10-17

The audits that read this cache:

- `AUDIT-FBS-DATA-20261017.md` -- what the releases carry, per season and per column
- `AUDIT-FBS-RECONCILE-20261017.md` -- do the releases agree with our stored results

Key numbers, so they are not lost if the cache is deleted and re-fetched:

- ESPN play-by-play 2026: 455 games, 78,642 plays; 85.1% of our 323 linked
  prop fixtures
- ESPN player box 2026: 455 games, 39,913 rows, 11,887 athletes
- stats.ncaa.org play-by-play (`cfbfastR`) 2026: 795 games, 149,246 plays
- ESPN game rosters 2026: 447 games, 100,682 rows
- ESPN team box 2026: 455 games, 910 rows
- Every release above covers season 2026; the releases before that carry
  2004-2025, so a multi-season backtest is possible from the releases even
  though our props are 2026-only.
