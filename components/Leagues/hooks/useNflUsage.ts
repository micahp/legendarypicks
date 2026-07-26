import { useCallback, useEffect, useState } from 'react'
import type { NflUsageResponse } from '../types'

export function useNflUsage(playerId: number, season?: number) {
  const [data, setData] = useState<NflUsageResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const buildUrl = useCallback(() => {
    const params = new URLSearchParams({ weeks: '8' })
    if (season !== undefined) params.set('season', String(season))
    return `/api/nfl/usage/${playerId}?${params.toString()}`
  }, [playerId, season])

  useEffect(() => {
    let ignore = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const response = await fetch(buildUrl())
        if (!response.ok) {
          if (!ignore) setError(`Usage data unavailable (${response.status})`)
          return
        }
        const json = await response.json()
        if (!ignore) setData(json)
      } catch {
        if (!ignore) setError('Unable to load usage data.')
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [buildUrl])

  return { data, loading, error }
}
