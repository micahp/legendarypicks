import { useEffect, useState } from 'react'
import type { NflTransaction } from '../types'

export function useNflTransactions(enabled: boolean) {
  const [data, setData] = useState<NflTransaction[] | null>(null)
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
        const response = await fetch('/api/nfl/transactions?limit=25')
        if (!response.ok) {
          if (!ignore) setError(`Transactions unavailable (${response.status})`)
          return
        }
        const json = await response.json()
        if (!ignore) setData(json.transactions ?? [])
      } catch {
        if (!ignore) setError('Unable to load transactions.')
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [enabled])

  return { data, loading, error }
}
