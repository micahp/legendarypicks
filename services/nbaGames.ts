import axios from 'axios'
import { normalizeGame, Game } from './sports'

function normalizeBaseUrl(raw?: string): string {
  const fallback = 'http://localhost:8000/api'
  if (!raw || raw.trim() === '') return fallback
  const base = raw.trim()
  if (base.startsWith('/')) return base
  if (!/^https?:\/\//i.test(base)) return `http://${base}`
  return base
}

const API_BASE_URL = normalizeBaseUrl(process.env.NEXT_PUBLIC_NBA_API_URL)

interface Player {
  playerId: string
  name: string
  team: string
  position: string
  jerseyNumber: string
}

export const NBAGameService = {
  // Unified ESPN backend: today's NBA scoreboard, mapped to the shared internal Game shape.
  getTodaysGames: async (): Promise<Game[]> => {
    try {
      const response = await axios.get(`${API_BASE_URL}/nba/games`)
      return (Array.isArray(response.data) ? response.data : []).map(normalizeGame)
    } catch (error) {
      console.error('Error fetching games:', error)
      return []
    }
  },

  getTeamRoster: async (teamId: string): Promise<Player[]> => {
    try {
      const response = await axios.get(`${API_BASE_URL}/nba/team/${teamId}/roster`)
      return (Array.isArray(response.data) ? response.data : []).map((p: any) => ({
        playerId: String(p?.player_id ?? ''),
        name: p?.name ?? '',
        team: teamId,
        position: p?.position ?? '',
        jerseyNumber: String(p?.jersey ?? ''),
      }))
    } catch (error) {
      console.error('Error fetching roster:', error)
      return []
    }
  },

  // Scoreboard-by-date goes through the Next API route (provider switch: ESPN backend or SportsData.io).
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
