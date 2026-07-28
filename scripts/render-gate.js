#!/usr/bin/env node
/**
 * REG-render — the gate that eight green gates were missing.
 *
 * On 2026-07-28 the draft pool crashed on first render while A1/A1b/A2/A3/B1/B2/B2b/B4
 * were all PASS. Every one of those assertions was true. Not one of them rendered React.
 * Two further bugs — a clock deadlock that ran a 180-pick draft in 40 seconds, and a camp
 * tab whose board was never wired to its hook — were found only by hand-driving a browser.
 *
 * So this gate drives a real browser and holds to two rules the others could not:
 *
 *   1. A 200 is not a render. Every check below requires React to have mounted AND
 *      responded to an interaction. HTML that Next.js server-rendered before the client
 *      threw would satisfy a curl; it will not satisfy a click.
 *   2. Evidence unavailable is a FAIL, never a skip. If the frontend is down, if chromium
 *      will not launch, if a selector never appears — this exits non-zero and says why.
 *      A gate that cannot run has not passed.
 *
 * Any console error or uncaught page error on any surface fails the gate outright. The
 * bugs above all announced themselves in the console; nothing was watching.
 *
 * Usage:  node scripts/render-gate.js            (defaults to :3098)
 *         LP_GATE_F=http://127.0.0.1:3093 node scripts/render-gate.js
 */

const BASE = process.env.LP_GATE_F || 'http://127.0.0.1:3098'
const NAV_TIMEOUT = 120000
const SEL_TIMEOUT = 60000

let chromium
try {
  ;({ chromium } = require('/root/legendarypicks/node_modules/playwright'))
} catch (_) {
  try {
    ;({ chromium } = require('playwright'))
  } catch (e) {
    console.log('FAIL REG-render  (playwright not resolvable: ' + e.message + ')')
    process.exit(1)
  }
}

const failures = []
const notes = []
function check(cond, id, detail) {
  if (!cond) failures.push(id + ': ' + detail)
  return cond
}

;(async () => {
  let browser
  try {
    browser = await chromium.launch()
  } catch (e) {
    console.log('FAIL REG-render  (chromium will not launch: ' + e.message + ')')
    process.exit(1)
  }

  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const consoleErrors = []
  page.on('console', m => {
    if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200))
  })
  page.on('pageerror', e => consoleErrors.push('UNCAUGHT: ' + e.message.slice(0, 200)))

  // ── Surface 1: /mock-draft — pool renders, draft starts, a row opens the overlay ──
  try {
    await page.goto(BASE + '/mock-draft', { waitUntil: 'networkidle', timeout: NAV_TIMEOUT })

    // React mounted and the pool loaded: the start control is the client-rendered proof.
    const start = page.getByRole('button', { name: 'Start Draft' })
    await start.waitFor({ timeout: SEL_TIMEOUT })
    await start.click()

    await page.waitForSelector('table tbody tr', { timeout: SEL_TIMEOUT })
    const poolRows = await page.locator('table tbody tr').count()
    check(poolRows > 50, 'mock-draft', 'only ' + poolRows + ' pool rows rendered')

    // The overlay is client-only. If the client threw, this click does nothing.
    //
    // Read the name and click in ONE evaluate: bots draft while the clock runs, so the
    // pool re-renders between a separate read and click and the gate opens a different
    // player than it measured. That race is also a real product hazard (B18) — but a
    // gate must fail for the reason it names, so it is removed here rather than tolerated.
    // Row 120 is deep enough that no bot reaches it during the run.
    const rowName = await page.evaluate(() => {
      const rows = document.querySelectorAll('table tbody tr')
      const row = rows[Math.min(120, rows.length - 1)]
      if (!row) return null
      const name = row.querySelectorAll('td')[1].innerText.split('\n')[0].trim()
      row.click()
      return name
    })
    check(rowName != null, 'mock-draft', 'no pool row available to click')
    // Wait for the dialog to have LOADED, not merely to exist. It mounts instantly with a
    // loading skeleton, so asserting against it the moment [role="dialog"] appears reads an
    // empty card and fails for the wrong reason — presence is not integrity, and this gate
    // is not exempt from that.
    const dialog = page.locator('[role="dialog"]')
    await dialog.waitFor({ timeout: 15000 })
    await dialog.locator('h2').waitFor({ timeout: 15000 })
    await page.waitForFunction(
      () => {
        const h = document.querySelector('[role="dialog"] h2')
        return h && h.innerText.trim().length > 0
      },
      null,
      { timeout: 15000 }
    )
    const dialogText = await dialog.innerText()
    check(
      dialogText.includes(rowName),
      'mock-draft',
      'overlay opened but does not name the clicked player (' + rowName + ')'
    )
    check(
      !/Failed to load player/i.test(dialogText),
      'mock-draft',
      'overlay rendered its error state'
    )
    notes.push('mock-draft ' + poolRows + ' rows, overlay=' + JSON.stringify(rowName))
    await page.keyboard.press('Escape').catch(() => {})
  } catch (e) {
    failures.push('mock-draft: ' + e.message.split('\n')[0])
  }

  // ── Surface 2: /leagues/nfl?tab=camp — the board that silently died once ──
  try {
    await page.goto(BASE + '/leagues/nfl?tab=camp', {
      waitUntil: 'networkidle',
      timeout: NAV_TIMEOUT,
    })

    const body = await page.locator('body').innerText()
    check(
      !/Draft board unavailable/i.test(body),
      'camp-tab',
      'board shows "Draft board unavailable" — the hook is not wired'
    )

    await page.waitForSelector('table tbody tr', { timeout: SEL_TIMEOUT })
    const boardRows = await page.locator('table tbody tr').count()
    check(boardRows > 10, 'camp-tab', 'only ' + boardRows + ' board rows rendered')

    // Position filters must actually re-render the table, not just repaint a pill.
    const pills = page.locator('[role="radio"]')
    const pillCount = await pills.count()
    check(pillCount >= 9, 'camp-tab', 'expected 9 position pills, found ' + pillCount)

    const shape = {}
    for (const [label, idx] of [['DEF', 7], ['PK', 8]]) {
      await pills.nth(idx).click()
      await page.waitForFunction(
        expected => {
          const first = document.querySelector('table tbody tr td:nth-child(3)')
          return first && first.innerText.trim() === expected
        },
        label,
        { timeout: 30000 }
      )
      const headers = await page.locator('table thead th').allInnerTexts()
      const rows = await page.locator('table tbody tr').count()
      shape[label] = { cols: headers.length, rows }
      check(rows === 32, 'camp-tab', label + ' filter returned ' + rows + ' rows, expected 32')
      // Position-aware columns (4b21d09): a specialised filter must be narrower
      // than the mixed view, or the specialisation silently regressed.
      check(
        headers.length <= 11,
        'camp-tab',
        label + ' shows ' + headers.length + ' columns — position-aware columns regressed'
      )
    }
    notes.push(
      'camp-tab ' + boardRows + ' rows, DEF=' + JSON.stringify(shape.DEF) +
      ' PK=' + JSON.stringify(shape.PK)
    )
  } catch (e) {
    failures.push('camp-tab: ' + e.message.split('\n')[0])
  }

  await browser.close()

  if (consoleErrors.length) {
    failures.push(
      consoleErrors.length + ' console/page error(s), first: ' + consoleErrors[0]
    )
  }

  if (failures.length === 0) {
    console.log('PASS REG-render  (' + notes.join(' · ') + ')')
    process.exit(0)
  }
  console.log('FAIL REG-render  (' + failures.join(' | ') + ')')
  process.exit(1)
})().catch(e => {
  console.log('FAIL REG-render  (gate itself threw: ' + e.message.split('\n')[0] + ')')
  process.exit(1)
})
