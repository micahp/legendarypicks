import axios from 'axios'

function normalizeBaseUrl(raw?: string): string {
  const fallback = 'http://localhost:8000/api'
  if (!raw || raw.trim() === '') return fallback
  const base = raw.trim()
  if (base.startsWith('/')) return base
  if (!/^https?:\/\//i.test(base)) return `http://${base}`
  return base
}

const API_BASE_URL = normalizeBaseUrl(process.env.NEXT_PUBLIC_SPORTS_API_URL)

// The unified ESPN backend (sports_service.py) returns games as
//   { game_id, date, state: 'pre'|'in'|'post', home/away: { abbrev, name, score } }
// The UI works against a stable internal shape; we translate here (anti-corruption layer).
export interface Game {
  gameId: string
  league?: string
  homeTeam: { teamId: string; name: string; score?: number }
  awayTeam: { teamId: string; name: string; score?: number }
  startTime: string
  status: 'SCHEDULED' | 'LIVE' | 'FINAL'
}

function statusFromState(state?: string): Game['status'] {
  return state === 'post' ? 'FINAL' : state === 'in' ? 'LIVE' : 'SCHEDULED'
}

function side(s: any): Game['homeTeam'] {
  const name = s?.name ?? s?.abbrev ?? ''
  const record = s?.record ? ` (${s.record})` : ''
  return { teamId: s?.abbrev ?? '', name: name + record, score: s?.score ?? undefined }
}

export function normalizeGame(g: any): Game {
  return {
    gameId: String(g?.game_id ?? g?.gameId ?? ''),
    homeTeam: side(g?.home ?? g?.homeTeam),
    awayTeam: side(g?.away ?? g?.awayTeam),
    startTime: g?.date ?? g?.startTime ?? '',
    status: g?.status && ['SCHEDULED', 'LIVE', 'FINAL'].includes(g.status) ? g.status : statusFromState(g?.state),
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
        ...normalizeGame(g),
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

  getPredictions: async (): Promise<Prediction[]> => {
    try {
      const res = await axios.get(`${API_BASE_URL}/predictions`)
      // backend returns { predictions, graded, accuracy }
      const list = Array.isArray(res.data) ? res.data : res.data?.predictions ?? []
      return list.map(normalizePrediction)
    } catch (err) {
      console.error('Error getting predictions', err)
      return []
    }
  },
}
