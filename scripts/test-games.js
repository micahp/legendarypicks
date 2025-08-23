#!/usr/bin/env node
/*
  Simple test runner to fetch games by date from the Next.js API.
  Usage:
    node scripts/test-games.js 2025-10-02 fastapi
  or envs:
    DATE=2025-10-02 PROVIDER=fastapi NEXT_BASE_URL=http://localhost:3000 node scripts/test-games.js
*/

const axios = require('axios')

const BASE_URL = process.env.NEXT_BASE_URL || 'http://localhost:3000'
const DATE = process.argv[2] || process.env.DATE || new Date().toISOString().slice(0, 10)
const PROVIDER = process.argv[3] || process.env.PROVIDER || undefined

async function main() {
  try {
    const params = { date: DATE }
    if (PROVIDER) params.provider = PROVIDER

    const url = `${BASE_URL}/api/nba/games`
    console.log(`[test] GET ${url} params=${JSON.stringify(params)}`)
    const { data } = await axios.get(url, { params })

    const count = Array.isArray(data) ? data.length : 0
    console.log(`[ok] games: ${count}`)
    if (count > 0) {
      console.log('[sample]', JSON.stringify(data.slice(0, 3), null, 2))
    }
    process.exit(0)
  } catch (err) {
    const status = err?.response?.status
    const detail = err?.response?.data || err?.message
    console.error('[error]', status || '', detail)
    process.exit(1)
  }
}

main()


