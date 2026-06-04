import type { NextApiRequest, NextApiResponse } from 'next'
import axios from 'axios'

type CacheEntry = { data: any; expiresAt: number }
const cache = new Map<string, CacheEntry>()
const TTL_MS = 60 * 1000 // 60s basic cache to mitigate rate limits

function cacheKey(date: string) {
  return `nba:games:${date}`
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

function shouldRetry(status?: number): boolean {
  if (!status) return false
  if (status === 429) return true
  if (status >= 500 && status < 600) return true
  return false
}

function normalizeBaseUrl(raw?: string): string {
  const fallback = 'http://localhost:8000/api'
  if (!raw || raw.trim() === '') return fallback
  let base = raw.trim()
  if (base.startsWith('/')) return fallback
  if (!/^https?:\/\//i.test(base)) base = `http://${base.replace(/^\/+/, '')}`
  return base.replace(/\/$/, '')
}

// Log provider/env once at module load for observability (not on every request)
try {
  const initInfo = {
    envProvider: process.env.NBA_PROVIDER,
    fastapiBase: process.env.NEXT_PUBLIC_NBA_API_URL,
    hasSportsDataKey: Boolean(process.env.SPORTSDATA_KEY),
  }
  const g: any = globalThis as any
  if (!g.__NBA_PROVIDER_LOGGED__) {
    console.log('[NBA_PROVIDER:init]', initInfo)
    g.__NBA_PROVIDER_LOGGED__ = true
  }
} catch (_) {
  // no-op
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET')
    return res.status(405).json({ message: 'Method Not Allowed' })
  }

  const { date } = req.query
  if (!date || typeof date !== 'string') {
    return res.status(400).json({ message: 'Missing required query param: date (YYYY-MM-DD)' })
  }

  try {
    const provider = (typeof req.query.provider === 'string' ? req.query.provider : process.env.NBA_PROVIDER) || 'nba_api'

    if (provider === 'fastapi' || provider === 'nba_api') {
      // Delegate to our unified ESPN backend: GET /api/nba/games?date=YYYY-MM-DD
      const base = normalizeBaseUrl(process.env.NEXT_PUBLIC_NBA_API_URL)
      const upstream = `${base}/nba/games`
      const upstreamResp = await axios.get(upstream, { params: { date }, validateStatus: () => true })
      if (upstreamResp.status >= 200 && upstreamResp.status < 300) {
        // Backend shape -> internal Game shape (the SportsData path below maps to the same shape).
        const mapped = (Array.isArray(upstreamResp.data) ? upstreamResp.data : []).map((g: any) => ({
          gameId: String(g?.game_id ?? ''),
          homeTeam: { teamId: g?.home?.abbrev ?? '', name: g?.home?.name ?? g?.home?.abbrev ?? '', score: g?.home?.score ?? undefined },
          awayTeam: { teamId: g?.away?.abbrev ?? '', name: g?.away?.name ?? g?.away?.abbrev ?? '', score: g?.away?.score ?? undefined },
          startTime: g?.date ?? new Date(date).toISOString(),
          status: g?.state === 'post' ? 'FINAL' : g?.state === 'in' ? 'LIVE' : 'SCHEDULED',
        }))
        return res.status(200).json(mapped)
      }
      return res.status(upstreamResp.status).json({ message: 'Upstream error', detail: upstreamResp.data })
    }

    // Default: SportsData.io path with cache + retries (paid/free tier)
    const apiKey = process.env.SPORTSDATA_KEY
    if (!apiKey) {
      return res.status(500).json({ message: 'SPORTSDATA_KEY not set on server' })
    }

    // Serve cached response if available and fresh
    const key = cacheKey(date)
    const now = Date.now()
    const hit = cache.get(key)
    if (hit && hit.expiresAt > now) {
      return res.status(200).json(hit.data)
    }

    // SportsData.io NBA Games by Date endpoint
    // Docs: v3/nba/scores/json/GamesByDate/{date}
    const sdUrl = `https://api.sportsdata.io/v3/nba/scores/json/GamesByDate/${encodeURIComponent(date)}`

    let attempt = 0
    let data: any = null
    let lastErr: any = null
    const maxAttempts = 3
    while (attempt < maxAttempts) {
      try {
        const resp = await axios.get(sdUrl, {
          params: { key: apiKey },
          validateStatus: () => true,
        })
        if (resp.status >= 200 && resp.status < 300) {
          data = resp.data
          break
        }
        if (!shouldRetry(resp.status)) {
          return res.status(resp.status).json({ message: 'Proxy error', detail: resp.data })
        }
        // Retry with backoff
        const retryAfter = Number(resp.headers?.['retry-after'])
        const backoff = retryAfter && !Number.isNaN(retryAfter)
          ? retryAfter * 1000
          : 300 * Math.pow(2, attempt)
        await sleep(backoff)
      } catch (err: any) {
        lastErr = err
        await sleep(300 * Math.pow(2, attempt))
      } finally {
        attempt += 1
      }
    }

    if (!data) {
      if (lastErr?.response) {
        const { status, data: detail } = lastErr.response
        return res.status(status || 500).json({ message: 'Proxy error', detail })
      }
      return res.status(500).json({ message: 'Proxy error', detail: lastErr?.message || 'Unknown' })
    }

    // Normalize to our internal Game shape
    const mapped = (Array.isArray(data) ? data : []).map((g: any) => {
      const statusRaw = (g?.Status || '').toString().toLowerCase()
      const status = statusRaw.includes('final')
        ? 'FINAL'
        : statusRaw.includes('inprogress') || statusRaw.includes('in progress')
        ? 'LIVE'
        : 'SCHEDULED'

      return {
        gameId: String(g?.GameID ?? g?.GlobalGameID ?? `${g?.HomeTeam}-${g?.AwayTeam}-${date}`),
        homeTeam: {
          teamId: String(g?.HomeTeam ?? ''),
          name: String(g?.HomeTeam ?? ''),
          score: g?.HomeTeamScore ?? undefined,
        },
        awayTeam: {
          teamId: String(g?.AwayTeam ?? ''),
          name: String(g?.AwayTeam ?? ''),
          score: g?.AwayTeamScore ?? undefined,
        },
        startTime: g?.DateTimeUTC || g?.DateTime || g?.Day || new Date(date).toISOString(),
        status,
      }
    })

    // Cache result
    cache.set(key, { data: mapped, expiresAt: Date.now() + TTL_MS })

    return res.status(200).json(mapped)
  } catch (err: any) {
    const status = err?.response?.status || 500
    const detail = err?.response?.data || { message: err?.message || 'Upstream error' }
    return res.status(status).json({ message: 'Proxy error', detail })
  }
}


