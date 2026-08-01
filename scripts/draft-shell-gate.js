#!/usr/bin/env node
/**
 * Gates for docs/TASK-mock-draft-espn-shell.md §7 — written and committed BEFORE the
 * code they describe, so weakening one shows up in git as an edit to this file rather
 * than as a green run.
 *
 * Every gate here drives a real browser and requires React to have mounted AND responded
 * to an interaction, for the reason scripts/render-gate.js exists: on 2026-07-28 eight
 * gates were green over a pool that crashed on first render. Every assertion was true;
 * not one of them rendered React.
 *
 * Two rules, inherited:
 *   1. Evidence unavailable is a FAIL, never a skip. A gate that could not run has not
 *      passed. Every catch below records a failure and names the surface.
 *   2. The gate must not write product data. The two mutating mock-draft calls are
 *      fulfilled locally, and the run asserts the interception fired so the guard cannot
 *      rot into a no-op.
 *
 * Usage:  node scripts/draft-shell-gate.js
 *         LP_GATE_F=http://127.0.0.1:3093 node scripts/draft-shell-gate.js
 *         node scripts/draft-shell-gate.js REG-sort        (one gate, for iteration)
 *
 * ── The DOM contract this file pins ────────────────────────────────────────────────
 * These are the selectors the rebuilt draft room must publish. They are part of the
 * spec, not incidental: a gate that reads a class name or a nth-child index re-breaks
 * every time the layout moves, and then gets deleted rather than fixed.
 *
 *   [data-testid="draft-status-header"]   persistent, visible on all four tabs
 *   [data-testid="draft-clock"]           the countdown, `0:SS`
 *   [data-testid="draft-pick-counter"]    `Pick <n> of <total>`
 *   [data-testid="round-strip"]           the horizontally scrolling pick cards
 *   [role="tablist"] > [role="tab"]       Players | Queue (n) | Board | Rosters
 *   [role="tabpanel"][data-tab="..."]     exactly ONE mounted at a time
 *   [data-testid="pool-table"]            the player list
 *   th/td[data-col="rank|player|bye|adp|proj|avail|action"]
 *   [data-testid="row-action"]            the action cell — exactly one <button>
 *   [data-testid="your-pick-divider"]     `YOUR PICK (R<r>,P<p>)` rules inside the list
 *   [data-testid="position-filter"]       the position control, authored order
 *   #pool-sort                            the sort <select>
 */

const BASE = process.env.LP_GATE_F || 'http://127.0.0.1:3093'
const ONLY = process.argv[2] || null
const NAV_TIMEOUT = 120000
const SEL_TIMEOUT = 60000

// The draft this gate runs. Seat 12 of 12 is not the default on either control, so a
// hardcoded seat or a Math.random() one fails here rather than passing by coincidence —
// and it is the seat §7's divider assertion is written against.
const TEAMS = 12
const SEAT = 12

let chromium
try {
  ;({ chromium } = require('/root/legendarypicks/node_modules/playwright'))
} catch (e) {
  console.log('FAIL draft-shell-gate  (playwright not resolvable: ' + e.message + ')')
  process.exit(1)
}

// ── Result plumbing ────────────────────────────────────────────────────────────────
const results = []            // { id, failures: [], notes: [] }
let current = null
function gate(id) {
  current = { id, failures: [], notes: [] }
  results.push(current)
  return current
}
function check(cond, detail) {
  if (!cond) current.failures.push(detail)
  return !!cond
}
function note(n) { current.notes.push(n) }
function wanted(id) { return !ONLY || ONLY === id }

// ── In-page readers. Plain DOM only: these run inside the browser. ──────────────────
function readPoolRows() {
  const table = document.querySelector('[data-testid="pool-table"]')
  if (!table) return null
  const cols = Array.from(table.querySelectorAll('thead th')).map(
    h => h.getAttribute('data-col') || ''
  )
  const out = []
  for (const tr of Array.from(table.querySelectorAll('tbody tr'))) {
    if (tr.getAttribute('data-testid') === 'your-pick-divider') {
      out.push({ divider: true, text: tr.innerText.trim() })
      continue
    }
    const tds = Array.from(tr.querySelectorAll('td'))
    if (!tds.length) continue
    const row = { divider: false }
    tds.forEach((td, i) => {
      const key = td.getAttribute('data-col') || cols[i] || ('c' + i)
      row[key] = td.innerText.trim()
    })
    row.buttons = Array.from(tr.querySelectorAll('[data-testid="row-action"] button')).map(
      b => b.innerText.trim()
    )
    out.push(row)
  }
  return out
}

function readHeaders() {
  const table = document.querySelector('[data-testid="pool-table"]')
  if (!table) return null
  return Array.from(table.querySelectorAll('thead th')).map(h => ({
    col: h.getAttribute('data-col') || '',
    text: h.innerText.trim(),
  }))
}

function readTabs() {
  const list = document.querySelector('[role="tablist"]')
  if (!list) return null
  return Array.from(list.querySelectorAll('[role="tab"]')).map(t => ({
    name: t.innerText.trim(),
    selected: t.getAttribute('aria-selected') === 'true',
  }))
}

function clickTab(name) {
  const list = document.querySelector('[role="tablist"]')
  if (!list) return false
  const tab = Array.from(list.querySelectorAll('[role="tab"]')).find(t =>
    t.innerText.trim().toLowerCase().startsWith(name.toLowerCase())
  )
  if (!tab) return false
  tab.click()
  return true
}

function readPanels() {
  return Array.from(document.querySelectorAll('[role="tabpanel"]')).map(p =>
    p.getAttribute('data-tab')
  )
}

function readClockSeconds() {
  const el = document.querySelector('[data-testid="draft-clock"]')
  if (!el) return null
  const m = /(\d+):(\d\d)/.exec(el.innerText)
  return m ? Number(m[1]) * 60 + Number(m[2]) : null
}

function readCurrentPick() {
  const el = document.querySelector('[data-testid="draft-pick-counter"]')
  if (!el) return null
  const m = /Pick\s+(\d+)/i.exec(el.innerText)
  return m ? Number(m[1]) : null
}

function readPositionFilter() {
  const el = document.querySelector('[data-testid="position-filter"]')
  if (!el) return null
  const opts = el.querySelectorAll('option')
  if (opts.length) return Array.from(opts).map(o => o.innerText.trim())
  return Array.from(el.querySelectorAll('button,[role="radio"]')).map(b => b.innerText.trim())
}

function setPosition(label) {
  const el = document.querySelector('[data-testid="position-filter"]')
  if (!el) return false
  const opts = Array.from(el.querySelectorAll('option'))
  if (opts.length) {
    const sel = el.tagName === 'SELECT' ? el : el.querySelector('select')
    const opt = opts.find(o => o.innerText.trim() === label)
    if (!sel || !opt) return false
    sel.value = opt.value
    sel.dispatchEvent(new Event('change', { bubbles: true }))
    return true
  }
  const btn = Array.from(el.querySelectorAll('button,[role="radio"]')).find(
    b => b.innerText.trim() === label
  )
  if (!btn) return false
  btn.click()
  return true
}

function clickFirstAction() {
  const table = document.querySelector('[data-testid="pool-table"]')
  if (!table) return null
  for (const tr of Array.from(table.querySelectorAll('tbody tr'))) {
    const btn = tr.querySelector('[data-testid="row-action"] button')
    if (!btn) continue
    const label = btn.innerText.trim()
    btn.click()
    return label
  }
  return null
}

// ── Helpers on the node side ───────────────────────────────────────────────────────
const num = s => {
  if (s == null) return null
  const m = /-?\d+(\.\d+)?/.exec(String(s).replace(/,/g, ''))
  return m ? Number(m[0]) : null
}
// The availability cell is a fraction with a label under it, and the label can
// legitimately contain a year ("No 2025 games"). Taking the first integer out of
// that reads 2025 as an availability. Read the measurement or read nothing.
const games = s => {
  const m = /^(\d+)\s*\/\s*(\d+)/.exec(String(s == null ? '' : s).trim())
  return m ? Number(m[1]) : null
}
const valueIn = (col, s) => (col === 'avail' ? games(s) : num(s))
const isBlank = s => s != null && /^[—-]$/.test(String(s).trim())

async function startDraft(page) {
  await page.goto(BASE + '/mock-draft', { waitUntil: 'networkidle', timeout: NAV_TIMEOUT })
  const start = page.getByRole('button', { name: 'Start Draft' })
  await start.waitFor({ timeout: SEL_TIMEOUT })
  const size = page.locator('[data-testid="draft-setup"] [role="radio"]', {
    hasText: String(TEAMS),
  })
  await size.first().click()
  await page.selectOption('#draft-slot', String(SEAT))
  await start.click()
  await page.waitForSelector('[data-testid="pool-table"] tbody tr', { timeout: SEL_TIMEOUT })
}

;(async () => {
  let browser
  try {
    browser = await chromium.launch()
  } catch (e) {
    console.log('FAIL draft-shell-gate  (chromium will not launch: ' + e.message + ')')
    process.exit(1)
  }

  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } })

  // Writes are faked. `pickDelayMs` is a knob, not a fudge: commitPick awaits the picks
  // POST before running the bots, so stretching that response is the only way to hold the
  // "bots are picking, it is not your turn" state still long enough to assert on it. The
  // assertion is unchanged; only the wall-clock width of a real state is.
  let intercepted = 0
  let createBody = null
  let pickDelayMs = 0
  await page.route('**/api/nfl/mock-draft**', async route => {
    const req = route.request()
    if (req.method() !== 'POST') return route.continue()
    intercepted++
    const url = req.url()
    if (!url.includes('/picks') && !url.includes('/complete')) {
      try { createBody = JSON.parse(req.postData() || '{}') } catch (_) {}
    }
    if (url.includes('/picks')) {
      let n = 0
      try { n = (JSON.parse(req.postData() || '{}').picks || []).length } catch (_) {}
      if (pickDelayMs) await new Promise(r => setTimeout(r, pickDelayMs))
      return route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ inserted: n }),
      })
    }
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ id: 'draft-shell-gate-ephemeral' }),
    })
  })

  const consoleErrors = []
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)) })
  page.on('pageerror', e => consoleErrors.push('UNCAUGHT: ' + e.message.slice(0, 200)))

  // Read the projection contract from the payload rather than trusting a header.
  let referenceSeason = null
  let draftSeason = null
  let projectedPlayers = 0
  try {
    const r = await page.request.get(BASE + '/api/nfl/mock-draft/pool?season=2026')
    const payload = await r.json()
    referenceSeason = payload.reference_season ?? null
    draftSeason = payload.season ?? null
    projectedPlayers = (payload.players || []).filter(p => p.proj_ppr_points != null).length
  } catch (_) {}

  try {
    await startDraft(page)
  } catch (e) {
    console.log('FAIL draft-shell-gate  (could not reach the draft room: ' +
      e.message.split('\n')[0] + ')')
    await browser.close()
    process.exit(1)
  }

  // ── REG-tabs ─────────────────────────────────────────────────────────────────────
  // Four tabs by accessible name; each mounts its own panel and unmounts the others; the
  // status header survives every switch; no console error is produced by switching.
  if (wanted('REG-tabs')) {
    gate('REG-tabs')
    try {
      const tabs = await page.evaluate(readTabs)
      check(tabs != null, 'no [role="tablist"] on the draft room')
      if (tabs) {
        const names = tabs.map(t => t.name)
        check(tabs.length === 4, 'expected 4 tabs, found ' + tabs.length + ': ' + JSON.stringify(names))
        const expect = ['Players', 'Queue', 'Board', 'Rosters']
        expect.forEach((want, i) => {
          check(
            names[i] != null && names[i].toLowerCase().startsWith(want.toLowerCase()),
            'tab ' + i + ' is ' + JSON.stringify(names[i]) + ', expected ' + want
          )
        })
        // ESPN's queue tab carries a count. Ours must too, or the badge is decoration.
        check(/\d/.test(names[1] || ''), 'the Queue tab carries no count badge: ' + JSON.stringify(names[1]))
        note('tabs=' + JSON.stringify(names))

        for (const want of expect) {
          const before = consoleErrors.length
          const clicked = await page.evaluate(clickTab, want)
          check(clicked, 'could not click the ' + want + ' tab')
          await page.waitForTimeout(350)
          const panels = await page.evaluate(readPanels)
          check(
            panels.length === 1,
            want + ': ' + panels.length + ' tabpanels mounted (' + JSON.stringify(panels) +
              ') — exactly one must be'
          )
          check(
            panels[0] != null && panels[0].toLowerCase() === want.toLowerCase(),
            want + ': mounted panel is data-tab=' + JSON.stringify(panels[0])
          )
          const now = await page.evaluate(readTabs)
          const sel = now.filter(t => t.selected).map(t => t.name)
          check(sel.length === 1, want + ': ' + sel.length + ' tabs report aria-selected=true')
          check(
            sel[0] != null && sel[0].toLowerCase().startsWith(want.toLowerCase()),
            want + ': aria-selected is on ' + JSON.stringify(sel[0])
          )
          const headerVisible = await page.locator('[data-testid="draft-status-header"]').isVisible()
          check(headerVisible, want + ': the status header is not visible on this tab')
          check(
            consoleErrors.length === before,
            want + ': switching produced ' + (consoleErrors.length - before) +
              ' console error(s): ' + consoleErrors.slice(before, before + 2).join(' ;; ')
          )
        }
      }
    } catch (e) { check(false, 'gate threw: ' + e.message.split('\n')[0]) }
    await page.evaluate(clickTab, 'Players').catch(() => {})
    await page.waitForTimeout(300)
  }

  // ── REG-position-order ───────────────────────────────────────────────────────────
  // Asserted on the RENDERED text, left to right — not on the source array. The bug this
  // replaces shipped because the array looked sorted and the row looked wrong, and only
  // one of those was ever read. FLEX is in the canonical order but is not a stored
  // position in the mock-draft pool, so it is legitimately absent here.
  if (wanted('REG-position-order')) {
    gate('REG-position-order')
    try {
      const labels = await page.evaluate(readPositionFilter)
      check(labels != null, 'no [data-testid="position-filter"] on the draft room')
      if (labels) {
        const expect = ['All', 'QB', 'RB', 'WR', 'TE', 'K', 'D/ST']
        check(
          JSON.stringify(labels) === JSON.stringify(expect),
          'position filter reads ' + JSON.stringify(labels) + ', expected ' + JSON.stringify(expect)
        )
        note('order=' + labels.join(' '))
      }
    } catch (e) { check(false, 'gate threw: ' + e.message.split('\n')[0]) }
  }

  // ── REG-projection ───────────────────────────────────────────────────────────────
  // Published 2026 projections must be a real API field and a visible decision
  // column. Prior-season actual/xFP columns no longer occupy the draft row.
  if (wanted('REG-projection')) {
    gate('REG-projection')
    try {
      const heads = await page.evaluate(readHeaders)
      check(heads != null, 'no pool table to read headers from')
      if (heads) {
        const proj = heads.filter(h => /PROJ/i.test(h.text))
        check(projectedPlayers > 0, 'pool API returned zero non-null projected players')
        check(proj.length === 1 && proj[0].col === 'proj', 'expected one proj column: ' + JSON.stringify(proj))
        check(heads.some(h => h.col === 'rank' && /^RK$/i.test(h.text)), 'published RK header is missing')
        check(draftSeason != null && proj[0] && proj[0].text.includes(String(draftSeason)),
          'projection header does not name drafted season ' + draftSeason)
        check(!heads.some(h => h.col === 'pts' || h.col === 'xfp'),
          'prior-season actual/xFP still occupies a draft decision column')
        note('headers=' + heads.map(h => h.text).filter(Boolean).join(' | '))
        note('projected=' + projectedPlayers)
      }
    } catch (e) { check(false, 'gate threw: ' + e.message.split('\n')[0]) }
  }

  // ── REG-labels ───────────────────────────────────────────────────────────────────
  // The database speaks PK and DEF. A drafter has never seen either string.
  if (wanted('REG-labels')) {
    gate('REG-labels')
    try {
      const body = await page.locator('body').innerText()
      check(!/\bPK\b/.test(body), 'the string "PK" is rendered to the user')
      check(!/\bDEF\b/.test(body), 'the string "DEF" is rendered to the user')

      for (const [label, expectRows] of [['K', null], ['D/ST', 32]]) {
        const ok = await page.evaluate(setPosition, label)
        check(ok, 'the position filter has no ' + label + ' option')
        await page.waitForTimeout(600)
        const rows = await page.evaluate(readPoolRows)
        const players = (rows || []).filter(r => !r.divider)
        check(players.length > 0, label + ': filter returned no rows')
        const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        const positionInPlayerCell = new RegExp('(?:^|[·\\s])' + escaped + '(?:$|[·\\s])')
        const wrong = players.filter(r => !positionInPlayerCell.test(r.player || ''))
        check(
          wrong.length === 0,
          label + ': ' + wrong.length + ' row(s) show a different position in the player cell: ' +
            JSON.stringify((wrong[0] || {}).player).slice(0, 120)
        )
        // Nobody says "D/ST1" out loud, and ESPN prints no positional rank for either.
        const ranked = players.filter(r => new RegExp(label.replace('/', '\\/') + '\\d').test(r.player || ''))
        check(
          ranked.length === 0,
          label + ': ' + ranked.length + ' row(s) render a positional rank (e.g. ' +
            JSON.stringify((ranked[0] || {}).player) + ')'
        )
        if (expectRows != null) {
          check(players.length === expectRows, label + ': ' + players.length + ' rows, expected ' + expectRows)
        }
        note(label + '=' + players.length + ' rows')
      }
      await page.evaluate(setPosition, 'All')
      await page.waitForTimeout(500)
    } catch (e) { check(false, 'gate threw: ' + e.message.split('\n')[0]) }
  }

  // ── REG-your-pick-divider ────────────────────────────────────────────────────────
  // The single best idea in the ESPN screenshots: it turns a list into "who will still be
  // here when I am up". Derived from userNextPick + ADP, so it is honest exactly as long
  // as it is labelled an ADP expectation. Seat 12 → the first divider is (R1,P12).
  if (wanted('REG-your-pick-divider')) {
    gate('REG-your-pick-divider')
    try {
      const rows = await page.evaluate(readPoolRows)
      check(rows != null, 'no pool table')
      if (rows) {
        const idx = rows.findIndex(r => r.divider)
        check(idx >= 0, 'no [data-testid="your-pick-divider"] in the list')
        if (idx >= 0) {
          check(
            /YOUR PICK \(R1,P12\)/i.test(rows[idx].text),
            'first divider reads ' + JSON.stringify(rows[idx].text) + ', expected YOUR PICK (R1,P12)'
          )
          const above = rows.slice(0, idx).filter(r => !r.divider)
          const below = rows.slice(idx + 1).filter(r => !r.divider)
          check(below.length > 0, 'the divider is the last row — nothing is expected to survive to your pick')
          const aboveBad = above.filter(r => num(r.adp) != null && num(r.adp) >= SEAT)
          const belowBad = below.slice(0, 25).filter(r => num(r.adp) != null && num(r.adp) < SEAT)
          check(
            aboveBad.length === 0,
            aboveBad.length + ' row(s) above the P12 divider have ADP >= 12 (e.g. ' +
              JSON.stringify((aboveBad[0] || {}).adp) + ')'
          )
          check(
            belowBad.length === 0,
            belowBad.length + ' row(s) below the P12 divider have ADP < 12 (e.g. ' +
              JSON.stringify((belowBad[0] || {}).adp) + ')'
          )
          note('divider at row ' + idx + ', ' + above.length + ' above / ' + below.length + ' below')
        }
      }
    } catch (e) { check(false, 'gate threw: ' + e.message.split('\n')[0]) }
  }

  // ── REG-one-button ───────────────────────────────────────────────────────────────
  // Exactly one button per action cell, always. On the clock every label is Draft; while
  // the bots are picking every label is Queue or Queued. `+Q` and `−Q` are gone from the
  // codebase, so they must appear zero times in the DOM.
  if (wanted('REG-one-button')) {
    gate('REG-one-button')
    try {
      const rows = (await page.evaluate(readPoolRows) || []).filter(r => !r.divider)
      check(rows.length >= 20, 'only ' + rows.length + ' rows to inspect, need 20')
      const sample = rows.slice(0, 20)
      const notOne = sample.filter(r => (r.buttons || []).length !== 1)
      check(
        notOne.length === 0,
        notOne.length + ' of 20 action cells do not hold exactly one button: ' +
          JSON.stringify(notOne.slice(0, 3).map(r => r.buttons))
      )
      const labels = [...new Set(sample.map(r => (r.buttons || [])[0]))]
      check(
        labels.length === 1 && /^draft$/i.test(labels[0] || ''),
        'on the clock the row labels are ' + JSON.stringify(labels) + ', expected only Draft'
      )
      const body = await page.locator('body').innerText()
      check(!/\+Q/.test(body), 'the string "+Q" is still in the DOM')
      check(!/[−-]Q\b/.test(body), 'the string "−Q" is still in the DOM')

      // The other half of the rule. commitPick awaits the picks POST before running the
      // bots, so holding that response open holds the not-your-turn state still.
      pickDelayMs = 2500
      const clicked = await page.evaluate(clickFirstAction)
      check(clicked != null && /^draft$/i.test(clicked), 'could not click a Draft button (got ' + clicked + ')')
      await page.waitForTimeout(700)
      const during = (await page.evaluate(readPoolRows) || []).filter(r => !r.divider).slice(0, 20)
      const duringNotOne = during.filter(r => (r.buttons || []).length !== 1)
      check(
        duringNotOne.length === 0,
        duringNotOne.length + ' action cells hold more than one button while the bots pick'
      )
      const duringLabels = [...new Set(during.map(r => (r.buttons || [])[0]))]
      check(
        duringLabels.every(l => /^(queue|queued)$/i.test(l || '')),
        'while it is not your turn the row labels are ' + JSON.stringify(duringLabels) +
          ', expected Queue/Queued — a live Draft button here also double-applies the pick'
      )
      note('on-clock=' + JSON.stringify(labels) + ' off-clock=' + JSON.stringify(duringLabels))
      pickDelayMs = 0
      await page.waitForTimeout(2600)
    } catch (e) { check(false, 'gate threw: ' + e.message.split('\n')[0]); pickDelayMs = 0 }
  }

  // ── REG-sort ─────────────────────────────────────────────────────────────────────
  // Each sort reorders the table; a descending sort has first >= last; valueless rows land
  // last and render an em dash, never 0.0. A null coerced to 0 is a false measurement,
  // and it is the specific defect that floated all 32 D/ST above pick 1 once already.
  if (wanted('REG-sort')) {
    gate('REG-sort')
    try {
      const options = await page.locator('#pool-sort option').allInnerTexts()
      check(options.length === 7, 'the sort control has ' + options.length + ' options, expected 7')
      const expect = ['Rank', 'Proj Pts', 'ADP', 'Availability', 'Bye', String(referenceSeason) + ' Pts/G', String(referenceSeason) + ' xFP/G']
      check(
        JSON.stringify(options) === JSON.stringify(expect),
        'sort options read ' + JSON.stringify(options) + ', expected ' + JSON.stringify(expect) +
          ' — authored order, default first, never alphabetical'
      )

      // column read for each sort, and the direction it claims
      const plan = [
        { label: 'Rank', col: 'rank', dir: 'asc' },
        { label: 'Proj Pts', col: 'proj', dir: 'desc' },
        { label: 'ADP', col: 'adp', dir: 'asc' },
        { label: 'Availability', col: 'avail', dir: 'desc' },
        { label: 'Bye', col: 'bye', dir: 'asc' },
      ]
      let previousFirst = null
      for (const step of plan) {
        if (!options.includes(step.label)) continue
        await page.selectOption('#pool-sort', { label: step.label })
        await page.waitForTimeout(700)
        const rows = (await page.evaluate(readPoolRows) || []).filter(r => !r.divider)
        check(rows.length > 20, step.label + ': only ' + rows.length + ' rows after sorting')
        const vals = rows.map(r => r[step.col])
        const numeric = vals.map(v => valueIn(step.col, v))
        const firstBlank = vals.findIndex(isBlank)
        const lastValue = numeric.reduce((acc, v, i) => (v != null ? i : acc), -1)
        check(
          firstBlank === -1 || firstBlank > lastValue,
          step.label + ': a valueless row sorts above a measured one (blank at ' + firstBlank +
            ', last value at ' + lastValue + ') — nulls sort last, always'
        )
        const seq = numeric.filter(v => v != null)
        const bad = seq.findIndex((v, i) =>
          i > 0 && (step.dir === 'asc' ? v < seq[i - 1] : v > seq[i - 1])
        )
        check(
          bad === -1,
          step.label + ': not ' + step.dir + 'ending at row ' + bad + ' (' + seq[bad - 1] +
            ' then ' + seq[bad] + ')'
        )
        check(
          seq.length > 1 && (step.dir === 'asc' ? seq[0] <= seq[seq.length - 1] : seq[0] >= seq[seq.length - 1]),
          step.label + ': first ' + seq[0] + ' vs last ' + seq[seq.length - 1] + ' contradicts a ' + step.dir + ' sort'
        )
        const firstName = (rows[0] || {}).player
        check(
          previousFirst === null || firstName !== previousFirst,
          step.label + ': the table did not reorder — still led by ' + JSON.stringify(firstName)
        )
        previousFirst = firstName
        note(step.label + ' → ' + JSON.stringify(String(firstName).split('\n')[0]))
      }
      await page.selectOption('#pool-sort', { label: 'Rank' }).catch(() => {})
      await page.waitForTimeout(500)
    } catch (e) { check(false, 'gate threw: ' + e.message.split('\n')[0]) }
  }

  // ── REG-clock ────────────────────────────────────────────────────────────────────
  // A deadlocked clock has shipped on this surface once already: it hit 0:00 and nothing
  // picked, and the draft sat on pick 6 forever. The countdown must run and must still
  // autopick while a non-Players tab is open, and switching tabs must not remount it —
  // a clock that restarts at 0:30 on every tab switch never expires at all.
  if (wanted('REG-clock')) {
    gate('REG-clock')
    try {
      await page.evaluate(clickTab, 'Board')
      await page.waitForTimeout(400)
      const panels = await page.evaluate(readPanels)
      check(panels[0] === 'board', 'not on the Board tab, on ' + JSON.stringify(panels))

      const t0 = await page.evaluate(readClockSeconds)
      const pick0 = await page.evaluate(readCurrentPick)
      check(t0 != null, 'no [data-testid="draft-clock"] while the Board tab is open')
      check(pick0 != null, 'no [data-testid="draft-pick-counter"]')
      await page.waitForTimeout(3200)
      const t1 = await page.evaluate(readClockSeconds)
      check(t1 != null && t0 != null && t1 < t0, 'clock did not advance on a non-Players tab: ' + t0 + ' → ' + t1)

      // Remount check: a fresh effect resets to 0:30, so the value must keep FALLING
      // across a switch rather than jumping back up.
      await page.evaluate(clickTab, 'Rosters')
      await page.waitForTimeout(1200)
      const t2 = await page.evaluate(readClockSeconds)
      check(
        t2 != null && t1 != null && t2 < t1,
        'the clock reset across a tab switch (' + t1 + ' → ' + t2 + ') — the effect is remounting'
      )

      // And it must still expire into a pick while a non-Players tab is open.
      const deadline = Date.now() + 45000
      let picked = null
      while (Date.now() < deadline) {
        await page.waitForTimeout(1500)
        const p = await page.evaluate(readCurrentPick)
        if (p != null && pick0 != null && p > pick0) { picked = p; break }
      }
      check(
        picked != null,
        'the clock ran out on the Board tab and no pick was made — pick stayed at ' + pick0 +
          ' (this is the deadlock, again)'
      )
      note('clock ' + t0 + '→' + t1 + '→' + t2 + ', pick ' + pick0 + '→' + picked)
      await page.evaluate(clickTab, 'Players')
      await page.waitForTimeout(400)
    } catch (e) { check(false, 'gate threw: ' + e.message.split('\n')[0]) }
  }

  await browser.close()

  // ── Report ───────────────────────────────────────────────────────────────────────
  if (!ONLY) {
    gate('REG-shell-hygiene')
    check(intercepted > 0, 'no mock-draft POST was intercepted — either the draft flow no ' +
      'longer persists, or this gate is writing to the product DB again')
    check(
      createBody != null && createBody.teams === TEAMS && createBody.seat === SEAT,
      'the draft was created as ' + JSON.stringify(createBody) + ', expected teams=' + TEAMS +
        ' seat=' + SEAT
    )
    check(
      consoleErrors.length === 0,
      consoleErrors.length + ' console/page error(s), first: ' + consoleErrors[0]
    )
    note('writes intercepted=' + intercepted)
  }

  let failed = 0
  for (const r of results) {
    if (r.failures.length === 0) {
      console.log('PASS ' + r.id + '  (' + (r.notes.join(' · ') || 'ok') + ')')
    } else {
      failed++
      console.log('FAIL ' + r.id + '  (' + r.failures.length + ')')
      r.failures.forEach(f => console.log('   x ' + f))
    }
  }
  process.exit(failed === 0 ? 0 : 1)
})().catch(e => {
  console.log('FAIL draft-shell-gate  (the gate itself threw: ' + e.message.split('\n')[0] + ')')
  process.exit(1)
})
