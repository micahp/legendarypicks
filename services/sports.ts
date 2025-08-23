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

export const SportsService = {
  getGames: async (league: string) => {
    try {
      const res = await axios.get(`${API_BASE_URL}/${league}/games`)
      return res.data
    } catch (err) {
      console.error('Error fetching games', err)
      return []
    }
  },

  getPlayerStats: async (league: string, playerId: string) => {
    try {
      const res = await axios.get(`${API_BASE_URL}/${league}/players/${playerId}`)
      return res.data
    } catch (err) {
      console.error('Error fetching player', err)
      return null
    }
  },

  submitPrediction: async (league: string, gameId: string, predictedWinner: string) => {
    try {
      const res = await axios.post(`${API_BASE_URL}/predictions`, { league, gameId, predictedWinner })
      return res.data
    } catch (err) {
      console.error('Error submitting prediction', err)
      return null
    }
  },

  getPredictions: async () => {
    try {
      const res = await axios.get(`${API_BASE_URL}/predictions`)
      return res.data
    } catch (err) {
      console.error('Error getting predictions', err)
      return []
    }
  }
}
