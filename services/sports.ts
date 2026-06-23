import axios from 'axios'

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

// Live game period detail
export interface LivePeriod {
  number: number
  type: 'inning' | 'period' | 'quarter' | 'round' | 'game'
  display?: string
}

// The unified ESPN backend (sports_service.py) returns games as
//   { game_id, date, state: 'pre'|'in'|'post', home/away: { abbrev, name, score } }
// The UI works against a stable internal shape; we translate here (anti-corruption layer).
export interface Game {
  gameId: string
  league?: string
  homeTeam: { teamId: string; name: string; nickname?: string; score?: number; winner?: boolean }
  awayTeam: { teamId: string; name: string; nickname?: string; score?: number; winner?: boolean }
  startTime: string
  status: 'SCHEDULED' | 'LIVE' | 'FINAL'
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
  return { teamId: s?.abbrev ?? '', name: name + record, nickname: s?.nickname, score: s?.score ?? undefined, winner: s?.winner ?? undefined }
}

function normalizeSets(g: any): TennisSet[] | undefined {
  // Try multiple possible API response formats
  if (g?.sets && Array.isArray(g.sets)) {
    return g.sets.map((s: any) => ({
      homeScore: s?.home_score ?? s?.homeScore ?? s?.home ?? 0,
      awayScore: s?.away_score ?? s?.awayScore ?? s?.away ?? 0,
    }))
  }
  // Some APIs return set scores as arrays
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
    // Determine type from league
    let type: LivePeriod['type'] = 'period'
    if (lg === 'mlb') type = 'inning'
    else if (lg === 'nba') type = 'quarter'
    else if (lg === 'nhl') type = 'period'
    else if (lg === 'nfl') type = 'quarter'
    else if (lg === 'ufc') type = 'round'
    else if (lg === 'atp' || lg === 'wta') type = 'period'

    // For MLB, use ESPN's status_detail which has inning state ("Top 1st", "End 5th", etc.)
    let display: string | undefined
    if (lg === 'mlb' && g?.status_detail) {
      // ESPN format: "End 1st", "Top 2nd", "Bot 3rd", "Mid 7th"
      // Convert "End 1st" → "End 1st" (keep as-is), "Top 2nd" → "Top 2nd"
      display = g.status_detail
    }

    return {
      number: typeof period === 'number' ? period : parseInt(String(period), 10),
      type,
      display,
    }
  }

  // Check for MLB-specific inning/outs
  if (g?.inning !== undefined) {
    return {
      number: g.inning,
      type: 'inning',
      display: g?.inning_state ? `Inning ${g.inning} (${g.inning_state})` : `Inning ${g.inning}`,
    }
  }

  return undefined
}

export function normalizeGame(g: any, leagueOverride?: string): Game {
  // Build subtitle: for UFC use card_segment, for tennis/UFC use event name
  let subtitle = g?.card_segment || g?.event || ''

  // Determine league from various possible fields, with optional override
  const league = leagueOverride ? leagueOverride : (g?.league ?? g?.sport ?? '')

  return {
    gameId: String(g?.game_id ?? g?.gameId ?? ''),
    league: league.toUpperCase() || undefined,
    homeTeam: side(g?.home ?? g?.homeTeam),
    awayTeam: side(g?.away ?? g?.awayTeam),
    startTime: g?.date ?? g?.startTime ?? '',
    status: g?.status && ['SCHEDULED', 'LIVE', 'FINAL'].includes(g.status) ? g.status : statusFromState(g?.state),
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

export const SportsService = {
  getGames: async (league: string): Promise<Game[]> => {
    try {
      const res = await axios.get(`${API_BASE_URL}/${league}/games`)
      return (Array.isArray(res.data) ? res.data : []).map(normalizeGame)
    } catch (err) {
      console.error('Error fetching games', err)
      return []
    }
  },

  getGamesByDate: async (league: string, date: string): Promise<Game[]> => {
    try {
      const res = await axios.get(`${API_BASE_URL}/${league}/games`, { params: { date } })
      return (Array.isArray(res.data) ? res.data : []).map((g: any) => ({
        ...normalizeGame(g, league),
        league: league.toUpperCase(),
      }))
    } catch (err) {
      console.error(`Error fetching ${league} games for ${date}`, err)
      return []
    }
  },

  getAllGamesByDate: async (date: string): Promise<Game[]> => {
    const leagues = ['nba', 'mlb', 'nhl', 'nfl', 'atp', 'wta', 'cod', 'ufc']
    const promises = leagues.map((l) => SportsService.getGamesByDate(l, date))
    const results = await Promise.all(promises)
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
}