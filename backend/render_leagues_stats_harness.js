// Deterministic player-stat category/sort/query harness for /leagues/[league].
const { chromium } = require('playwright')

const BASE = process.env.FRONTEND || 'http://127.0.0.1:3095'
const requests = []
const results = []
let failures = 0

const metric = (key, label, format) => ({ key, label, format })
const nbaCategories = [
  { key: 'scoring', label: 'Scoring', stats: [metric('pts', 'Points', 'decimal_1')] },
  { key: 'playmaking', label: 'Playmaking', stats: [metric('ast', 'Assists', 'decimal_1'), metric('tov', 'Turnovers', 'decimal_1')] },
  { key: 'rebounding', label: 'Rebounding', stats: [metric('reb', 'Rebounds', 'decimal_1')] },
  { key: 'defense', label: 'Defense', stats: [metric('stl', 'Steals', 'decimal_1')] },
  { key: 'efficiency', label: 'Efficiency', stats: [metric('ts_pct', 'TS%', 'percent_1'), metric('pts', 'Points', 'decimal_1'), metric('minutes', 'Minutes', 'decimal_1')] },
]
const battingCategories = [
  { key: 'production', label: 'Production', stats: [metric('avg', 'AVG', 'decimal_3'), metric('hr', 'HR', 'integer')] },
  { key: 'discipline', label: 'Discipline', stats: [metric('k_pct', 'K%', 'percent_1')] },
]
const pitchingCategories = [
  { key: 'strikeouts', label: 'Strikeouts', stats: [metric('k_pct', 'K%', 'percent_1'), metric('whiff_pct', 'Whiff%', 'percent_1')] },
  { key: 'contact_suppression', label: 'Contact Suppression', stats: [metric('xwoba_against', 'xwOBA Against', 'decimal_3')] },
]

function check(name, condition, detail = '') {
  results.push(`${condition ? 'PASS' : 'FAIL'}  ${name}${detail ? ` :: ${detail}` : ''}`)
  if (!condition) failures++
}

function leaderResponse(league, statType, categories, categoryKey, statKey) {
  const category = categories.find((item) => item.key === categoryKey)
  const values = {
    pts: 31.4, ast: 8.6, tov: 3.2, reb: 10.1, stl: 1.7,
    ts_pct: 61.2, minutes: 35.4, avg: 0.321, hr: 27,
    k_pct: 29.4, whiff_pct: 34.8, xwoba_against: 0.287,
  }
  return {
    league,
    season: 2026,
    stat: statKey,
    stat_type: statType,
    category: categoryKey,
    categories,
    columns: category.stats,
    leaders: [{ player_id: 7, name: 'Fixture Leader', team: 'TST', games: 50, ...values }],
  }
}

function requestAfter(index, predicate) {
  return requests.slice(index).find(predicate)
}

(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage()
  const pageErrors = []
  const consoleErrors = []
  page.on('pageerror', (error) => pageErrors.push(String(error.message || error)))
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const params = Object.fromEntries(url.searchParams.entries())
    requests.push({ path: url.pathname, params })

    if (url.pathname === '/api/nba/leaders') {
      if (params.category === 'invalid' || params.stat === 'invalid') {
        return route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({ detail: "Stat 'invalid' is unavailable for season 2026" }),
        })
      }
      const category = params.category || 'scoring'
      const selected = nbaCategories.find((item) => item.key === category) || nbaCategories[0]
      const stat = params.stat || selected.stats[0].key
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(leaderResponse('nba', null, nbaCategories, selected.key, stat)),
      })
    }

    if (url.pathname === '/api/mlb/leaders') {
      const pitching = params.type === 'pitching'
      const categories = pitching ? pitchingCategories : battingCategories
      const category = params.category || categories[0].key
      const selected = categories.find((item) => item.key === category) || categories[0]
      const stat = params.stat || selected.stats[0].key
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(leaderResponse('mlb', pitching ? 'pitching' : 'batting', categories, selected.key, stat)),
      })
    }

    return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })

  await page.goto(
    `${BASE}/leagues/nba?tab=stats&view=players&category=efficiency&stat=ts_pct`,
    { waitUntil: 'networkidle', timeout: 30000 },
  )
  await page.waitForFunction(() => document.body.innerText.includes('61.2%'))
  const nbaBody = await page.innerText('body')
  check(
    '[nba] deep link sends category and stat',
    requests.some(({ path, params }) => path === '/api/nba/leaders'
      && params.category === 'efficiency' && params.stat === 'ts_pct'),
    JSON.stringify(requests),
  )
  const categoryLabels = await page.locator('[aria-label="Player stat categories"] button').allTextContents()
  check('[nba] all returned categories render', ['Scoring', 'Playmaking', 'Rebounding', 'Defense', 'Efficiency'].every((label) => categoryLabels.includes(label)), JSON.stringify(categoryLabels))
  const columnHeaders = await page.getByRole('columnheader').allTextContents()
  check('[nba] only Efficiency metric columns render', ['TS%↓', 'Points', 'Minutes'].every((label) => columnHeaders.some((header) => header.includes(label))) && !columnHeaders.some((header) => /Assists|Turnovers/.test(header)), JSON.stringify(columnHeaders))
  check('[nba] percent format uses stored percent units', nbaBody.includes('61.2%'))
  check('[nba] TS% is descending sort', await page.getByRole('columnheader', { name: /TS%/ }).getAttribute('aria-sort') === 'descending')
  check('[nba] no pageerror', pageErrors.length === 0, pageErrors.join(' | '))
  check('[nba] no console.error', consoleErrors.length === 0, consoleErrors.join(' | '))

  let requestIndex = requests.length
  await page.getByRole('button', { name: 'Playmaking', exact: true }).click()
  await page.waitForURL('**/*stat=ast*')
  await page.waitForFunction(() => document.body.innerText.includes('8.6'))
  const playmakingRequests = requests.slice(requestIndex)
  check('[nba] category click sends no stale stat', !!requestAfter(requestIndex, ({ path, params }) => path === '/api/nba/leaders' && params.category === 'playmaking' && params.stat === undefined), JSON.stringify(playmakingRequests))
  check('[nba] backend default stat is written to URL', page.url().includes('category=playmaking') && page.url().includes('stat=ast'), page.url())

  requestIndex = requests.length
  await page.getByRole('button', { name: 'Turnovers', exact: true }).click()
  await page.waitForURL('**/*stat=tov*')
  check('[nba] metric click requests tov', !!requestAfter(requestIndex, ({ path, params }) => path === '/api/nba/leaders' && params.category === 'playmaking' && params.stat === 'tov'))
  check('[nba] metric URL retains Stats state', page.url().includes('tab=stats') && page.url().includes('view=players') && page.url().includes('category=playmaking'), page.url())

  requestIndex = requests.length
  await page.goto(
    `${BASE}/leagues/nba?tab=stats&view=players&category=invalid&stat=invalid`,
    { waitUntil: 'networkidle', timeout: 30000 },
  )
  await page.getByRole('button', { name: 'Reset stats filters' }).waitFor()
  check('[error] FastAPI detail is visible', (await page.innerText('body')).includes("Unable to load player stats: Stat 'invalid' is unavailable for season 2026"))
  await page.getByRole('button', { name: 'Reset stats filters' }).click()
  await page.waitForFunction(() => document.body.innerText.includes('Fixture Leader'))
  check('[error] reset makes an unfiltered leaders request', !!requestAfter(requestIndex, ({ path, params }) => path === '/api/nba/leaders' && params.category === undefined && params.stat === undefined), JSON.stringify(requests.slice(requestIndex)))
  check('[error] reset renders backend default', page.url().includes('category=scoring') && page.url().includes('stat=pts'), page.url())

  await page.goto(
    `${BASE}/leagues/mlb?tab=stats&view=players&type=batting&category=production&stat=avg`,
    { waitUntil: 'networkidle', timeout: 30000 },
  )
  await page.waitForFunction(() => document.body.innerText.includes('0.321'))
  requestIndex = requests.length
  await page.getByRole('button', { name: /^pitching$/i }).click()
  await page.waitForURL('**/*type=pitching*')
  await page.waitForFunction(() => document.body.innerText.includes('34.8%'))
  const typeSwitchRequests = requests.slice(requestIndex).filter(({ path }) => path === '/api/mlb/leaders')
  check(
    '[mlb] type switch clears batting category/stat before requesting',
    typeSwitchRequests.length > 0
      && typeSwitchRequests[0].params.type === 'pitching'
      && typeSwitchRequests[0].params.category === undefined
      && typeSwitchRequests[0].params.stat === undefined
      && !typeSwitchRequests.some(({ params }) => params.type === 'pitching' && (params.category === 'production' || params.stat === 'avg')),
    JSON.stringify(typeSwitchRequests),
  )
  const pitchingButtons = await page.locator('[aria-label="Player stat categories"] button').allTextContents()
  check('[mlb] pitching metadata renders', pitchingButtons.includes('Strikeouts') && pitchingButtons.includes('Contact Suppression') && (await page.innerText('body')).includes('Whiff%'))

  await page.goto(
    `${BASE}/leagues/mlb?tab=stats&view=invalid&type=invalid`,
    { waitUntil: 'networkidle', timeout: 30000 },
  )
  await page.waitForFunction(() => document.body.innerText.includes('Fixture Leader'))
  check('[query] invalid MLB view/type canonicalize', page.url().includes('view=players') && page.url().includes('type=batting'), page.url())
  check('[query] canonical request uses batting', requests.some(({ path, params }) => path === '/api/mlb/leaders' && params.type === 'batting'))

  await page.goto(
    `${BASE}/leagues/nba?tab=stats&view=invalid&type=pitching`,
    { waitUntil: 'networkidle', timeout: 30000 },
  )
  await page.waitForFunction(() => document.body.innerText.includes('Fixture Leader'))
  check('[query] non-MLB canonicalization removes type', page.url().includes('view=players') && !page.url().includes('type='), page.url())

  await browser.close()
  console.log('\n=== LEAGUES STATS RESULTS ===')
  console.log(results.join('\n'))
  console.log(`\nTOTAL: ${results.length} checks, ${failures} FAILURES`)
  process.exit(failures === 0 ? 0 : 1)
})().catch((error) => {
  console.error('HARNESS ERROR', error)
  process.exit(2)
})
