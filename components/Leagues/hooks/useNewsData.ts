import { useEffect, useState } from 'react'
import type { LeagueNews } from '../../News/LeagueSection'

/**
 * League news feed. `/api/news/{league}` answers with every league keyed by
 * name, but only the requested one carries populated `narratives`/`granular`
 * — the `conversations` block is cross-league by design. So this reads the
 * requested league's own entry rather than the whole payload, and an absent
 * entry is an empty feed, never another league's news.
 */
export function useNewsData(league: string, active: boolean) {
  const [news, setNews] = useState<LeagueNews | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // Only fetch when the tab is actually open — the league hub already loads
    // standings, leaders and team aggregates on mount, and news is the one of
    // those nobody sees unless they ask for it.
    if (!league || !active) return
    let ignore = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const response = await fetch(`/api/news/${league}`)
        if (!response.ok) {
          const body = await response.json().catch(() => null)
          throw new Error(body?.detail || 'News is unavailable.')
        }
        const payload = await response.json()
        if (ignore) return
        const own = payload?.leagues?.[league]
        setNews(own
          ? {
            conversations: Array.isArray(own.conversations) ? own.conversations : [],
            narratives: Array.isArray(own.narratives) ? own.narratives : [],
            granular: Array.isArray(own.granular) ? own.granular : [],
            other: typeof own.other === 'number' ? own.other : 0,
          }
          : { conversations: [], narratives: [], granular: [], other: 0 })
      } catch (err) {
        if (!ignore) {
          setError(err instanceof Error && err.message ? err.message : 'Unable to load news.')
          setNews(null)
        }
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [league, active])

  return { news, loading, error }
}
