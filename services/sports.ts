import axios from 'axios'
import { livePeriodTypeForLeague } from '../lib/liveGameStatus'
import type { LivePeriod } from '../lib/liveGameStatus'

function normalizeBaseUrl(raw?: string): string {
  // Relative same-origin default: browser -> nginx -> backend. A 'localhost:8000'
  // default fails in the user's browser (it's THEIR machine), which blanked the scores page.
  const fallback = '/api'
  if (!raw || raw.trim() === '') return fallback
  const base = raw.trim()
  if (base.startsWith('/')) return base
  if (!/^https?:\/\//i.test(base)) return `http://${base}`
  return base
}

const API_BASE_URL = normalizeBaseUrl(process.env.NEXT_PUBLIC_SPORTS_API_URL)

// Tennis set score
export interface TennisSet {
  homeScore: number
  awayScore: number
}

export type { LivePeriod } from '../lib/liveGameStatus'

// The unified ESPN backend (sports_service.py) returns games as
//   { game_id, date, state: 'pre'|'in'|'post', home/away: { abbrev, name, score } }
// The UI works against a stable internal shape; we translate here (anti-corruption layer).
export interface TeamSide {
  teamId: string
  name: string
  nickname?: string
  score?: number
  winner?: boolean
  // EWC bracket participants: a decided club renders by name; an undecided slot renders the
  // dependency label ("Winner of X–Y") and never a score, logo, or detail link.
  label?: string
  pending?: boolean
  unavailable?: boolean
}

export interface Game {
  gameId: string
  // Optional canonical id for a league-specific detail source. CoD scores use
  // BreakingPoint gameId values while the grounded detail page uses PandaScore.
  detailGameId?: string
  league?: string
  homeTeam: TeamSide
  awayTeam: TeamSide
  startTime: string
  status: 'SCHEDULED' | 'LIVE' | 'FINAL'
  // ESPN short detail, e.g. "Final/10" (extra innings) or "Final/OT" — shown on the FINAL badge
  statusDetail?: string
  subtitle?: string
  // Tennis: array of set scores [home, away] for each set
  sets?: TennisSet[]
  // Live game period details (only present when LIVE)
  livePeriod?: LivePeriod
}

function statusFromState(state?: string): Game['status'] {
  return state === 'post' ? 'FINAL' : state === 'in' ? 'LIVE' : 'SCHEDULED'
}

function side(s: any): Game['homeTeam'] {
  const name = s?.name ?? s?.abbrev ?? ''
  const record = s?.record ? ` (${s.record})` : ''
  const p = s?.participant
  const state = p?.state
  const label = state === 'named'
    ? (p?.clubName ?? name)
    : (p?.label ?? name)
  return {
    teamId: s?.abbrev ?? '',
    name: name + record,
    nickname: s?.nickname,
    score: s?.score ?? undefined,
    winner: s?.winner ?? undefined,
    label: label || undefined,
    pending: state === 'pending',
    unavailable: state === 'unavailable',
  }
}

function normalizeSets(g: any): TennisSet[] | undefined {
  // Per-competitor arrays from tennis branch (home.sets=[6,7,6], away.sets=[2,5,4])
  const homeArr = g?.home?.sets
  const awayArr = g?.away?.sets
  if (homeArr && awayArr && Array.isArray(homeArr) && Array.isArray(awayArr)) {
    const n = Math.max(homeArr.length, awayArr.length)
    const sets: TennisSet[] = []
    for (let i = 0; i < n; i++) {
      sets.push({ homeScore: homeArr[i] ?? 0, awayScore: awayArr[i] ?? 0 })
    }
    return sets.length > 0 ? sets : undefined
  }
  // Old format: g.sets = [{home_score, away_score}, ...]
  if (g?.sets && Array.isArray(g.sets)) {
    return g.sets.map((s: any) => ({
      homeScore: s?.home_score ?? s?.homeScore ?? s?.home ?? 0,
      awayScore: s?.away_score ?? s?.awayScore ?? s?.away ?? 0,
    }))
  }
  // Old format: g.set_scores = [[home, away], ...]
  if (g?.set_scores && Array.isArray(g.set_scores)) {
    return g.set_scores.map((s: any) => ({
      homeScore: s[0] ?? 0,
      awayScore: s[1] ?? 0,
    }))
  }
  return undefined
}

function normalizeLivePeriod(g: any, league?: string): LivePeriod | undefined {
  // Only for LIVE games
  if (g?.state !== 'in' && g?.status !== 'LIVE') return undefined

  const period = g?.period ?? g?.current_period ?? g?.inning ?? g?.quarter ?? g?.round ?? g?.game
  const lg = (league || g?.league || '').toLowerCase()

  if (period !== undefined && period !== null) {
    const type = livePeriodTypeForLeague(lg)
    // ESPN's baseball display clock is often exactly "0:00" while the
    // authoritative inning state lives in shortDetail. Keep them separate so
    // the UI never treats the placeholder clock as the phase.
    const display = lg === 'mlb' ? g?.status_detail ?? undefined : undefined

    return {
      number: typeof period === 'number' ? period : parseInt(String(period), 10),
      type,
      display,
      clock: g?.clock ?? undefined,
    }
  }

  // Check for MLB-specific inning/outs
  if (g?.inning !== undefined) {
    return {
      number: g.inning,
      type: 'inning',
      display: g?.inning_state ? `Inning ${g.inning} (${g.inning_state})` : `Inning ${g.inning}`,
      clock: g?.clock ?? undefined,
    }
  }

  // Soccer: preserve the running match clock even when ESPN omits a half number.
  if (lg === 'wc' || lg === 'lcup' || lg === 'mls') {
    const clock = g?.clock ?? g?.status_detail
    if (clock) {
      return { type: 'half', clock }
    }
  }

  return undefined
}

export function normalizeGame(g: any, leagueOverride?: string): Game {
  // Determine league from various possible fields, with optional override
  const rawLeague = leagueOverride ? leagueOverride : (g?.league ?? g?.sport ?? '')
  const league = typeof rawLeague === 'string' ? rawLeague : (rawLeague?.abbreviation || rawLeague?.name || String(rawLeague || ''))

  // The board's section heading. Tennis names the tournament ("Cincinnati
  // Open"); a UFC card used to name only its segment ("Main Card"), which says
  // nothing about WHICH card. The event leads for the same reason the tournament
  // does, and the segment follows it, since Prelims and Main Card start at
  // different times and still have to group separately.
  const segment = g?.card_segment || ''
  const event = g?.event || ''
  let subtitle = event && segment ? `${event} · ${segment}` : (segment || g?.subtitle || event || '')

  return {
    gameId: String(g?.game_id ?? g?.gameId ?? ''),
    detailGameId: g?.detail_game_id != null
      ? String(g.detail_game_id)
      : g?.detailGameId != null
      ? String(g.detailGameId)
      : undefined,
    league: league.toUpperCase() || undefined,
    homeTeam: side(g?.home ?? g?.homeTeam),
    awayTeam: side(g?.away ?? g?.awayTeam),
    startTime: g?.date ?? g?.startTime ?? '',
    status: g?.status && ['SCHEDULED', 'LIVE', 'FINAL'].includes(g.status) ? g.status : statusFromState(g?.state),
    statusDetail: g?.status_detail ?? g?.statusDetail ?? undefined,   // ESPN shortDetail, e.g. "Final/10"
    subtitle: subtitle || undefined,
    sets: normalizeSets(g),
    livePeriod: normalizeLivePeriod(g, league),
  }
}

export interface Prediction {
  id: number
  league: string
  gameId: string
  predictedWinner: string
  correct: boolean | null
}

function normalizePrediction(p: any): Prediction {
  return {
    id: p?.id,
    league: p?.league,
    gameId: String(p?.game_id ?? p?.gameId ?? ''),
    predictedWinner: p?.predicted_winner ?? p?.predictedWinner ?? '',
    correct: p?.correct === null || p?.correct === undefined ? null : Boolean(p.correct),
  }
}

// Client-side games cache. The scoreboard fans out to many league×date requests (each
// viewer-local day pulls neighbors, and the 30s live-poll re-fires) — without this, cod
// (~1.3s) got re-fetched several times per load. Past days are settled (cache long);
// today refreshes fast enough (< the 30s poll) that live scores never freeze.
const _gamesCache = new Map<string, { ts: number; data: Game[] }>()
const _gamesInflight = new Map<string, Promise<Game[]>>()
const _scheduleDatesCache = new Map<string, { ts: number; data: ScheduleDatesResponse }>()
const _scheduleDatesInflight = new Map<string, Promise<ScheduleDatesResponse | null>>()
const _scheduleDatesTtl = 300_000
const _localToday = () => new Date().toLocaleDateString('en-CA')
const _cacheTtl = (date: string): number => {
  const today = _localToday()
  if (date < today) return 300_000 // settled past — 5 min
  if (date > today) return 60_000  // future slate — 1 min
  return 10_000                    // today — 10s (< 30s live poll, so scores stay fresh)
}

export const SportsService = {
  getGames: async (league: string): Promise<Game[]> => {
    try {
      const res = await axios.get(`${API_BASE_URL}/${league}/games`)
      // Pass the requested league explicitly as the override so each game keeps
      // the correct league (the map(callback) form would pass the array INDEX as
      // the override — see Blocker-3 regression). This keeps GameCard links working.
      return (Array.isArray(res.data) ? res.data : []).map((g: any) => normalizeGame(g, league))
    } catch (err) {
      console.error('Error fetching games', err)
      return []
    }
  },

  getGamesByDate: async (league: string, date: string): Promise<Game[]> => {
    const key = `${league}:${date}`
    const hit = _gamesCache.get(key)
    if (hit && Date.now() - hit.ts < _cacheTtl(date)) return hit.data
    // Collapse concurrent identical requests (React re-renders, the window's neighbor
    // days, and the live poll) into a single in-flight fetch.
    const inflight = _gamesInflight.get(key)
    if (inflight) return inflight
    const p = (async () => {
      try {
        const res = await axios.get(`${API_BASE_URL}/${league}/games`, { params: { date } })
        const data = (Array.isArray(res.data) ? res.data : []).map((g: any) => ({
          ...normalizeGame(g, league),
          league: league.toUpperCase(),
        }))
        // An outage with no persisted fallback is intentionally a 200 [] so it
        // cannot take every league page down. Do not turn that temporary state
        // into a five-minute past-date cache entry after the publisher recovers.
        if (res.headers?.['x-lp-data-source'] !== 'unavailable') {
          _gamesCache.set(key, { ts: Date.now(), data })
        }
        return data
      } catch (err) {
        console.error(`Error fetching ${league} games for ${date}`, err)
        // A failed request is not the same thing as a valid day with no games.
        // Callers own the visible error state and already catch this rejection.
        throw err
      } finally {
        _gamesInflight.delete(key)
      }
    })()
    _gamesInflight.set(key, p)
    return p
  },

  getAllGamesByDate: async (date: string): Promise<Game[]> => {
    const leagues = ['nba', 'mlb', 'nhl', 'nfl', 'lcup', 'mls', 'atp', 'wta', 'cod', 'ufc', 'wc']
    const promises = leagues.map((l) => SportsService.getGamesByDate(l, date))
    const results = await Promise.all(promises)
    return results.flat()
  },

  // `startTime` is an absolute UTC instant, but the scoreboard's "day" must be the VIEWER's
  // local day — not the backend's UTC date bucket. A CoD match that ended 9pm CT is 02:00 UTC
  // the next day, so a plain by-UTC-date fetch drops it onto tomorrow's board. Fetch the
  // selected day plus its neighbors and keep only games whose local day matches.
  getGamesByLocalDate: async (league: string, localDate: string, opts?: { strict?: boolean }): Promise<Game[]> => {
    const localDayOf = (iso: string): string | null => {
      if (!iso) return null
      // Persisted team_game_results knows the published game date, not an exact
      // start instant. Parsing YYYY-MM-DD as UTC midnight moves it to the prior
      // date in US timezones. Keep day-precision rows in their requested bucket.
      if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null
      const d = new Date(iso)
      return isNaN(d.getTime()) ? null : d.toLocaleDateString('en-CA')
    }
    const base = new Date(localDate + 'T12:00:00') // noon-anchored to dodge TZ rollover
    // A local day maps to at most two UTC dates; fetch only the neighbor in the tz's
    // direction (west of UTC → next day also holds late-local games; east → previous)
    // instead of both, halving the request fan-out.
    const off = base.getTimezoneOffset() // minutes; >0 = behind UTC (west), <0 = ahead (east)
    const deltas = off > 0 ? [0, 1] : off < 0 ? [-1, 0] : [0]
    const windowDates = deltas.map((delta) => {
      const d = new Date(base); d.setDate(d.getDate() + delta)
      return d.toLocaleDateString('en-CA')
    })
    const perDate = await Promise.all(
      windowDates.map(async (d) => {
        try {
          const games = await SportsService.getGamesByDate(league, d)
          return { d, games }
        } catch (err) {
          if (opts?.strict) throw err
          return { d, games: [] as Game[] }
        }
      }),
    )
    const seen = new Set<string>()
    const kept: Game[] = []
    for (const { d, games } of perDate) {
      for (const g of games) {
        const day = localDayOf(g.startTime)
        // valid instant → keep on its local day; undated (TBD) → keep on its own backend bucket
        if (!(day ? day === localDate : d === localDate)) continue
        const key = `${g.league}:${g.gameId}`
        if (seen.has(key)) continue
        seen.add(key)
        kept.push(g)
      }
    }
    return kept
  },

  getAllGamesByLocalDate: async (localDate: string, opts?: { strict?: boolean }): Promise<Game[]> => {
    const leagues = ['nba', 'mlb', 'nhl', 'nfl', 'lcup', 'mls', 'atp', 'wta', 'cod', 'ufc', 'wc']
    const results = await Promise.all(leagues.map((l) => SportsService.getGamesByLocalDate(l, localDate, opts)))
    return results.flat()
  },

  // Team quality ranking (win% / differential / streak / last-10) — new capability of the ESPN backend.
  getStrength: async (league: string) => {
    try {
      const res = await axios.get(`${API_BASE_URL}/${league}/strength`)
      return res.data
    } catch (err) {
      console.error('Error fetching strength', err)
      return []
    }
  },

  // M7 analytics — EV / CLV / calibration from the odds-snapshot backbone.
  getCalibration: async (league: string, market?: string) => {
    try {
      const params: Record<string, any> = { league }
      if (market) params.market = market
      const res = await axios.get(`${API_BASE_URL}/calibration`, { params })
      return res.data
    } catch (err) {
      console.error('Error fetching calibration', err)
      return null
    }
  },

  getPropsEV: async (league: string, opts: { min_ev?: number; market?: string; limit?: number } = {}) => {
    try {
      const res = await axios.get(`${API_BASE_URL}/props/ev`, { params: { league, ...opts } })
      return res.data
    } catch (err) {
      console.error('Error fetching props EV', err)
      return null
    }
  },

  getPropsCLV: async (league: string, opts: { min_clv?: number; limit?: number } = {}) => {
    try {
      const res = await axios.get(`${API_BASE_URL}/props/clv`, { params: { league, ...opts } })
      return res.data
    } catch (err) {
      console.error('Error fetching props CLV', err)
      return null
    }
  },

  submitPrediction: async (league: string, gameId: string, predictedWinner: string): Promise<Prediction | null> => {
    try {
      // backend contract is snake_case
      const res = await axios.post(`${API_BASE_URL}/predictions`, {
        league,
        game_id: gameId,
        predicted_winner: predictedWinner,
      })
      return normalizePrediction(res.data)
    } catch (err) {
      console.error('Error submitting prediction', err)
      return null
    }
  },

  getPredictions: async (league?: string): Promise<Prediction[]> => {
    try {
      const params: Record<string, string> = {}
      if (league) params.league = league
      const res = await axios.get(`${API_BASE_URL}/predictions`, { params })
      // backend returns { predictions, graded, accuracy }
      const list = Array.isArray(res.data) ? res.data : res.data?.predictions ?? []
      return list.map(normalizePrediction)
    } catch (err) {
      console.error('Error getting predictions', err)
      return []
    }
  },

  getGameDetail: async (league: string, gameId: string) => {
    try {
      const res = await axios.get(`${API_BASE_URL}/${league}/game/${gameId}/detail`)
      return res.data
    } catch (err) {
      console.error('Error fetching game detail', err)
      return null
    }
  },

  // Per-tab lazy endpoints — each tab fetches its own data on first open
  getBoxscore: async (league: string, gameId: string) => {
    try {
      const res = await axios.get(`${API_BASE_URL}/${league}/game/${gameId}/boxscore`)
      return res.data
    } catch (err) {
      console.error('Error fetching boxscore', err)
      return { available: false }
    }
  },

  getPlayByPlay: async (league: string, gameId: string) => {
    try {
      const res = await axios.get(`${API_BASE_URL}/${league}/game/${gameId}/playbyplay`)
      return res.data
    } catch (err) {
      console.error('Error fetching play-by-play', err)
      return { available: false }
    }
  },

  getGameInfo: async (league: string, gameId: string) => {
    try {
      const res = await axios.get(`${API_BASE_URL}/${league}/game/${gameId}/gameinfo`)
      return res.data
    } catch (err) {
      console.error('Error fetching game info', err)
      return { available: false }
    }
  },

  getScheduleDates: async (league: string, anchor: string): Promise<ScheduleDatesResponse | null> => {
    const key = `${league.toLowerCase()}:${anchor}`
    const cached = _scheduleDatesCache.get(key)
    if (cached && Date.now() - cached.ts < _scheduleDatesTtl) return cached.data

    // Auto-resolution and arrow navigation consume the same contract. Collapse
    // their concurrent effects (including React development replays) into one
    // backend request instead of multiplying ESPN discovery work.
    const inflight = _scheduleDatesInflight.get(key)
    if (inflight) return inflight

    const request = (async () => {
      try {
        const res = await axios.get(`${API_BASE_URL}/${league}/schedule-dates`, { params: { anchor } })
        const data = res.data as ScheduleDatesResponse
        _scheduleDatesCache.set(key, { ts: Date.now(), data })
        return data
      } catch (err) {
        console.error('Error fetching schedule dates', err)
        return null
      } finally {
        _scheduleDatesInflight.delete(key)
      }
    })()
    _scheduleDatesInflight.set(key, request)
    return request
  },

  // W3 — day navigation jumps to the neighbouring date that actually has games
  // instead of calendar ±1. Resolves the nearest local date strictly before
  // (delta -1) / after (delta +1) the anchor across the given leagues, from the
  // schedule-dates contract. Returns null when no league reports a game in that
  // direction or discovery fails — callers decide the fallback.
  getNeighbourGameDate: async (leagues: string[], anchor: string, delta: -1 | 1): Promise<string | null> => {
    const perLeague = await Promise.all(leagues.map(async (league) => {
      const data = await SportsService.getScheduleDates(league, anchor)
      if (!data) return [] as string[]
      const starts = delta < 0 ? data.past_event_starts : data.future_event_starts
      return (starts || [])
        .map(iso => new Date(iso).toLocaleDateString('en-CA'))
        .filter(d => delta < 0 ? d < anchor : d > anchor)
    }))
    const candidates = perLeague.flat().sort()
    if (!candidates.length) return null
    return delta < 0 ? candidates[candidates.length - 1] : candidates[0]
  },

  getNflScheduleWeeks: async (anchor: string): Promise<NflScheduleWeeksResponse | null> => {
    try {
      const res = await axios.get(`${API_BASE_URL}/nfl/schedule-weeks`, { params: { anchor } })
      return res.data
    } catch (err) {
      console.error('Error fetching NFL schedule weeks', err)
      return null
    }
  },

  getNflScheduleWeek: async (season: number, seasonType: number, week: number): Promise<NflScheduleWeekResponse | null> => {
    try {
      const res = await axios.get(`${API_BASE_URL}/nfl/schedule-week`, {
        params: { season, season_type: seasonType, week },
      })
      return res.data
    } catch (err) {
      console.error('Error fetching NFL schedule week', err)
      return null
    }
  },
}

export interface ScheduleDatesResponse {
  contract: string
  league: string
  anchor_date: string
  event_start_timezone: string
  available?: boolean
  source?: 'espn' | 'local' | 'unavailable'
  error?: 'publisher_unavailable'
  future_event_starts: string[]
  past_event_starts: string[]
  search: {
    future: { start_date: string; end_date: string; event_starts_found: number }[]
    past: { start_date: string; end_date: string; event_starts_found: number }[]
    max_horizon_days: number
  }
}

// ── NFL schedule weeks ──

export interface NflWeekEntry {
  key: string
  season_type: number
  week: number
  label: string
  alternate_label: string | null
  detail: string | null
  start_time: string
  end_time: string
}

export interface NflPhaseGroup {
  season_type: number
  label: string
  start_time: string
  end_time: string
  weeks: NflWeekEntry[]
}

export interface NflScheduleWeeksResponse {
  contract: string
  league: string
  season: number
  anchor_date: string
  navigation: string
  phases: NflPhaseGroup[]
  weeks: NflWeekEntry[]
  default_week_key: string
  default_reason: string
}

export interface NflScheduleWeekResponse {
  contract: string
  league: string
  season: number
  selected_week: NflWeekEntry
  games: any[]
}
