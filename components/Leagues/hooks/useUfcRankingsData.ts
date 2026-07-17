import { useEffect, useState } from 'react'
import type { UFCRankings } from '../types'

export function useUfcRankingsData(isUFC: boolean, league: string) {
  const [rankings, setRankings] = useState<UFCRankings | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!isUFC || !league) return
    let ignore = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const response = await fetch('/api/ufc/rankings')
        if (!response.ok) throw new Error(`${response.status}`)
        const data: UFCRankings = await response.json()
        if (!ignore) setRankings(data)
      } catch (loadError: any) {
        if (!ignore) setError(loadError.message || 'Unable to load UFC rankings.')
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [isUFC, league])

  return { rankings, loading, error }
}
