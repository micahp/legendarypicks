# NFL historical rule regimes (2010–2026)

**Status:** Initial verified high-impact inventory, NOT a complete audit of every annual amendment.  
**Structured registry:** [NFL-RULE-REGIME-REGISTRY-2010-2026.json](NFL-RULE-REGIME-REGISTRY-2010-2026.json)  
**Dataset coverage:** NFL historical schedules, play-by-play and associated records, 2010–2026.

## Why this is necessary

A historical play from 2011 may not be legally transferable to a 2026 game without an era translation. The change might be **a legal rule** (kickoff touchback spot, whether a try is required), **a decision regime** (overtime possession guarantee, permitted onside kickoff), **a measurement convention** (catch/fumble and review), or **an exposure change** (17 vs 16 regular-season games). A sample's original context must remain distinguishable from the target game's active rules.

## Verified season transitions affecting the simulator

| Season | Key changes verified in first pass | Affected modeling surfaces |
|---|---|---|
| 2010 | Modified sudden-death overtime **postseason only**; defensive restrictions around kick snapper | Overtime, blocked kicks |
| 2011 | Kickoff moves to own 35; reduced coverage running start | Kickoffs, touchbacks |
| 2012 | Modified sudden-death overtime extended to **regular season** | OT possession, winners, tries |
| 2013 | Tuck rule eliminated; FG/try defensive overload restrictions | Fumbles, blocking |
| 2014 | Clock remains running after sacks outside final two minutes; reviews of loose-ball recovery expanded | Clock, fumbles |
| 2015 | PAT kick snap at 15, two-point try at 2; defense can score two on try return | Two-point choice, try success, defensive score |
| 2016 | Kickoff touchback moved from own 20 to own 25; chop-block restriction | Field position, penalties |
| 2017 | Regular-season OT reduced to 10 minutes; FG/try leaper prohibited | OT, blocked FG |
| 2018 | Catch standard updated; kickoff alignment changed; unnecessary regulation-end try removed; specific OT turnover down continues | Passes, kickoffs, try eligibility, OT |
| 2019 | Pass interference reviewable **only in 2019**; 2018 kickoff structure made permanent | Penalties, replay, kickoff |
| 2020 | 2019 PI-replay provision ended; returner protection expanded | Replay, penalty outcomes |
| 2021 | 17 regular-season games/18 weeks; preseason overtime removed; replay assistance changed | Season metrics, PRE vs REG, replay |
| 2022 | Both sides receive an overtime possession opportunity in **postseason** | OT, walk-off scoring |
| 2023 | One-year fair catch of free kick behind own 25 puts ball at 25 | Kickoff/safety-kick start spot |
| 2024 | Dynamic kickoff and revised touchback regimes; hip-drop tackle prohibited; restricted onside declaration | Special teams, tackles, penalties |
| 2025 | Dynamic kickoff made permanent with new TB35 path; **regular-season** overtime both-team opportunity even after opening TD; onside eligibility changed | Kickoff, OT, two-point choice |
| 2026 | Free-kick setup and kickoff-from-50 touchback updates, Rule 6 onside text, disqualification consultation changes | Free kicks, onside, replay |

The machine-readable registry lists **39** verified high-impact transitions, effective start/end seasons, REG/POST applicability, a model implication and a source URL. Every year remains flagged **annual full-rulebook audit incomplete**. This first pass must not be presented as *all* rule changes.

## Integration contract

1. Every historical record has `season`, `season_type`, `game_id`, and `source_rule_regime`. Join postseason type from schedule when the local PBP table omits it.
2. Every simulated matchup has `target_rule_regime` generated from the target season and game type. The reducer enforces **target** rules; it never silently applies source-year legality.
3. A source play can be sampled directly only if source-to-target legality and outcomes are compatible. Otherwise, use a versioned translation with an auditable denominator, or exclude with a named reason.
4. On any **decision** change, reconstruct choice opportunities rather than using completed-choice counts alone (e.g. 2024 declared onside vs 2025).
5. On **rate** changes, do not pool across eras before testing whether pooling is justified (2015 extra points, 2024–26 kickoffs, OT rules).
6. Save a `rule_registry_sha256`, `active_rule_ids`, dataset hash, and reducer commit with every simulation manifest.
7. Require invariant tests at each regime boundary: REG 2011/2012 OT; 2014/2015 PAT; 2015/2016 touchback; 2016/2017 OT length; 2017/2018 walk-off try and kick rules; 2021/2022 postseason OT; 2023/2024 kickoff; 2024/2025 REG OT and kickoff; 2025/2026 kick-at-50.
8. For empirical comparisons spanning years, include era indicators and test a pre/post segmentation or explicit structural break. A regime change is not itself evidence of a particular measured effect.

## Audit completion checklist

- [x] Start source-linked structured registry for each dataset year, 2010–2026.
- [x] Mark high-impact confirmed regime transitions from official NFL sources.
- [ ] Verify the **entire** annual Rules Changes section for all 17 year-specific official rulebooks, and all in-season rule exceptions; record official text and its document SHA-256.
- [ ] Cover **all** permanent, experimental/one-year, repeal and midseason changes, including details not yet in the first pass.
- [ ] Add rule section/article, legal edge cases, source-field mapping, and exact effective season type.
- [ ] Check changes in stat-provider classifications/labels separately from actual football rules.
- [ ] Add automated source-year versus target-year compatibility function and boundary tests.
- [ ] Compare current simulator `GUARDS` / traceability matrix to registry and fail if any known regime-dependent transition lacks a registered policy.

## Original NFL sources

- [NFL 2026 Rulebook](https://operations.nfl.com/rules-officiating/2026-nfl-rulebook)
- [NFL featured rules and 2025 changes](https://operations.nfl.com/rules-officiating/featured-rules)
- [NFL overtime rule evolution](https://operations.nfl.com/rules-officiating/featured-rules/overtime-rules/)
- [Official 2018 rule changes](https://operations.nfl.com/media/3277/2018-nfl-rulebook_final-version.pdf)
- [Official 2024 kickoff guide](https://operations.nfl.com/media/2c1hiep0/2024-kickoff-guide.pdf)
- [NFL historical safety-rule chronology](https://www.nfl.com/news/nfl-health-and-safety-related-rules-changes-since-2002)
- [NFL 2015 try rule](https://www.nfl.com/news/nfl-moves-extra-point-to-15-yard-line-for-2015-season-0ap3000000493347)
- [2023 one-year fair-catch experiment](https://operations.nfl.com/updates/the-rules/adopted-playing-rules-change-proposal-putting-ball-in-play-after-fair-catch/)

**Do not assume a blank or incomplete annual audit means "no rule changes."** The sources and registry are a baseline for completing the full audit.
