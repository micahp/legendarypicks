import { useEffect, useRef, useState } from 'react'
import { SportsService, type ScheduleDatesResponse } from '../../../services/sports'

function instantToLocalDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-CA')
}

function findPrevDate(
  data: Pick<ScheduleDatesResponse, 'past_event_starts'>,
  anchor: string,
): string | null {
  const dates = data.past_event_starts
    .map(iso => instantToLocalDate(iso))
    .filter(d => d < anchor)
    .sort()
    .reverse()
  return dates[0] || null
}

function findNextDate(
  data: Pick<ScheduleDatesResponse, 'future_event_starts'>,
  anchor: string,
): string | null {
  const dates = data.future_event_starts
    .map(iso => instantToLocalDate(iso))
    .filter(d => d > anchor)
    .sort()
  return dates[0] || null
}

interface UseScheduleNavigationResult {
  prevDate: string | null
  nextDate: string | null
  loading: boolean
}

/**
 * Resolves the previous and next actual game dates for arrow navigation.
 * Fetches schedule-dates once per (league, anchor) and caches until the
 * anchor changes. Falls back to null on error (arrows will be disabled).
 * NFL returns null/null since it uses week-based navigation instead.
 */
export function useScheduleNavigation(
  isNFL: boolean,
  league: string,
  currentDate: string,
): UseScheduleNavigationResult {
  const [prevDate, setPrevDate] = useState<string | null>(null)
  const [nextDate, setNextDate] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const lastKey = useRef<string | null>(null)

  useEffect(() => {
    if (isNFL || !league || !currentDate) {
      setPrevDate(null)
      setNextDate(null)
      setLoading(false)
      lastKey.current = null // reset so re-entry refetches
      return
    }

    const key = `${league}:${currentDate}`
    if (lastKey.current === key) return
    lastKey.current = key

    let ignore = false
    setLoading(true)

    SportsService.getScheduleDates(league, currentDate).then(data => {
      if (ignore) return
      if (data) {
        setPrevDate(findPrevDate(data, currentDate))
        setNextDate(findNextDate(data, currentDate))
      } else {
        setPrevDate(null)
        setNextDate(null)
        lastKey.current = null // allow retry
      }
      setLoading(false)
    }).catch(() => {
      if (!ignore) {
        setPrevDate(null)
        setNextDate(null)
        lastKey.current = null // allow retry
        setLoading(false)
      }
    })

    return () => { ignore = true }
  }, [isNFL, league, currentDate])

  return { prevDate, nextDate, loading }
}
