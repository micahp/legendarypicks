# MLS identity audit, v4 (2026-10-27)

Audit of the 815 cross-source MLS pairs (a FotMob key and an MLS Soccer key bound to one person).

Layers:
1. Date of birth from each publisher. The MLS page's printed date is read as every calendar reading that fits its
   shown age, with a one-day tolerance (the page's age is computed on the day it was rendered).
2. Identity status, kept separate from roster membership. A date disagreement alone is not an identity conflict.
3. External review for the 21 flagged pairs: official club, league, and reference records, with URLs and reasons.

Files:
- `pairs_v4.jsonl`: one row per pair (815), with both dates, the status layers, and the external review where it exists.
- `summary_v4.json`: counts by status, and the pairs whose status changed from the earlier audit.
- `audit_v4.py`: the classification script. It reads the earlier audit rows and needs no network access.
- `SHA256SUMS_v4`: checksums. Verify with `sha256sum -c SHA256SUMS_v4`.

Results: 556 verified by date, 240 matching one of two MLS readings, 15 date disagreements (none classed as an
identity conflict), 4 pairs with no MLS date. Confirmed bad identity links: 0.

Caveats: external findings come from search summaries, and not every page was opened. Ian Smith's FotMob date
conflicts with a search summary and needs a direct check.
