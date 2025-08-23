### [Decision 1]: Site-wide “hype” redesign and ESPN-style Scores UX
**Timestamp (UTC):** 2025-08-23T00:00:00Z
**Scope:** `styles/globals.css`, `tailwind.config.js`, `components/Layout.tsx`, `pages/_app.tsx`, `pages/index.tsx`, `pages/scores.tsx`, `components/Scores/{DayStrip.tsx,CalendarPopover.tsx,ProviderToggle.tsx,GameCard.tsx,States.tsx}`, `components/MomentGallery.tsx`, `components/ContestBrowser.tsx`
**Change Summary:** Introduced a cohesive dark theme with brand accents, a new global layout (sticky header/footer), and ESPN-inspired Scores UI (day strip, calendar popover, provider toggle, cards, and robust loading/error/empty states). Updated Home hero and sections to a bold, retail-grade style and restyled the Moments Gallery and Contests to match. Avoided nested card patterns by flattening section wrappers.
**Rationale:** The previous UI mixed light and dark styles and lacked cohesive hierarchy, causing readability and brand fragmentation. A premium, high-contrast aesthetic improves scannability and aligns with sports/collectibles expectations (retail + broadcast). ESPN-style density fits scoreboard content; Nike/Flight Club conventions guide hero and merchandising moments; Top Shot informs crypto-native elements. Null-safe calendar and defensive states address prior interaction errors and 5xx propagation. Centralized layout and tokens accelerate future iteration and reduce duplication.
**Alternatives Considered:**
  - Keep legacy styles — rejected due to visual inconsistency and limited extensibility.
  - CSS-in-JS theme overhaul (emotion/stitches) — rejected for bundle/runtime overhead; Tailwind+tokens suffices.
  - Heavy animation-first approach — deferred; will add tasteful micro-interactions post-layout stabilization.
**Trade-offs / Risks:**
  - Dark theme requires careful contrast checks (a11y); risk of insufficient contrast on secondary text.
  - More components increases maintenance surface; mitigated via shared tokens and `panel` utility.
  - Calendar popover positioning simplified to avoid ref races; fewer fancy placements.
  - Provider toggle surfaces choice to users; may invite questions without docs.
**Follow-ups / TODOs:**
  - Add motion system (hover/press ramps, hero reveal) and define permissible animation budget.
  - Typography scale pass (H1–H6, lead, fine print) and spacing audit across pages.
  - A11y: improve focus rings, color contrast audits, and keyboard traps in popover.
  - Content slots: hero carousel or featured contests; dynamic badges (LIVE/FINAL) accents.
  - Document design tokens and usage in `/docs/design.md`.
**Source Prompt(s):**
  - “go ahead and do the redesign. let's redesign the whole app to be a hype beast sports design wit these images in mind from espn”
  - “now let's move on to rest of fite. design should be a mix of @https://nike.com , @https://flighclub.com , @https://nbatopshot.com,  and @https://espn.com”


