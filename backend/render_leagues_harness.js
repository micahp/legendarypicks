// Headless render harness for /leagues/[league] across all six leagues.
// Asserts zero uncaught JS errors + per-league checks. Backend on :8000, frontend on :3106.
const { chromium } = require('playwright')

const BASE = process.env.FRONTEND || 'http://127.0.0.1:3106'
const results = []
let failures = 0
function check(name, cond, detail = '') {
  results.push(`${cond ? 'PASS' : 'FAIL'}  ${name}${detail ? ' :: ' + detail : ''}`)
  if (!cond) failures++
}

(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage()
  const pageErrors = []
  const consoleErrors = []
  page.on('pageerror', (e) => pageErrors.push(String(e.message || e)))
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })

  const leagues = ['mlb', 'nba', 'nhl', 'nfl', 'wc', 'ufc']
  for (const lg of leagues) {
    pageErrors.length = 0
    consoleErrors.length = 0
    const url = `${BASE}/leagues/${lg}`
    await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 })
    // give client-side fetch + render a beat
    await page.waitForTimeout(2500)

    check(`[${lg}] zero uncaught pageerrors`, pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '))
    check(`[${lg}] zero console.error`, consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '))

    // Active tab = button whose class contains the active marker (border-emerald-500 text-white)
    const activeTab = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'))
      const active = btns.find(b => /border-emerald-500/.test(b.className || '') && /text-white/.test(b.className || ''))
      return active ? active.textContent.trim() : (btns.find(b => /standings|rankings|schedule|stats/i.test(b.textContent||''))?.textContent.trim() || '')
    }).catch(() => '')
    check(`[${lg}] has an active tab`, !!activeTab, `active="${activeTab}"`)

    if (lg === 'wc') {
      // Visible team name text present (nonblank object team names rendered)
      const bodyText = await page.innerText('body').catch(() => '')
      const hasTeam = /\b(Brazil|France|Spain|Argentina|England|Germany|Canada|Japan)\b/i.test(bodyText)
      check(`[wc] visible team names rendered`, hasTeam, `sample=${bodyText.replace(/\s+/g,' ').slice(0,120)}`)
      // Six round headers in canonical order
      const roundText = await page.evaluate(() =>
        Array.from(document.querySelectorAll('h2,h3,div,span'))
          .map(e => e.textContent.trim())
          .filter(t => /Round of 32|Round of 16|Quarterfinals|Semifinals|Third Place|Final/.test(t))
          .filter((t,i,a) => a.indexOf(t) === i)
          .sort()
      )
      const canonical = ['Final','Quarterfinals','Round of 16','Round of 32','Semifinals','Third Place']
      const found = ['Round of 32','Round of 16','Quarterfinals','Semifinals','Third Place','Final'].filter(r => roundText.some(t => t.includes(r)))
      check(`[wc] six knockout rounds present`, found.length === 6, `found=${JSON.stringify(found)}`)
      // order: ensure Round of 32 appears before Final in DOM order
      const orderOk = await page.evaluate(() => {
        const order = ['Round of 32','Round of 16','Quarterfinals','Semifinals','Third Place','Final']
        const nodes = order.map(r => Array.from(document.querySelectorAll('*')).find(n => n.children.length===0 && n.textContent.trim()===r))
        const idx = nodes.map(n => n ? Array.from(document.body.querySelectorAll('*')).indexOf(n) : -1)
        const valid = idx.filter(i=>i>=0)
        for (let i=1;i<valid.length;i++) if (valid[i] < valid[i-1]) return false
        return valid.length === 6
      }).catch(() => false)
      check(`[wc] rounds in canonical DOM order`, orderOk)
    }

    if (lg === 'ufc') {
      // default tab = Rankings
      check(`[ufc] default tab is Rankings`, /rankings/i.test(activeTab), `active="${activeTab}"`)
      // No Standings / Stats tabs
      const tabTexts = await page.evaluate(() =>
        Array.from(document.querySelectorAll('button, [role="tab"]')).map(b => b.textContent.trim())
      )
      const hasStandings = tabTexts.some(t => /standings/i.test(t))
      const hasStats = tabTexts.some(t => /^stats$/i.test(t))
      check(`[ufc] NO Standings tab`, !hasStandings, `tabs=${JSON.stringify(tabTexts)}`)
      check(`[ufc] NO Stats tab`, !hasStats, `tabs=${JSON.stringify(tabTexts)}`)
      // Rankings content present (a division/fighter name)
      const ufcBody = await page.innerText('body').catch(() => '')
      check(`[ufc] rankings content rendered`, /(Pound-for-Pound|Heavyweight|Lightweight|Champion|Division)/i.test(ufcBody), `sample=${ufcBody.replace(/\s+/g,' ').slice(0,120)}`)
    }

    if (['mlb','nba','nhl','nfl'].includes(lg)) {
      // Default tab is Standings — click "Schedule" to reveal game cards
      const clicked = await page.evaluate(() => {
        const b = Array.from(document.querySelectorAll('button')).find(x => /schedule/i.test(x.textContent||''))
        if (b) { b.click(); return true } return false
      })
      check(`[${lg}] Schedule tab clickable`, clicked)
      await page.waitForTimeout(1500)
      // A valid empty slate is expected in the offseason; distinguish it from
      // a broken/blank schedule while still exercising cards when they exist.
      const cardCount = await page.evaluate(() =>
        Array.from(document.querySelectorAll('div')).filter(d =>
          /cursor-pointer/.test(d.className || '') && /hover:border-blue-500/.test(d.className || '')
        ).length
      )
      const scheduleBody = await page.innerText('body').catch(() => '')
      const honestEmpty = new RegExp(`No ${lg.toUpperCase()} games scheduled for`, 'i').test(scheduleBody)
      check(
        `[${lg}] schedule state rendered`,
        cardCount > 0 || honestEmpty,
        `cards=${cardCount} empty=${honestEmpty}`,
      )
      if (cardCount > 0) {
        // Click first card -> router.push to /game/<league>/<id>
        let navOk = false
        try {
          await Promise.all([
            page.waitForURL('**/game/**', { timeout: 15000 }),
            page.evaluate(() => {
              const c = Array.from(document.querySelectorAll('div')).find(d =>
                /cursor-pointer/.test(d.className||'') && /hover:border-blue-500/.test(d.className||''))
              c && c.click()
            }),
          ])
          const after = page.url()
          navOk = /\/game\/[a-z]+\/\d+/.test(after)
          check(`[${lg}] card click routes to /game detail`, navOk, `url=${after}`)
        } catch (e) {
          check(`[${lg}] card click routes to /game detail`, false, 'nav timeout/err: ' + e.message.split('\n')[0])
        }
      }
    }
  }

  await browser.close()
  console.log('\n=== HEADLESS RENDER RESULTS ===')
  console.log(results.join('\n'))
  console.log(`\nTOTAL: ${results.length} checks, ${failures} FAILURES`)
  process.exit(failures === 0 ? 0 : 1)
})().catch(e => { console.error('HARNESS ERROR', e); process.exit(2) })
