# Madden publication dates and in-season updates (2026-10-23)

Question: is each archive rating a pregame value for the NFL season it covers? Dataset label
L is the Madden title year and covers NFL season L-1 (Madden 26 covers 2025), so the rating
must be public before season L-1 kicks off. The archive itself carries no publication or
snapshot timestamp, so the answer has to come from outside the data and from tests against it.

Sources: "opened" means the page was fetched and read. "snippet" means only a search result
was seen and the page was not read.

## 1. Release dates by dataset label

| Label | Title | Release | Source | Status |
|---|---|---|---|---|
| 2000 | Madden NFL 2000 | Aug 31, 1999 | Wikipedia, opened | dated; before NFL kickoff |
| 2005 | Madden NFL 2005 | 2004, no day ("ahead of the 2004 NFL season") | Wikipedia, opened | year only |
| 2009 | Madden NFL 09 | Aug 12, 2008 | Wikipedia, opened | dated |
| 2010 | Madden NFL 10 | Aug 14, 2009 | Wikipedia, opened | dated |
| 2011 | Madden NFL 11 | Jul 27, 2010 (originally Aug 10) | Wikipedia, opened | dated |
| 2012 | Madden NFL 12 | Aug 25, 2011 | Wikipedia, opened | dated |
| 2013 | Madden NFL 13 | Aug 28, 2012 | Wikipedia, opened | dated |
| 2014 | Madden NFL 25 (2013 video game) | Aug 27, 2013 | Wikipedia, opened | dated; title-to-label mapping by overlap (see below) |
| 2015 | Madden NFL 15 | Aug 26, 2014 | Wikipedia, opened | dated |
| 2016 | Madden NFL 16 | Aug 25, 2015 | Wikipedia, opened | dated |
| 2017 | Madden NFL 17 | Aug 23, 2016 | Wikipedia, opened | dated |
| 2018 | Madden NFL 18 | Aug 25, 2017 | Wikipedia, opened | dated |
| 2019 | Madden NFL 19 | Aug 10, 2018 | Wikipedia, opened | dated |
| 2020 | Madden NFL 20 | Aug 2, 2019 | Wikipedia, opened | dated |
| 2021 | Madden NFL 21 | Aug 28, 2020 | Wikipedia, opened | dated |
| 2022 | Madden NFL 22 | not stated | Wikipedia, opened | unresolved |
| 2023 | Madden NFL 23 | not stated (announced Jun 1, 2022) | Wikipedia, opened | unresolved |
| 2024 | Madden NFL 24 | not stated | Wikipedia, opened | unresolved |
| 2025 | Madden NFL 25 (2024 video game) | "early September 2024", no day | Wikipedia, opened | **conflict**: a snippet gives Aug 16, 2024 from a mislabelled page; early September may fall on or after the 2024 kickoff |
| 2026 | Madden NFL 26 | Aug 14, 2025 (Deluxe early access Aug 7) | Wikipedia, opened; Deluxe date from snippet | dated |
| 2027 | Madden NFL 27 | Aug 13, 2026 | Wikipedia infobox, opened; snippet from a pre-launch article | dated; launch already happened, post-launch confirmation not checked |
| 1992-1999 (except 2000) | Madden NFL 92-99 | no day on the opened page | Wikipedia, opened | unresolved. A repost snippet gives Nov 19, 1993 for '94, Nov 18, 1994 for '95, Nov 10, 1995 for '96 and Sep 6, 1996 for '97. Those repost dates are unverified; if correct, the first three fall after their season's kickoff |

Title and label: Wikipedia names two titles "25" (2013 and 2024). The archive label 2014 matches
League Station's `madden-25-2013.csv` by overlap (54 matches against 43 for label 2013), so the
2013 release is label 2014.

Ratings reveal: the Madden 26 ratings were revealed in staggered waves in the days before launch.
This is from SI and Insider Gaming snippets; the pages were not opened. The reveal does not
establish when a value was fixed or whether it changed later.

## 2. Did ratings change after launch?

- **Madden 26 (season 2025): yes.** Operation Sports, opened: "Madden ratings changed throughout the
  NFL season." Its last update "focused heavily on Super Bowl LX participants," and it marks the end
  of the ratings cycle. The page gives no weekly schedule. ESPN's "Week 18 ratings update" article
  returned HTTP 403 and was not read.
- **Madden 27 (season 2026): yes.** Yahoo Sports, opened, dated Friday Sep 18, 2026. It lists 29
  overall changes from the previous value, for example T.J. Watt 93 to 96, and Drake Maye 92 to 89.
  The page does not say which NFL week the update followed.

## 3. Test: does the archive's 2027 row reflect the Sep 18 update?

`scripts/madden/publication_update_test.py` compares the archive's 2027 OVR for the 29 players in the
Yahoo list with the old and new values.

| Archive 2027 OVR matches | Players |
|---|---|
| old (launch) value | 18 |
| new (post-update) value | 0 |
| neither | 6 |
| absent from the 2027 release | 5 (T.J. Watt, Kenneth Walker, D'Andre Swift, Kevin Byard III, James Cook III) |

Reading: the archive does not hold the post-Sep 18 values for these players. The six "neither"
values could be later updates that Yahoo did not list, or source differences. The test does not
prove that the archive is a launch snapshot, because the six unexplained values show that at least
some changes are not explained by a single old-or-new pattern. The five absent players are a
coverage gap in the 2027 release, reported in the QA checkpoint.

## 4. League Station test (OVR agreement with the archive, by label)

From `scripts/madden/crosscheck_leaguestation.py` and the label-offset check.

- Labels 2006-2015 and 2017-2025: exact OVR agreement at the matching label is 0.74-1.00. Most
  are 0.85-0.95.
- Label 2010: 0.07 at its own label, 0.03 at -1 and 0.05 at +1. No label offset explains it, so it
  is an unexplained archive defect (also a presence collapse in the audit).
- Label 2026: 0.40 at its own label and 0.78 against the archive's label 2027 (36 pairs).
- Label 2027: 0.57 at its own label (40 pairs).

League Station's README claims its free preview shows the launch roster. That claim is not
verified. If it holds, the disagreement for 2026 and 2027 says the archive values differ from launch,
which conflicts with section 3. If the preview is itself updated, the test says nothing about the
archive. The two tests cannot be combined until one of those sources is checked against a known
launch value.

## 5. Leakage-safe rule for the training schema

A rating row with label L (season S = L-1) is pregame-eligible for season S only if both hold:

1. Its release date is before season S kickoff. The conservative check is before Sep 1 of S. This
   is an approximation; the exact kickoff dates are not sourced here.
2. Its snapshot is verified as a launch-day value.

Condition 2 is not established for any release. The schema therefore starts every release at
`snapshot_status = unverified`, which excludes all of them from pregame training. Releases with no
or conflicting dates are also excluded: 1992-1999 (except 2000), 2005 (no day), 2022-2025, and any
release whose date is unverified.

## 6. Open items

- Settle the Madden 25 (2024) date conflict: "early September 2024" against Aug 16, 2024.
- Find dates for 1992-1999, 2005 and 2022-2024 from a second source, preferably EA.
- Verify the snapshot status per release with a test that uses known launch values for the same
  players. League Station's preview is the only launch-value source in the workspace and is not yet
  verified against one.
- Explain the 2010 OVR anomaly (no label offset fits) and the 2026 and 2027 disagreement.
- Read the ESPN Week 18 update article if it becomes reachable; it was not read.
