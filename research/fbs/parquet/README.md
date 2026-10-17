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
