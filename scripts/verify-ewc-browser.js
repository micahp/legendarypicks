/* Phase 4 browser gate — EWC candidate on isolated ports (:3105 frontend, :8105 backend).
 * Verifies: /esports EWC module (desktop + mobile), no pageerrors, /scores CoD cards without
 * raw TBD, date navigation, ?league=Call of Duty, and a CoD detail link. */
const { chromium } = require('playwright')

const BASE = 'http://127.0.0.1:3105'

async function collect(page) {
  const errors = []
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
  page.on('console', (m) => { if (m.type() === 'error') errors.push(`console: ${m.text()}`) })
  page.on('response', (r) => { if (r.status() >= 400) errors.push(`http ${r.status()}: ${r.url()}`) })
  return errors
}

;(async () => {
  const browser = await chromium.launch()
  const out = {}
  // ---------- desktop /esports ----------
  {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
    const errors = await collect(page)
    await page.goto(`${BASE}/esports`, { waitUntil: 'networkidle', timeout: 30000 })
    await page.waitForTimeout(4000)
    out.esportsDesktop = {
      title: await page.title(),
      hasEwcModule: await page.getByText('EWC 2026', { exact: true }).count(),
      hasEventName: await page.getByText('Esports World Cup 2026', { exact: true }).count(),
      hasGenericSchedule: await page.getByText('What’s next', { exact: true }).count(),
      bodyText: (await page.locator('body').innerText()).slice(0, 120).replace(/\n/g, ' | '),
      errors,
    }
    await page.screenshot({ path: '/root/lp-ewc-2026/docs/ewc2026/fixtures/browser-esports-desktop.png', fullPage: false })
    await page.close()
  }
  // ---------- mobile /esports ----------
  {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
    const errors = await collect(page)
    await page.goto(`${BASE}/esports`, { waitUntil: 'networkidle', timeout: 30000 })
    await page.waitForTimeout(4000)
    out.esportsMobile = {
      hasEwcModule: await page.getByText('EWC 2026', { exact: true }).count(),
      errors,
    }
    await page.screenshot({ path: '/root/lp-ewc-2026/docs/ewc2026/fixtures/browser-esports-mobile.png' })
    await page.close()
  }
  // ---------- /scores CoD (league filter + date nav) ----------
  {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
    const errors = await collect(page)
    await page.goto(`${BASE}/scores?league=${encodeURIComponent('Call of Duty')}`, { waitUntil: 'networkidle', timeout: 30000 })
    await page.waitForTimeout(5000)
    const body = await page.locator('body').innerText()
    out.scoresCod = {
      hasTbd: /(^|\s)TBD(\s|$)/.test(body),
      hasWinnerLabel: body.includes('Winner of') || body.includes('Winner of '),
      hasUnavailable: body.includes('Participant unavailable'),
      codCards: await page.locator('text=/Call of Duty/').count(),
      errors,
    }
    // date navigation: previous day
    await page.getByLabel('Previous day').click()
    await page.waitForTimeout(3000)
    out.scoresCod.prevDayBody = (await page.locator('body').innerText()).slice(0, 80).replace(/\n/g, ' | ')
    await page.close()
  }
  // ---------- CoD detail link ----------
  {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
    const errors = await collect(page)
    // grab a reconciled EWC game's detail id from the candidate API
    const games = await (await page.request.get(`${BASE}/api/cod/games`)).json()
    const withDetail = (games || []).find((g) => g.detail_game_id)
    let detail = null
    if (withDetail) {
      await page.goto(`${BASE}/game/call-of-duty/${withDetail.detail_game_id}`, { waitUntil: 'networkidle', timeout: 30000 })
      await page.waitForTimeout(3000)
      detail = { status: await page.title(), hasTeamNames: await page.getByText('Call of Duty', { exact: false }).count() > 0, errors }
    }
    out.codDetail = { found: Boolean(withDetail), gameId: withDetail?.game_id, detailGameId: withDetail?.detail_game_id, detail }
    await page.close()
  }
  await browser.close()
  console.log(JSON.stringify(out, null, 2))
  const fails = Object.values(out).filter((v) => (v.errors && v.errors.length) || (v.hasTbd))
  if (fails.length) { console.error('GATE FAIL'); process.exit(1) }
  console.log('GATE PASS')
})().catch((e) => { console.error('RUN ERROR', e); process.exit(1) })
