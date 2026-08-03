/* Does the fantasy game log still scroll sideways?
 *
 * The brief was "it was nice not to have to scroll to see all the stats", and it
 * has been declared fixed twice off things that are not that: a column list and
 * a card width. This opens the real overlay in a real browser, at the width a
 * phone gives it, and measures scrollWidth against clientWidth on the actual
 * scroll container — the only measurement that answers the question asked.
 *
 * Note the two tablists: the overlay's own strip (Overview | Game log | News |
 * Projections) and the game log's inner one, which carries aria-label
 * "Game log stats". Matching the first one measures the wrong table.
 */
const { chromium } = require('/root/legendarypicks/node_modules/playwright')

const BASE = process.env.LP_GATE_F || 'http://127.0.0.1:3096'
const results = []
const check = (ok, what) => results.push({ ok, what })

async function measure(scope) {
  return scope.evaluate(node => {
    const table = node.querySelector('table')
    if (!table) return null
    let box = table.parentElement
    while (box && getComputedStyle(box).overflowX !== 'auto') box = box.parentElement
    box = box || table.parentElement
    return {
      scrollWidth: box.scrollWidth,
      clientWidth: box.clientWidth,
      cols: table.querySelectorAll('thead th').length,
      headers: [...table.querySelectorAll('thead th')].map(th => th.innerText.trim()),
    }
  })
}

;(async () => {
  const browser = await chromium.launch()
  for (const [label, viewport] of [
    ['phone 390', { width: 390, height: 844 }],
    ['desktop 1280', { width: 1280, height: 900 }],
  ]) {
    const page = await browser.newPage({ viewport })
    const errors = []
    page.on('pageerror', e => errors.push(String(e)))
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })

    await page.goto(BASE + '/mock-draft', { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('table tbody tr', { timeout: 60000 })
    await page.locator('table tbody tr').first().click()
    const dialog = page.locator('[role="dialog"]').first()
    await dialog.waitFor({ timeout: 30000 })

    // The Overview table is what opens by default — measure it too, it is the
    // first thing a user sees. RED ON PURPOSE as of 2026-08-03: SEASON STATS is
    // ten columns and 560px wide, which is 254px past a phone and 92px past the
    // desktop card. The game log was fixed with tabs; this one is a single
    // season row, so tabs are the wrong instrument and the fix is a product
    // decision. Do not relax this to make the gate green.
    await dialog.locator('table').first().waitFor({ timeout: 30000 })
    await page.waitForTimeout(1200)
    const overview = await measure(dialog)
    if (overview) {
      const over = overview.scrollWidth - overview.clientWidth
      check(over <= 1, `${label}/Overview(season stats): ${overview.cols} cols ` +
        `[${overview.headers.join(' ')}] ${overview.scrollWidth}px in ${overview.clientWidth}px` +
        (over > 1 ? `  <-- OVERFLOWS BY ${over}px` : ''))
    } else {
      check(false, `${label}/Overview: no table rendered at all`)
    }

    await dialog.getByText(/^game log$/i).first().click()
    const inner = dialog.locator('[role="tablist"][aria-label="Game log stats"]')
    try {
      await inner.waitFor({ timeout: 30000 })
    } catch {
      check(false, `${label}: game log never rendered its tab strip`)
      await page.close(); continue
    }
    await dialog.locator('table tbody tr').first().waitFor({ timeout: 30000 })

    const tabs = inner.locator('[role="tab"]')
    const labels = (await tabs.allInnerTexts()).map(s => s.trim())
    check(labels.length >= 2, `${label}: game log tabs [${labels.join(' | ')}]`)

    for (let i = 0; i < labels.length; i++) {
      await tabs.nth(i).click()
      await page.waitForTimeout(200)
      const m = await measure(dialog)
      if (!m) { check(false, `${label}/${labels[i]}: no table`); continue }
      const over = m.scrollWidth - m.clientWidth
      check(over <= 1,
        `${label}/${labels[i]}: ${m.cols} cols [${m.headers.join(' ')}] ` +
        `${m.scrollWidth}px in ${m.clientWidth}px` +
        (over > 1 ? `  <-- OVERFLOWS BY ${over}px` : ''))
      check(m.cols <= 8, `${label}/${labels[i]}: ${m.cols} columns (budget 8)`)
      check((await tabs.nth(i).getAttribute('aria-selected')) === 'true',
        `${label}/${labels[i]}: aria-selected set on click`)
    }

    check(errors.length === 0,
      `${label}: page errors ${errors.length ? JSON.stringify(errors.slice(0, 2)) : 'none'}`)
    await page.close()
  }
  await browser.close()

  const failed = results.filter(r => !r.ok)
  for (const r of results) console.log(`${r.ok ? 'ok  ' : 'FAIL'} ${r.what}`)
  console.log(`\n── ${results.length - failed.length} passed, ${failed.length} failed ──`)
  process.exit(failed.length ? 1 : 0)
})().catch(e => { console.log('PROBE DIED: ' + e.message); process.exit(2) })
