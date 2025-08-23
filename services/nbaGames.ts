import axios from 'axios'

function normalizeBaseUrl(raw?: string): string {
  const fallback = 'http://localhost:8000/api'
  if (!raw || raw.trim() === '') return fallback
  const base = raw.trim()
  if (base.startsWith('/')) return base
  if (!/^https?:\/\//i.test(base)) return `http://${base}`
  return base
}

const API_BASE_URL = normalizeBaseUrl(process.env.NEXT_PUBLIC_NBA_API_URL)

interface Game {
  gameId: string
  homeTeam: {
    teamId: string
    name: string
    score?: number
  }
  awayTeam: {
    teamId: string
    name: string
    score?: number
  }
  startTime: string
  status: 'SCHEDULED' | 'LIVE' | 'FINAL'
}

interface Player {
  playerId: string
  name: string
  team: string
  position: string
  jerseyNumber: string
}

interface PlayerStats {
  points: number
  rebounds: number
  assists: number
  steals: number
  blocks: number
  turnovers: number
  fantasyScore: number
}

export const NBAGameService = {
  getTodaysGames: async (): Promise<Game[]> => {
    try {
      const response = await axios.get(`${API_BASE_URL}/games/today`)
      return response.data
    } catch (error) {
      console.error('Error fetching games:', error)
      return []
    }
  },

  getTeamRoster: async (teamId: string): Promise<Player[]> => {
    try {
      const response = await axios.get(`${API_BASE_URL}/team/${teamId}/roster`)
      return response.data
    } catch (error) {
      console.error('Error fetching roster:', error)
      return []
    }
  },

  getPlayerStats: async (playerId: string): Promise<PlayerStats | null> => {
    try {
      const response = await axios.get(`${API_BASE_URL}/player/${playerId}/stats`)
      return response.data
    } catch (error) {
      console.error('Error fetching player stats:', error)
      return null
    }
  },

  getGamesByDate: async (date: string, provider?: 'sportsdata' | 'fastapi' | 'nba_api') => {
    try {
      const res = await axios.get(`/api/nba/games`, { params: { date, provider } })
      return res.data
    } catch (e) {
      console.error('getGamesByDate error', e)
      return []
    }
  },
} 