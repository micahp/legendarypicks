import axios from 'axios'

const API_BASE_URL = process.env.NEXT_PUBLIC_NBA_API_URL || 'http://localhost:8000/api'

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
  }
} 