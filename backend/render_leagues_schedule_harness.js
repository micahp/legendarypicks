// Deterministic Schedule UX harness for /leagues/[league].
// Keeps render_leagues_harness.js as the live-backend integration check.
const { chromium } = require('playwright')

const BASE = process.env.FRONTEND || 'http://127.0.0.1:3106'
const FIXTURE_DATE = '2026-07-18'
const EMPTY_DATE = '2026-07-19'
const ERROR_DATE = '2026-07-20'
const UFC_START = `${FIXTURE_DATE}T23:30:00Z`
const requestedSchedule = []
const results = []
let failures = 0

function check(name, condition, detail = '') {
  results.push(`${condition ? 'PASS' : 'FAIL'}  ${name}${detail ? ` :: ${detail}` : ''}`)
  if (!condition) failures++
}

async function activeTab(page) {
  return page.evaluate(() => {
    const active = Array.from(document.querySelectorAll('button')).find(
      (button) => /border-emerald-500/.test(button.className || '')
        && /text-white/.test(button.className || '')
    )
    return active ? active.textContent.trim() : ''
  })
}

(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage()

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const gameMatch = path.match(/^\/api\/(ufc|wc)\/games$/)
    if (gameMatch) {
      const league = gameMatch[1]
      const date = url.searchParams.get('date') || ''
      requestedSchedule.push({ league, date })
      if (date === ERROR_DATE) {
        return route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: '{"detail":"fixture outage"}',
        })
      }
      const games = date === EMPTY_DATE ? [] : [{
        game_id: league === 'ufc' ? '901' : '902',
        date: league === 'ufc' ? UFC_START : `${FIXTURE_DATE}T18:00:00Z`,
        state: 'pre',
        subtitle: league === 'wc' ? 'Group Stage' : undefined,
        card_segment: league === 'ufc' ? 'UFC 999 Main Card' : undefined,
        home: { abbrev: 'HOM', name: league === 'ufc' ? 'Blue Fighter' : 'Home Team' },
        away: { abbrev: 'AWY', name: league === 'ufc' ? 'Red Fighter' : 'Away Team' },
      }]
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(games),
      })
    }
    if (path === '/api/ufc/rankings') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          pound_for_pound: {
            men: [{ rank: 1, fighter: 'Test Man' }],
            women: [{ rank: 1, fighter: 'Test Woman' }],
          },
          divisions: [],
        }),
      })
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })

  await page.goto(
    `${BASE}/leagues/ufc?tab=schedule&date=${FIXTURE_DATE}`,
    { waitUntil: 'networkidle', timeout: 30000 }
  )
  await page.waitForFunction(() => document.body.innerText.includes('UFC 999 Main Card'))
  const deepLinkBody = await page.innerText('body')
  check('[schedule] deep link activates Schedule', await activeTab(page) === 'Schedule')
  check('[schedule] selected date including year is visible', /Jul.*18.*2026|18.*Jul.*2026/.test(deepLinkBody))
  check('[schedule] timezone context is visible', /Times shown in your local time \([^)]+\)/.test(deepLinkBody))
  check('[schedule] UFC subtitle group is visible', deepLinkBody.includes('UFC 999 Main Card'))
  check(
    '[schedule] requested deep-link date',
    requestedSchedule.some(({ league, date }) => league === 'ufc' && date === FIXTURE_DATE),
    JSON.stringify(requestedSchedule)
  )
  const expectedUfcTime = await page.evaluate(
    (start) => new Date(start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    UFC_START
  )
  check('[schedule] UFC event exposes scheduled local time', deepLinkBody.includes(expectedUfcTime))

  await page.locator('input[aria-label="Choose schedule date"]').fill(EMPTY_DATE)
  await page.waitForFunction(() => document.body.innerText.includes('No UFC games scheduled for'))
  const emptyBody = await page.innerText('body')
  check(
    '[schedule] date input requests selected day',
    requestedSchedule.some(({ league, date }) => league === 'ufc' && date === EMPTY_DATE),
    JSON.stringify(requestedSchedule)
  )
  check('[schedule] empty copy includes chosen date', /No UFC games scheduled for .*Jul.*19.*2026|No UFC games scheduled for .*19.*Jul.*2026/.test(emptyBody))
  check('[schedule] URL retains tab and date', page.url().includes('tab=schedule') && page.url().includes(`date=${EMPTY_DATE}`))

  const requestCount = requestedSchedule.length
  await page.getByRole('button', { name: 'Previous day' }).click()
  await page.waitForFunction(() => document.body.innerText.includes('UFC 999 Main Card'))
  const previousValue = await page.locator('input[aria-label="Choose schedule date"]').inputValue()
  check(
    '[schedule] previous day requests and renders the prior day',
    requestedSchedule.slice(requestCount).some(({ league, date }) => league === 'ufc' && date === FIXTURE_DATE)
      && previousValue === FIXTURE_DATE,
    JSON.stringify(requestedSchedule.slice(requestCount))
  )

  await page.locator('input[aria-label="Choose schedule date"]').fill(ERROR_DATE)
  await page.waitForFunction(() => document.body.innerText.includes('Unable to load schedule.'))
  const errorBody = await page.innerText('body')
  check('[schedule] failure is distinct from empty', !errorBody.includes('No UFC games scheduled'))

  await page.goto(
    `${BASE}/leagues/wc?tab=schedule&date=${FIXTURE_DATE}`,
    { waitUntil: 'networkidle', timeout: 30000 }
  )
  await page.waitForFunction(() => document.body.innerText.includes('Group Stage'))
  check(
    '[wc] Schedule renders real backend subtitle context',
    (await page.innerText('body')).includes('Group Stage')
      && requestedSchedule.some(({ league, date }) => league === 'wc' && date === FIXTURE_DATE)
  )

  await page.goto(`${BASE}/leagues/nba?tab=stats`, { waitUntil: 'networkidle', timeout: 30000 })
  const usedClientRouter = await page.evaluate(async () => {
    const nextRouter = window.next && window.next.router
    if (!nextRouter) return false
    await nextRouter.push('/leagues/ufc?tab=stats')
    return true
  })
  check('[tabs] client router available for league-switch regression', usedClientRouter)
  if (usedClientRouter) {
    await page.waitForURL('**/leagues/ufc?**', { timeout: 15000 })
    await page.waitForFunction(() => document.body.innerText.includes("Men's"))
    check('[tabs] UFC rejects retained Stats tab', await activeTab(page) === 'Rankings', page.url())
  }

  await browser.close()
  console.log('\n=== LEAGUES SCHEDULE RESULTS ===')
  console.log(results.join('\n'))
  console.log(`\nTOTAL: ${results.length} checks, ${failures} FAILURES`)
  process.exit(failures === 0 ? 0 : 1)
})().catch((error) => {
  console.error('HARNESS ERROR', error)
  process.exit(2)
})
