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

## Revision 2026-10-28

Changes made after the review of 109467c8. The counts did not change.

- **Source errors are named, not searched for.** `audit_v4.py` used to call a disagreement a source error when its
  conclusion text contained the word "error". Each reviewed pair now names the publisher whose record is wrong
  (`source_error_publisher`: `mls` for 58549, 58598, 58670, 59000; `fotmob` for 71285). Regenerating from the stored
  v2 evidence gives the same 815 statuses, with the same five source errors.
- **Every cited URL has an access record.** `external_access_2026-10-28.json` lists all 33 unique URLs with how each was
  read (WebFetch, the audit's MLS helper, or FotMob's API), the date text the page gives, and whether it matches the
  review. 32 were inspected. One ESPN page (Sargeant, 58965) returned no content on two attempts, so the review's ESPN
  claim is not confirmed. One Sporting KC page (Mosquera, 59000) failed once on DNS and then succeeded.
- **Ian Smith's FotMob date is checked directly.** FotMob's own player API gives 26 Jul 2002, the value stored in the
  audit. The club page and MLS give 16 Jul. The disagreement stays biographical, and the link is kept.
- **Tracked categories.** `tracking_2026-10-28.json`, from `track_v4.py`, lists every person by the evidence behind the
  record: 556 date agreements, 240 date-order ambiguities, 10 biographical disagreements, 5 source errors, 4 with no MLS
  date, and 225 single-source people (one publisher key in the snapshot membership). Nothing is marked independently
  verified. The 225 have no cross-check at all.
- **MLS structured birth date: none found.** The public MLS player pages carry the date only as printed text
  (`<span>5.7.2004 (22)</span>` under a "Date of Birth" heading). The roster widgets and the two pages checked
  (Cabral Carter, Nolan Miller) have no JSON-LD, no data attribute, and no birth key. This covers one club roster and
  two players. Carter and Miller's Opta confirmation is the reviewer's report; no Opta URL is in this bundle, and it
  was not checked here.
- **Snapshot shadow outputs.** `../mls-snapshot-shadow-2026-10-28/` holds the 2026-10-28 squads, the shadow report, and
  its log. The code and the write-up are on the `feat/mls-snapshot-2026-10-27` branch.

Earlier caveats still apply. An external check of a date is only as strong as the page read. The MLS-printed dates are
checked against the shown age, and the audit's date-order readings stay ambiguous where the age cannot separate them.
