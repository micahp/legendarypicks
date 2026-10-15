# UFCalendar design reference

**Reference inspected:** [Summer Onley vs. Alivia Bierley, DWCS 95](https://www.ufcalendar.com/events/ufc-dwcs-95-2026-10-06/summer-onley-vs-alivia-bierley)
**Inspection date:** 2026-10-15
**Purpose:** Capture the visual and information-design choices worth adapting to Legendary Picks.

## Overall character

The page feels like an editorial fight report presented through a sports-data interface. It combines a strong event poster hierarchy with compact statistical detail. The layout stays readable because it uses clear surfaces, restrained color, distinct section headings, and tabs to divide different kinds of information.

The useful idea for Legendary Picks is the system behind the page: use typography and structure to establish hierarchy, then reserve color for meaning. Adapt that system to LP's existing brand and sport-specific needs rather than copying UFCalendar's identity.

## Typography

The live page's computed styles and loaded font faces were inspected in Chromium.

| Role | Typeface and observed treatment | Use |
| --- | --- | --- |
| Body, navigation, and explanatory copy | **Inter**, with system sans-serif fallbacks. Body copy is 16px. | Readable paragraphs, navigation, descriptions, and supporting labels. |
| Display headings, fighter names, and prominent scores | **Bebas Neue**, with Impact and sans-serif fallbacks. Section headings are about 22px, regular weight, tight line height, and lightly tracked. Fighter names are about 24px on mobile and 30px on desktop. | A condensed, poster-like voice for high-priority sports information. |
| Small labels | Inter, usually around 11px, uppercase, with increased tracking. | Column labels, table headings, and compact metadata. |
| Supporting hints | Inter, around 12px in muted gray. | Short context that should not compete with values. |

The header wordmark also uses Bebas Neue, approximately 24px with letter spacing. Scores use tabular numerals where alignment matters. Other font files are present on the site, but this page's displayed content was verified as using Inter and Bebas Neue; avoid treating other loaded fonts as part of this page's design without checking their use.

## Color and meaning

The page uses a warm near-white canvas with white cards and dark text. Color is concentrated in meaningful accents:

| Observed value | Approximate hex | Role |
| --- | --- | --- |
| `rgb(250, 250, 247)` | `#FAFAF7` | Main page background. |
| `rgb(10, 10, 11)` | `#0A0A0B` | Primary text. |
| `rgb(163, 5, 0)` | `#A30500` | Red corner and red emphasis. |
| `rgb(29, 85, 160)` | `#1D55A0` | Blue corner and blue emphasis. |
| `rgb(239, 237, 234)` | `#EFEDEA` | Soft inset surfaces, including judge scorecards. |
| `rgb(214, 212, 207)` | `#D6D4CF` | Fine card borders and separators. |

Red and blue consistently identify the two corners in labels, portraits, score values, and stat bars. Green is used sparingly for a positive result or successful prediction. Most content remains neutral, so these accents remain legible and meaningful.

## Cards and surfaces

- Main content cards are white, with a subtle gray border, a 16px corner radius, and a restrained shadow. The observed shadow is `0 1px 2px rgba(10,10,11,.04), 0 18px 40px -24px rgba(10,10,11,.22)`.
- Nested or secondary panels use a soft neutral fill instead of another prominent shadow. This provides depth without making every information group look like a separate floating card.
- Borders and small dividers separate adjacent items where a full card would be too heavy.
- Statuses and short outcomes use compact pills. Their color reinforces status but does not become a large block of saturated color.
- A vertical red rule sets off the lead result summary, giving it emphasis without another large decorative element.

## Judge scorecards

The judge scorecards are a strong example of grouping related data into its own visual unit. Each judge gets an individual warm-gray panel inside the larger scorecard section. On desktop, the three panels sit in a row.

- Each panel has a 12px radius, compact padding, and no pronounced shadow.
- The judge's name sits in a header area, divided from the score rows by a thin rule.
- Small uppercase labels identify the round or score columns.
- Red and blue corner labels and point totals keep the two fighters easy to track across rows.
- Round rows stay compact; the final accumulated score is larger and uses the display face and corner color.

For LP, apply this treatment when a group of values belongs together as one self-contained record—for example, a judge card or a grouped result breakdown. Give the group a softly tinted background, keep its internal separators thin, and reserve the strongest text treatment for the total or outcome.

## Information hierarchy and separation

The page avoids presenting the whole event as one long undifferentiated feed:

1. **Matchup and result hero:** fighter portraits and names flank a centered result summary. Round and time, judge decision scores, division, scheduled rounds, and a full-card link are grouped with the result. Date and venue sit below a divider.
2. **Result summary:** a short editorial explanation receives a colored side rule, separating the main takeaway from supporting detail.
3. **Navigation by subject:** tabs divide the fight overview, rounds, scorecards, odds, and pre-fight information. A red underline marks the active tab.
4. **Within-tab sections:** result, prediction, odds, fight stats, tale of the tape, target/position breakdowns, round-by-round details, and judges' cards each receive a clear heading and a bounded content area.
5. **Secondary utilities:** the AI prompt and other supporting material have their own bordered panel and separated rows, so they do not interrupt the result hierarchy.

Section headings use a small red slash accent before uppercase display text. This creates a repeated landmark without requiring a different color or oversized heading for every section.

## Statistics and comparisons

Fight-stat comparisons mirror the two fighters' colors. A centered category label sits between the red and blue sides; each side has a value and a horizontal bar. The track uses a pale tint, with a stronger corner-color fill showing the relative amount. Small helper text explains scale or context where needed.

This is useful when the user needs to compare two participants quickly. Keep labels and values visible even when bars are present, and make the scale understandable rather than relying on bar length alone.

## Navigation and responsive behavior

- The top navigation is sticky and uses a translucent surface with backdrop blur.
- Desktop navigation has room for direct links; compact layouts reduce the header to the logo, search/account controls, and a menu button.
- On mobile, the verdict is centered before the fighter blocks stack. Date and venue follow below a divider.
- Tabs and section groupings preserve the same information hierarchy across the page instead of shrinking a wide desktop arrangement into a dense column.

## Adaptation notes for Legendary Picks

- Preserve LP's existing brand and sports vocabulary; borrow the hierarchy, spacing, surface contrast, and information grouping.
- Use a display face only for high-value headings, player/team names, and key figures. Keep body copy and labels in a highly readable sans-serif.
- Give related stats or outcomes a shared softly tinted panel when that makes the grouping clearer. Judge cards are the clearest reference example.
- Let neutral surfaces carry most of the page. Use accent colors consistently for participant identity, active navigation, and result status.
- Separate information by user question—prediction, market/line, actual result, and grading—so each section is quickly scannable.
- Keep labels close to the values they describe, use thin dividers inside dense groups, and avoid adding a new floating card for every row.
- Use bars for direct comparisons, with numeric values and a clear scale alongside them.
- Use responsive stacking to preserve reading order and comparison context on mobile.

## Evidence and limits

The typography, background colors, radii, card shadow, and judge-panel background were read from the rendered page's browser-computed styles. The page was rendered with Chromium after the browser binary was installed. The visual descriptions summarize the referenced event page; they are design observations, not a claim that every UFCalendar page uses identical components.

Reference page: [ufcalendar.com event page](https://www.ufcalendar.com/events/ufc-dwcs-95-2026-10-06/summer-onley-vs-alivia-bierley). Its CSS is served from the site's static Next.js assets; computed browser styles were used as the source for the values above.
