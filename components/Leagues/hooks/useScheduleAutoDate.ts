import { useEffect, useRef, useState } from 'react'
import { SportsService, type ScheduleDatesResponse } from '../../../services/sports'
import { localToday } from '../presentation'

type DateIntent = 'default' | 'user' | 'auto'

function instantToLocalDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-CA')
}

function resolveDate(
  data: Pick<ScheduleDatesResponse, 'future_event_starts' | 'past_event_starts'>,
  anchor: string,
): { date: string; explanation: string } | null {
  const futureDates = data.future_event_starts
    .map(iso => instantToLocalDate(iso))
    .filter(d => d > anchor)
    .sort()

  const pastDates = data.past_event_starts
    .map(iso => instantToLocalDate(iso))
    .filter(d => d < anchor)
    .sort()
    .reverse()

  const nextDate = futureDates[0]
  if (nextDate) return { date: nextDate, explanation: `Next scheduled date` }

  const prevDate = pastDates[0]
  if (prevDate) return { date: prevDate, explanation: `Latest scheduled date` }

  return null
}

interface UseScheduleAutoDateResult {
  resolved: boolean
  resolvedDate: string | null
  explanation: string | null
  /** "{league}:{anchor}" — page effect validates this against current route */
  resolutionKey: string | null
}

export function useScheduleAutoDate(
  enabled: boolean,
  league: string,
  scheduleDate: string,
  gamesCount: number,
  loading: boolean,
  error: string | null,
  dateIntent: DateIntent,
): UseScheduleAutoDateResult {
  const [resolved, setResolved] = useState(false)
  const [resolvedDate, setResolvedDate] = useState<string | null>(null)
  const [explanation, setExplanation] = useState<string | null>(null)
  const [resolutionKey, setResolutionKey] = useState<string | null>(null)
  const triggeredKey = useRef<string | null>(null)

  // Clear on user action OR when Schedule tab closes (enabled→false allows retry)
  useEffect(() => {
    if (dateIntent === 'user' && resolved) {
      setResolved(false)
      setResolvedDate(null)
      setExplanation(null)
      setResolutionKey(null)
    }
    if (!enabled) {
      triggeredKey.current = null
    }
  }, [dateIntent, enabled, resolved])

  // Auto-resolve effect — only for 'default' intent + schedule tab active
  useEffect(() => {
    if (!enabled) return
    if (dateIntent !== 'default') return
    if (!league) return
    if (scheduleDate !== localToday()) return
    if (loading) return
    if (error) return
    if (gamesCount > 0) return

    const key = `${league}:${scheduleDate}`
    if (triggeredKey.current === key) return

    let ignore = false

    SportsService.getScheduleDates(league, scheduleDate).then(data => {
      if (ignore) return
      triggeredKey.current = key // mark only after successful conditions pass
      if (!data) return
      const result = resolveDate(data, scheduleDate)
      if (result) {
        setResolvedDate(result.date)
        setExplanation(result.explanation)
        setResolutionKey(key)
        setResolved(true)
      }
    })

    return () => { ignore = true }
  }, [enabled, dateIntent, league, scheduleDate, gamesCount, loading, error])

  return { resolved, resolvedDate, explanation, resolutionKey }
}
