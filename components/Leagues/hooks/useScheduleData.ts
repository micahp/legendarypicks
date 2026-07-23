import { useEffect, useMemo, useState } from 'react'
import { SportsService } from '../../../services/sports'
import type { Game } from '../../../services/sports'
import { formatScheduleDate, localToday } from '../presentation'
import type { HubTab } from '../types'

export function useScheduleData(
  league: string,
  activeTab: HubTab,
  scheduleDate: string,
) {
  const [games, setGames] = useState<Game[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!league || activeTab !== 'schedule') return
    let ignore = false
    const load = async () => {
      setGames([])
      setLoading(true)
      setError(null)
      try {
        // Strict local-date fetch: if either neighbor backend request fails,
        // the whole load fails → error → no auto-resolve.
        const schedule = await SportsService.getGamesByLocalDate(league, scheduleDate, { strict: true })
        if (!ignore) setGames(Array.isArray(schedule) ? schedule : [])
      } catch {
        if (!ignore) setError('Unable to load schedule.')
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [league, scheduleDate, activeTab])

  const groups = useMemo(() => {
    const sorted = [...games].sort(
      (left, right) => new Date(left.startTime).getTime() - new Date(right.startTime).getTime(),
    )
    return sorted.reduce((result, game) => {
      const subtitle = game.subtitle || ''
      if (!result[subtitle]) result[subtitle] = []
      result[subtitle].push(game)
      return result
    }, {} as Record<string, Game[]>)
  }, [games])

  return {
    games,
    groups,
    loading,
    error,
    formattedDate: formatScheduleDate(scheduleDate),
    isToday: scheduleDate === localToday(),
  }
}
