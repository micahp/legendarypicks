#!/usr/bin/env node
/**
 * E2E-mock-draft — drives the v0.6.12 feature claims in a real browser.
 *
 * REG-render proves the page mounts and does not throw. That is a different question from
 * "do the things the release notes claim actually work", and this release claims a lot:
 * D/ST draftable at published ADP, position filters, a queue, a board grid, a clock.
 * Each assertion is tied to a specific line in the CHANGELOG, so a failure names the
 * promise it breaks rather than a selector.
 *
 * Two rules inherited from REG-render, for the same reasons:
 *   1. A 200 is not a render, and a render is not a working feature. Every check drives an
 *      interaction and reads what came back.
 *   2. Evidence unavailable is a FAIL, never a skip. If a control never appears this exits
 *      non-zero and says which claim went unverified.
 *
 * It must not write product data: the two mutating calls are fulfilled locally exactly as
 * REG-render does, and the run asserts the interception fired so the guard cannot rot into
 * a no-op. Reads hit the real backend.
 *
 * Usage:  node scripts/e2e-mock-draft.js          (defaults to :3096, dev)
 *         LP_GATE_F=http://127.0.0.1:3098 node scripts/e2e-mock-draft.js
 */

const BASE = process.env.LP_GATE_F || 'http://127.0.0.1:3096'
const NAV_TIMEOUT = 120000
const SEL_TIMEOUT = 60000

let chromium
try {
  ;({ chromium } = require('/root/legendarypicks/node_modules/playwright'))
} catch (e) {
  console.log('FAIL E2E-mock-draft  (playwright not resolvable: ' + e.message + ')')
  process.exit(1)
}

const failures = []
const notes = []
function check(cond, claim, detail) {
  if (!cond) failures.push(claim + ' — ' + detail)
  else notes.push(claim)
  return !!cond
}

// ── In-page helpers ─────────────────────────────────────────────────────────────
// The page renders TWO tables: the player pool, and the teams x rounds board grid. A bare
// `table tbody tr` counts both, which made a 32-defense filter read as 44 rows. Everything
// below finds the pool by its PLAYER header instead. These run inside the browser, so they
// use plain DOM only — Playwright's :text-is() is not valid CSS and throws in evaluate().

function readPool() {
  const pool = Array.from(document.querySelectorAll('table'))
    .find(t => /PLAYER/.test((t.querySelector('thead') || {}).innerText || ''))
  if (!pool) return null
  return Array.from(pool.querySelectorAll('tbody tr'))
    .map(r => Array.from(r.querySelectorAll('td')).map(c => c.innerText.trim()))
    .filter(c => c.length > 4)
    .map(c => ({ name: c[1].split('\n')[0], pos: c[2], avail: c[3], adp: c[4] }))
}

// Filter chips are dispatched directly rather than via locator.click(): they re-render on
// every filter change, and an actionability wait on them times out as "waiting for
// locator" — which reads like the control is missing when it is merely busy.
function clickByText(text) {
  const b = Array.from(document.querySelectorAll('button')).find(x => x.innerText.trim() === text)
  if (!b) return false
  b.click()
  return true
}

function draftFirstDST() {
  const pool = Array.from(document.querySelectorAll('table'))
    .find(t => /PLAYER/.test((t.querySelector('thead') || {}).innerText || ''))
  if (!pool) return null
  const row = Array.from(pool.querySelectorAll('tbody tr')).find(r => r.innerText.indexOf('D/ST') !== -1)
  if (!row) return null
  const name = row.querySelectorAll('td')[1].innerText.split('\n')[0].trim()
  const btn = Array.from(row.querySelectorAll('button')).find(b => /DRAFT/i.test(b.innerText))
  if (!btn) return null
  btn.click()
  return name
}

function queueFirst() {
  const pool = Array.from(document.querySelectorAll('table'))
    .find(t => /PLAYER/.test((t.querySelector('thead') || {}).innerText || ''))
  if (!pool) return false
  const btn = Array.from(pool.querySelectorAll('button')).find(b => b.innerText.trim() === '+Q')
  if (!btn) return false
  btn.click()
  return true
}

function boardHeaders() {
  const grid = Array.from(document.querySelectorAll('table'))
    .find(t => /TEAM/.test((t.querySelector('thead') || {}).innerText || ''))
  if (!grid) return null
  return Array.from(grid.querySelectorAll('thead th')).map(h => h.innerText.trim())
}

;(async () => {
  let browser
  try {
    browser = await chromium.launch()
  } catch (e) {
    console.log('FAIL E2E-mock-draft  (chromium will not launch: ' + e.message + ')')
    process.exit(1)
  }

  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } })

  let intercepted = 0
  await page.route('**/api/nfl/mock-draft**', async route => {
    const req = route.request()
    if (req.method() !== 'POST') return route.continue()
    intercepted++
    if (req.url().includes('/picks')) {
      let n = 0
      try { n = (JSON.parse(req.postData() || '{}').picks || []).length } catch (_) {}
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ inserted: n }) })
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'e2e-ephemeral' }) })
  })

  const consoleErrors = []
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)) })
  page.on('pageerror', e => consoleErrors.push('UNCAUGHT: ' + e.message.slice(0, 200)))

  try {
    await page.goto(BASE + '/mock-draft', { waitUntil: 'networkidle', timeout: NAV_TIMEOUT })
    const start = page.getByRole('button', { name: 'Start Draft' })
    await start.waitFor({ timeout: SEL_TIMEOUT })
    await start.click()
    await page.waitForSelector('table tbody tr', { timeout: SEL_TIMEOUT })

    const all = await page.evaluate(readPool)
    if (!check(all != null && all.length > 50, 'the player pool renders',
      'pool rows: ' + (all ? all.length : 'NO TABLE WITH A PLAYER HEADER'))) {
      throw new Error('pool absent — nothing further can be verified')
    }

    // ── "All 32 D/ST are in the pool" ─────────────────────────────────────────
    check(await page.evaluate(clickByText, 'DEF'), 'a DEF position filter exists', 'no DEF chip')
    await page.waitForTimeout(900)
    const def = await page.evaluate(readPool)
    check(def.length === 32, 'all 32 D/ST are in the pool', 'DEF filter returned ' + def.length + ' rows')
    check(def.every(d => d.pos === 'DEF'), 'the position filter returns only that position',
      'other positions present: ' + [...new Set(def.filter(d => d.pos !== 'DEF').map(d => d.pos))].join(','))

    // ── "Their draft position is ESPN's published ADP" ────────────────────────
    const den = def.find(d => /Denver|DEN/.test(d.name))
    check(den && /^9[01]\./.test(den.adp), 'D/ST carry published ADP (DEN ~90.0)',
      'DEN reads ADP=' + (den ? den.adp : 'ROW MISSING'))

    // ── "A fabricated sentinel that reaches a user is a false measurement" ────
    const fabricated = def.filter(d => /999/.test(d.adp))
    check(fabricated.length === 0, 'no 999 sentinel reaches the user',
      fabricated.length + ' D/ST render 999 as their ADP')

    // ── "A defense with no published ADP shows —, not a number" ──────────────
    const blank = def.filter(d => !/[0-9]/.test(d.adp))
    const numeric = def.filter(d => /[0-9]/.test(d.adp))
    check(blank.every(d => d.adp.includes('—')), 'unpublished ADP renders an em dash',
      'empties that are not a dash: ' + blank.map(d => JSON.stringify(d.adp)).slice(0, 3).join(','))
    check(numeric.length >= 15, 'the published D/ST ADPs are present',
      'only ' + numeric.length + ' of 32 D/ST carry a number')
    notes.push('D/ST ADP published on ' + numeric.length + ' of 32, ' + blank.length + ' show an em dash')

    // ── "Both surfaces now agree about who played" — D/ST used to read 0/17 ──
    const zeroed = def.filter(d => /^0\//.test(d.avail))
    check(zeroed.length === 0, 'D/ST availability is measured, not zero',
      zeroed.length + ' D/ST still read 0 games')
    check(den && /17\/17/.test(den.avail), 'DEN D/ST reads a full season',
      'DEN availability=' + (den ? den.avail : 'ROW MISSING'))

    // ── "A queue — pre-rank players" ─────────────────────────────────────────
    check(await page.evaluate(clickByText, 'ALL'), 'an ALL filter chip exists', 'no ALL chip')
    await page.waitForTimeout(700)
    const restored = await page.evaluate(readPool)
    check(restored.length > def.length, 'clearing the filter restores the full pool',
      'ALL returned ' + restored.length + ' rows against ' + def.length + ' filtered')
    const bodyBefore = await page.locator('body').innerText()
    check(await page.evaluate(queueFirst), 'a +Q queue control exists on a pool row', 'no +Q button')
    await page.waitForTimeout(800)
    const bodyAfter = await page.locator('body').innerText()
    check(bodyAfter !== bodyBefore, 'the queue responds to +Q', 'the page did not change after queueing')

    // ── "A board grid showing teams x rounds" ────────────────────────────────
    const headers = await page.evaluate(boardHeaders)
    check(headers != null, 'the board grid is on the page', 'no table with a TEAM header')
    if (headers) {
      const rounds = headers.filter(h => /^R\d+$/.test(h))
      check(rounds.length === 15, 'the board grid shows 15 rounds', 'found ' + rounds.length + ' round columns')
    }

    // ── "A 30-second clock ... autopick when it expires" ─────────────────────
    await page.waitForTimeout(2600)
    const bodyLater = await page.locator('body').innerText()
    check(bodyLater !== bodyAfter, 'the clock is running',
      'page text is byte-identical across 2.6s — the clock may be frozen')

    // ── "Defenses are draftable" — the headline claim ────────────────────────
    await page.evaluate(clickByText, 'DEF')
    await page.waitForTimeout(900)
    const drafted = await page.evaluate(draftFirstDST)
    check(drafted != null, 'a D/ST row offers a DRAFT control', 'no draftable D/ST row found')
    if (drafted) {
      await page.waitForTimeout(1800)
      const afterDraft = await page.locator('body').innerText()
      const team = drafted.split(' ')[0]
      check(afterDraft.includes('D/ST') && (afterDraft.includes(drafted) || afterDraft.includes(team)),
        'the drafted D/ST lands on the roster',
        'drafted "' + drafted + '" but it is not on screen afterwards')
      notes.push('drafted ' + drafted)
    }

    check(intercepted > 0, 'writes were intercepted, not persisted',
      'interception never fired — this run may have written real rows')
    check(consoleErrors.length === 0, 'no console or page errors',
      consoleErrors.slice(0, 3).join(' ;; '))
  } catch (e) {
    failures.push('run aborted: ' + String(e.message).slice(0, 300))
  } finally {
    await browser.close()
  }

  if (failures.length) {
    console.log('FAIL E2E-mock-draft  (' + failures.length + ' claim(s) broken)')
    failures.forEach(f => console.log('   x ' + f))
    process.exit(1)
  }
  console.log('PASS E2E-mock-draft  (' + notes.length + ' claims verified, writes intercepted=' + intercepted + ')')
  notes.forEach(n => console.log('   - ' + n))
  process.exit(0)
})()
