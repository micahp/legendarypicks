#!/usr/bin/env node
/** Public, read-only end-to-end gate for Props and the UFC optimizer.
 *
 * Usage:
 *   LP_PUBLIC_BASE=https://example.trycloudflare.com node scripts/e2e-props-optimizer.js
 *
 * The gate discovers a current alternate-line example from the API instead of
 * pinning a player who will disappear from the next slate. Evidence unavailable
 * is a failure. It performs no writes and imports no CSV.
 */
const { chromium } = require('playwright')

const BASE = (process.env.LP_PUBLIC_BASE || 'https://coins-gold-future-catering.trycloudflare.com').replace(/\/$/, '')
const TIMEOUT = 120000
const failures = []
const evidence = []

function check(value, claim) {
  if (!value) failures.push(claim)
}

async function api(page, path) {
  return page.evaluate(async endpoint => {
    const response = await fetch(endpoint)
    const body = await response.json().catch(() => null)
    return { ok: response.ok, status: response.status, body }
  }, path)
}

async function findAlternateExample(page) {
  const summary = await api(page, '/api/props/slate?summary=1')
  if (!summary.ok || !Array.isArray(summary.body)) return null
  for (const game of summary.body.slice(0, 30)) {
    const detail = await api(page, `/api/props/slate?game_id=${game.game_id}`)
    const full = detail.ok && Array.isArray(detail.body) ? detail.body[0] : null
    for (const player of full?.players || []) {
      const markets = new Map()
      for (const prop of player.props || []) {
        const market = String(prop.market || '').split('___')[0].toLowerCase()
        const offers = markets.get(market) || new Map()
        const key = `${prop.line}|${prop.source}`
        const sides = offers.get(key) || new Set()
        sides.add(String(prop.side).toLowerCase())
        offers.set(key, sides)
        markets.set(market, offers)
      }
      for (const [market, offers] of markets) {
        if (offers.size > 1 && Array.from(offers.values()).some(sides =>
          sides.has('over') && sides.has('under'))) {
          return { gameId: game.game_id, player: player.name, market, offerCount: offers.size }
        }
      }
    }
  }
  return null
}

;(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const runtimeErrors = []
  const relevantApiFailures = []
  page.on('pageerror', error => runtimeErrors.push(error.message))
  page.on('console', message => {
    if (message.type() === 'error') runtimeErrors.push(message.text())
  })
  page.on('response', response => {
    if (response.url().includes('/api/') && response.status() >= 500) {
      relevantApiFailures.push(`${response.status()} ${response.url()}`)
    }
  })

  try {
    // Optimizer: rendered state must agree with the same current-pool API the
    // component consumes. A past embedded card is forbidden in either branch.
    await page.goto(`${BASE}/leagues/ufc?tab=optimizer`, { waitUntil: 'domcontentloaded', timeout: TIMEOUT })
    await page.getByRole('heading', { name: 'UFC Lineup Optimizer' }).waitFor({ timeout: TIMEOUT })
    const pool = await api(page, '/api/ufc/draftkings-pool')
    check(pool.ok, `current DraftKings pool API returned ${pool.status}`)
    if (pool.body?.slate) {
      await page.getByText(pool.body.slate.sourceName, { exact: true }).waitFor({ timeout: TIMEOUT })
      const starts = pool.body.slate.fighters.map(fighter => Date.parse(fighter.startTime)).filter(Number.isFinite)
      check(starts.length === pool.body.slate.fighters.length, 'current optimizer pool has missing start times')
      check(Math.min(...starts) > Date.now(), 'optimizer rendered a pool after its first lock')
      const perFight = new Map()
      pool.body.slate.fighters.forEach(fighter => perFight.set(
        fighter.gameInfo, (perFight.get(fighter.gameInfo) || 0) + 1,
      ))
      check(Array.from(perFight.values()).every(count => count === 2), 'optimizer pool has a one-sided fight')
      evidence.push(`optimizer=current ${pool.body.slate.fighters.length} fighters/${perFight.size} fights`)
    } else {
      await page.getByText('DraftKings MMA pool not available yet', { exact: true }).waitFor({ timeout: TIMEOUT })
      evidence.push(`optimizer=unavailable (${pool.body?.reason || 'no reason'})`)
    }
    check(!(await page.locator('body').innerText()).includes('August 29 DraftKings Classic'),
      'optimizer still rendered the expired August 29 card')

    // Slate: discover a live multi-line player/market and prove it renders as
    // one row, one line dropdown, and one OVER/UNDER pair.
    await page.goto(`${BASE}/props`, { waitUntil: 'domcontentloaded', timeout: TIMEOUT })
    await page.locator('[data-slate-game]').first().waitFor({ timeout: TIMEOUT })
    const example = await findAlternateExample(page)
    check(example, 'no current multi-line slate example was discoverable')
    if (example) {
      const game = page.locator(`[data-slate-game-id="${example.gameId}"]`)
      await game.getByRole('button').first().click()
      const player = game.locator(`[data-slate-player="${example.player.replace(/"/g, '\\"')}"]`)
      await player.waitFor({ timeout: TIMEOUT })
      const row = player.locator(`[data-slate-market-row="${example.market}"]`)
      await row.waitFor({ timeout: TIMEOUT })
      check(await player.locator(`[data-slate-market-row="${example.market}"]`).count() === 1,
        'Slate duplicated one player/market across alternate lines')
      await row.locator('[data-slate-line-selector] summary').click()
      check(await row.getByRole('option').count() === example.offerCount,
        'Slate alternate dropdown count disagrees with the API')
      check(await row.getByRole('button', { name: 'OVER' }).count() === 1,
        'Slate did not collapse OVER to one control')
      check(await row.getByRole('button', { name: 'UNDER' }).count() === 1,
        'Slate did not collapse UNDER to one control')
      evidence.push(`slate=${example.player}/${example.market} ${example.offerCount} lines in 1 row`)
    }

    // Props UFC: selecting a method market must open and request fight form
    // without a disclosure click.
    await page.getByRole('button', { name: 'UFC', exact: true }).click()
    await page.getByRole('button', { name: 'Props', exact: true }).click()
    const method = page.getByRole('button', { name: /^(Win by decision|Finishes|Knockouts|Submissions)\b/ }).first()
    await method.waitFor({ timeout: TIMEOUT })
    await method.click()
    const form = page.locator('[data-fight-form]').first()
    await form.waitFor({ timeout: TIMEOUT })
    await page.waitForFunction(() => {
      const value = document.querySelector('[data-fight-form]')?.getAttribute('data-fight-form-state')
      return value === 'open'
    }, null, { timeout: TIMEOUT })
    check(await form.locator('[data-fight-form-content]').count() === 1,
      'UFC recent form did not render automatically')
    const fighterId = await form.getAttribute('data-fight-player-id')
    const formApi = await api(page, `/api/ufc/fighter/${fighterId}/form`)
    check(formApi.ok && formApi.body?.source === 'ufcstats',
      'UFC automatic form was not backed by UFCStats')
    evidence.push(`ufc-form=automatic player ${fighterId} source ${formApi.body?.source}`)

    // Tennis: both newly supported fields must render chart history, not a
    // placeholder. Use the current combined ATP/WTA slate.
    await page.getByRole('button', { name: 'Tennis', exact: true }).click()
    for (const market of ['Total Games', 'Match Winner']) {
      const button = page.getByRole('button', { name: new RegExp(`^${market}\\b`) }).first()
      await button.waitFor({ timeout: TIMEOUT })
      await button.click()
      await page.locator('[data-market-row]').first().waitFor({ timeout: TIMEOUT })
      await page.locator('[data-market-chart]').first().waitFor({ timeout: TIMEOUT })
      const rows = await page.locator('[data-market-row]').count()
      const charts = await page.locator('[data-market-chart]').count()
      const empty = await page.locator('[data-history-empty]').count()
      check(rows > 0 && charts === rows && empty === 0,
        `${market} did not render history for every current tennis row (${charts}/${rows}, empty ${empty})`)
      evidence.push(`tennis-${market.toLowerCase().replace(/ /g, '-')}=${charts}/${rows} charts`)
    }

    check(runtimeErrors.length === 0, `browser runtime errors: ${runtimeErrors.join(' | ')}`)
    check(relevantApiFailures.length === 0, `API 5xx responses: ${relevantApiFailures.join(' | ')}`)
  } catch (error) {
    failures.push(`gate crashed: ${error.stack || error.message}`)
  } finally {
    await browser.close()
  }

  evidence.forEach(item => console.log(`PASS ${item}`))
  if (failures.length) {
    failures.forEach(item => console.error(`FAIL ${item}`))
    process.exit(1)
  }
  console.log(`PASS public Props/UFC optimizer E2E at ${BASE}`)
})()
