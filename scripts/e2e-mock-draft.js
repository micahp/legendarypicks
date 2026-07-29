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
  // Columns are resolved by data-col, not by index. They were read positionally
  // until 2026-07-29, and c[4] is the points column rather than ADP — which
  // made this file report DEN=8.2. It was reading Denver's points per game and
  // calling it an average draft position. A column index is not a column.
  const pool = document.querySelector('[data-testid="pool-table"]')
    || Array.from(document.querySelectorAll('table'))
      .find(t => /PLAYER/.test((t.querySelector('thead') || {}).innerText || ''))
  if (!pool) return null
  const heads = Array.from(pool.querySelectorAll('thead th')).map(h => h.getAttribute('data-col') || '')
  return Array.from(pool.querySelectorAll('tbody tr'))
    .filter(r => r.getAttribute('data-testid') !== 'your-pick-divider')
    .map(r => Array.from(r.querySelectorAll('td')))
    .filter(tds => tds.length > 4)
    .map(tds => {
      const by = {}
      tds.forEach((td, i) => { by[td.getAttribute('data-col') || heads[i] || ('c' + i)] = td.innerText.trim() })
      return {
        name: (by.player || '').split('\n')[0],
        pos: by.pos,
        avail: by.avail,
        adp: by.adp,
      }
    })
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
  const pool = document.querySelector('[data-testid="pool-table"]')
  if (!pool) return null
  const row = Array.from(pool.querySelectorAll('tbody tr'))
    .filter(r => r.getAttribute('data-testid') !== 'your-pick-divider')
    .find(r => r.innerText.indexOf('D/ST') !== -1)
  if (!row) return null
  const name = row.querySelectorAll('td')[1].innerText.split('\n')[0].trim()
  const btn = Array.from(row.querySelectorAll('button')).find(b => /DRAFT/i.test(b.innerText))
  if (!btn) return null
  btn.click()
  return name
}

// Queueing moved off the row. The row holds exactly one button and on the clock
// that button is Draft — and in this engine it is always your turn, because the
// bot picks between your turns run in one synchronous loop. So the card is where
// a player gets queued from, and that is the path this drives.
function openFirstPlayerCard() {
  const pool = document.querySelector('[data-testid="pool-table"]')
  if (!pool) return false
  const row = Array.from(pool.querySelectorAll('tbody tr'))
    .find(r => r.getAttribute('data-testid') !== 'your-pick-divider' && r.querySelectorAll('td').length > 4)
  if (!row) return false
  row.click()
  return true
}

function clickDialogQueue() {
  const dialog = document.querySelector('[role="dialog"]')
  if (!dialog) return false
  const btn = Array.from(dialog.querySelectorAll('button')).find(b => b.innerText.trim() === 'Queue')
  if (!btn) return false
  btn.click()
  return true
}

function queueTabCount() {
  const list = document.querySelector('[role="tablist"]')
  if (!list) return null
  const tab = Array.from(list.querySelectorAll('[role="tab"]')).find(t => /^queue/i.test(t.innerText.trim()))
  if (!tab) return null
  const m = /(\d+)/.exec(tab.innerText)
  return m ? Number(m[1]) : null
}

// The grid is teams-across / rounds-down as of c17eae7, and it lives behind the
// Board tab. This searched every table for a "TEAM" header, which no table has
// ever had — the claim "the board grid shows 15 rounds" could not be true or
// false, only absent, and it read as a failure with the grid right there.
function openBoardTab() {
  const list = document.querySelector('[role="tablist"]')
  if (!list) return false
  const tab = Array.from(list.querySelectorAll('[role="tab"]')).find(t => /^board/i.test(t.innerText.trim()))
  if (!tab) return false
  tab.click()
  return true
}

function boardShape() {
  const grid = document.querySelector('[data-testid="draft-board-grid"]')
  if (!grid) return null
  return {
    cols: Array.from(grid.querySelectorAll('thead th')).map(h => h.innerText.trim()),
    rounds: Array.from(grid.querySelectorAll('tbody tr > th')).map(h => h.innerText.trim()),
  }
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
    const poolResponse = await page.request.get(
      BASE + '/api/nfl/mock-draft/pool?season=2026'
    )
    const poolPayload = poolResponse.ok() ? await poolResponse.json() : null
    const publishedDen = (poolPayload && poolPayload.players || [])
      .find(p => p.team === 'DEN' && p.position === 'DEF')

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
    check(await page.evaluate(clickByText, 'D/ST'), 'a D/ST position filter exists', 'no D/ST chip')
    await page.waitForTimeout(900)
    const def = await page.evaluate(readPool)
    check(def.length === 32, 'all 32 D/ST are in the pool', 'DEF filter returned ' + def.length + ' rows')
    check(def.every(d => d.pos === 'D/ST'), 'the position filter returns only that position',
      'other positions present: ' + [...new Set(def.filter(d => d.pos !== 'D/ST').map(d => d.pos))].join(','))

    // ── "Their draft position is ESPN's published ADP" ────────────────────────
    const den = def.find(d => /Denver|DEN/.test(d.name))
    const publishedDenAdp = publishedDen && publishedDen.adp != null
      ? Number(publishedDen.adp).toFixed(1)
      : null
    check(
      den && publishedDenAdp != null && den.adp === publishedDenAdp,
      'D/ST carry published ADP (DEN matches API)',
      'DEN renders ADP=' + (den ? den.adp : 'ROW MISSING') +
        ', API publishes ' + (publishedDenAdp == null ? 'NO VALUE' : publishedDenAdp)
    )

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
    check(await page.evaluate(clickByText, 'All'), 'an All filter chip exists', 'no All chip')
    await page.waitForTimeout(700)
    const restored = await page.evaluate(readPool)
    check(restored.length > def.length, 'clearing the filter restores the full pool',
      'ALL returned ' + restored.length + ' rows against ' + def.length + ' filtered')
    const queuedBefore = await page.evaluate(queueTabCount)
    check(queuedBefore != null, 'the Queue tab carries a count', 'no queue count on the tab')
    check(await page.evaluate(openFirstPlayerCard), 'a pool row opens the player card', 'no player row')
    await page.waitForSelector('[role="dialog"] h2', { timeout: 30000 })
    await page.waitForTimeout(600)
    check(await page.evaluate(clickDialogQueue), 'the player card offers Queue', 'no Queue button on the card')
    await page.waitForTimeout(800)
    const queuedAfter = await page.evaluate(queueTabCount)
    check(queuedAfter === (queuedBefore || 0) + 1, 'queueing a player increments the Queue tab count',
      'count went ' + queuedBefore + ' → ' + queuedAfter)
    const bodyAfter = await page.locator('body').innerText()

    // ── "A board grid showing teams x rounds" ────────────────────────────────
    check(await page.evaluate(openBoardTab), 'the draft room has a Board tab', 'no Board tab')
    await page.waitForSelector('[data-testid="draft-board-grid"]', { timeout: 30000 })
    const board = await page.evaluate(boardShape)
    check(board != null, 'the board grid is on the page', 'no [data-testid="draft-board-grid"]')
    if (board) {
      check(board.rounds.length === 15, 'the board grid shows 15 rounds',
        'found ' + board.rounds.length + ' round rows')
      check(board.cols.length >= 11, 'the board grid shows every team',
        'found ' + (board.cols.length - 1) + ' team columns')
    }
    await page.evaluate(() => {
      const list = document.querySelector('[role="tablist"]')
      const tab = list && Array.from(list.querySelectorAll('[role="tab"]')).find(t => /^players/i.test(t.innerText.trim()))
      if (tab) tab.click()
    })
    await page.waitForSelector('[data-testid="pool-table"] tbody tr', { timeout: 30000 })

    // ── "A 30-second clock ... autopick when it expires" ─────────────────────
    await page.waitForTimeout(2600)
    const bodyLater = await page.locator('body').innerText()
    check(bodyLater !== bodyAfter, 'the clock is running',
      'page text is byte-identical across 2.6s — the clock may be frozen')

    // ── "Defenses are draftable" — the headline claim ────────────────────────
    await page.evaluate(clickByText, 'D/ST')
    await page.waitForTimeout(900)
    const drafted = await page.evaluate(draftFirstDST)
    check(drafted != null, 'a D/ST row offers a DRAFT control', 'no draftable D/ST row found')
    if (drafted) {
      await page.waitForTimeout(1800)
      // The roster is a tab now, not a permanent right-hand panel, so the claim
      // has to say where it is looking. It also gets stricter for free: the
      // defense must land in the D/ST STARTING slot, which is the bug that
      // shipped — buildRosterSlots stopped at K and a bot-drafted defense went
      // silently to the bench while the engine counted it as a starter.
      await page.evaluate(() => {
        const list = document.querySelector('[role="tablist"]')
        const tab = list && Array.from(list.querySelectorAll('[role="tab"]')).find(t => /^rosters/i.test(t.innerText.trim()))
        if (tab) tab.click()
      })
      await page.waitForTimeout(900)
      const slot = await page.evaluate(name => {
        const rows = Array.from(document.querySelectorAll('div'))
          .filter(d => d.children.length && /^(D\/ST|BE\d+)$/.test((d.firstElementChild.innerText || '').trim()))
        const row = rows.find(d => d.innerText.indexOf(name) !== -1)
        return row ? (row.firstElementChild.innerText || '').trim() : null
      }, drafted)
      check(slot === 'D/ST', 'the drafted D/ST lands in the starting D/ST slot',
        'drafted "' + drafted + '" and it is in slot ' + JSON.stringify(slot))
      notes.push('drafted ' + drafted + ' into ' + slot)
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
