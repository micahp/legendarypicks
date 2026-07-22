import { useEffect, useState } from 'react'
import type { NflSeasonContext } from '../types'

export function useNflSeasonContext(enabled: boolean) {
  const [data, setData] = useState<NflSeasonContext | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!enabled) {
      setData(null)
      setError(null)
      setLoading(true) // ready for re-entry, no flash
      return
    }
    let ignore = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const response = await fetch('/api/nfl/season-context')
        if (!response.ok) {
          if (!ignore) setError(`Season context unavailable (${response.status})`)
          return
        }
        const json = await response.json()
        if (!ignore) setData(json)
      } catch {
        if (!ignore) setError('Unable to load season context.')
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [enabled])

  return { data, loading, error }
}
