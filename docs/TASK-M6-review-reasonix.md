# TASK — M6 DESIGN REVIEW (adversarial, read-only)

**For:** reasonix. `docs/ODDS-CAPTURE-DESIGN.md` will drive M6-impl (the odds-capture
build — the biggest bettor-grade lever). Stress-test the design NOW so the
implementation isn't built on a flawed foundation. READ-ONLY — produce a review,
do not change the design doc or any code.

## Review for (be specific, cite doc line/section):
1. **Math correctness** — §7 EV/CLV/calibration formulas:
   - `american_to_decimal`, implied prob, de-vig (two-sided Over/Under), EV, CLV.
     Any sign errors, vig-double-counting, or edge cases (pick'em ±100, heavy
     favorites, push at the line)?
2. **De-vig assumption** — is dividing out by `p_over + p_under` valid for the props
   we care about, or does Bovada's vig split asymmetrically (favorite/longshot bias)?
3. **Schema sufficiency** — does `props.odds` + `prop_odds_snapshots` actually capture
   what M7 (EV/CLV/calibration) needs, or is something missing (e.g. the bet *side's*
   odds vs both sides, line-movement vs odds-movement)?
4. **Matching/identity (§6)** — can the `--capture` mode reliably resolve a scraped
   Bovada prop to a `props.id` by (player_id, market, line, side)? Where does it break?
5. **Operational risk (§8)** — the Bovada-scraping TOS + cadence. Is ~6 req/day realistic,
   or will it get walled? What's the monitoring/canary?

## Output
Append your review to `docs/ODDS-CAPTURE-DESIGN.md` as a new `## Appendix: Adversarial
Review (reasonix, <verdict>)` section — for each of the 5, state PASS / ISSUE (with the
specific fix). If the design is sound, say so plainly; don't manufacture findings.

## GUARDRAILS
- READ-ONLY. No code/DB changes. Append to the design doc only.
- Bounded; curl-verify any endpoint claim. No machine-wide greps.
- Write `logs/AGENT-M6-review-reasonix.md` (1-line OK if the review's in the doc).
- Do NOT commit/push/deploy.
