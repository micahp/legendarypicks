import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/router'
import { localToday, validScheduleDate } from '../presentation'
import { useCoverage, isVouched } from './useCoverage'
import type { HubTab } from '../types'

type DateIntent = 'default' | 'user' | 'auto'

export function useLeagueRouteState() {
  const router = useRouter()
  const leagueQuery = router.query.league
  const league = (typeof leagueQuery === 'string' ? leagueQuery : '').toLowerCase()
  const isWorldCup = league === 'wc'
  const isUFC = league === 'ufc'
  const isNFL = league === 'nfl'

  // Whether a league may be shown at all comes from the coverage registry, not from a
  // list in this file. The literal `['mlb','nba','nhl','nfl']` that used to live here
  // was a second place to remember, and the failure mode is silent: add a league,
  // forget the array, and the hub renders empty tabs with no error anywhere.
  //
  // UFC and the World Cup are not team-stats leagues and are not in team_stats_coverage
  // at all, so they are named here as *shape*, not as permission — they render their own
  // tabs and neither one is gated on a team-stats row it will never have.
  const coverage = useCoverage()
  const coverageLoading = coverage.loading
  const supportsTeamStats = isVouched(coverage.statusFor(league))
  // The World Cup used to be offerable unconditionally, alongside UFC. It is not any
  // more (Micah, 2026-08-04): it keeps /scores, its API and its ingest, but stops
  // being a hub. Everything below that branches on `isWorldCup` is left in place —
  // this is the one line that decides whether anyone can get there.
  const offerable = isUFC || supportsTeamStats
  const validTabs: HubTab[] = isUFC
    ? ['rankings', 'schedule', 'predict']
    : isWorldCup
      ? ['standings', 'schedule']
      : isNFL
        ? ['camp', 'standings', 'stats', 'schedule']
        : ['standings', 'stats', 'schedule']

  const [activeTab, setActiveTab] = useState<HubTab>('standings')
  const [scheduleDate, setScheduleDate] = useState(() => localToday())
  const [dateIntent, setDateIntent] = useState<DateIntent>('default')
  const [nflWeek, setNflWeek] = useState<string>('')

  // Marks auto-resolve URL writes. Persists until user action or league change
  // so unrelated route events between write and round-trip don't reclassify it.
  const pendingAutoDate = useRef<string | null>(null)

  // Reset on league change
  const prevLeague = useRef(league)
  useEffect(() => {
    if (prevLeague.current !== league) {
      prevLeague.current = league
      pendingAutoDate.current = null
      setScheduleDate(localToday())
      setDateIntent('default')
    }
  }, [league])

  useEffect(() => {
    if (!router.isReady || !league) return

    const queryTab = typeof router.query.tab === 'string' ? router.query.tab : ''
    const nextTab = validTabs.includes(queryTab as HubTab)
      ? queryTab as HubTab
      : validTabs[0]
    const urlDate = typeof router.query.date === 'string' ? router.query.date : null
    const isNFL = league === 'nfl'

    // ── Determine date + intent from URL ──
    let nextDate: string
    let nextIntent: DateIntent

    // NFL: never use date from URL; always default to local today
    const effectiveUrlDate = isNFL ? null : urlDate

    if (effectiveUrlDate && validScheduleDate(effectiveUrlDate)) {
      if (pendingAutoDate.current === effectiveUrlDate) {
        nextDate = effectiveUrlDate
        nextIntent = 'auto'
      } else {
        nextDate = effectiveUrlDate
        nextIntent = 'user'
      }
    } else {
      nextDate = localToday()
      nextIntent = 'default'
    }

    setActiveTab(nextTab)
    setScheduleDate(nextDate)
    setDateIntent(nextIntent)

    // NFL week from URL
    const urlWeek = typeof router.query.week === 'string' ? router.query.week : ''
    setNflWeek(urlWeek)

    // ── URL housekeeping ──
    // NFL: never carry date; use week param instead
    const wantsDateInUrl = !isNFL && nextIntent !== 'default' && nextTab === 'schedule'
    const keepDateForIntent = !isNFL && nextIntent !== 'default' && nextTab !== 'schedule'
    const urlHasDate = router.query.date !== undefined
    const dateMismatch = wantsDateInUrl
      ? router.query.date !== nextDate
      : !keepDateForIntent && urlHasDate
    const tabChanged = router.query.tab !== nextTab

    if (tabChanged || dateMismatch) {
      const query: Record<string, string | string[] | undefined> = {
        ...router.query,
        league: router.query.league || league,
        tab: nextTab,
      }
      if (!isNFL && nextIntent !== 'default') {
        query.date = nextDate
      } else {
        delete query.date
      }
      void router.replace(
        { pathname: router.pathname, query },
        undefined,
        { shallow: true },
      )
    }
  }, [router.isReady, router.query.tab, router.query.date, router.query.week, league])

  const updateRoute = (tab: HubTab, date?: string, intent: DateIntent = 'user') => {
    const query: Record<string, string | string[] | undefined> = {
      ...router.query,
      league: router.query.league || league,
      tab,
    }
    // Preserve date for any non-default intent, regardless of tab
    if (intent !== 'default' && date) {
      query.date = date
    } else if (intent === 'default') {
      delete query.date
    }
    void router.replace(
      { pathname: router.pathname, query },
      undefined,
      { shallow: true },
    )
  }

  const selectTab = (tab: HubTab) => {
    setActiveTab(tab)
    updateRoute(tab, tab === 'schedule' ? scheduleDate : undefined, dateIntent)
  }

  const selectScheduleDate = (date: string) => {
    if (!validScheduleDate(date)) return
    pendingAutoDate.current = null // user action clobbers auto marker
    setScheduleDate(date)
    setDateIntent('user')
    updateRoute('schedule', date, 'user')
  }

  const resolveScheduleDate = (date: string) => {
    if (!validScheduleDate(date)) return
    pendingAutoDate.current = date
    setScheduleDate(date)
    setDateIntent('auto')
    updateRoute('schedule', date, 'auto')
  }

  const selectNflWeek = (key: string) => {
    setNflWeek(key)
    const query: Record<string, string | string[] | undefined> = {
      ...router.query,
      league: router.query.league || league,
      tab: 'schedule',
      week: key,
    }
    delete query.date
    void router.push(   // push so Back restores prior week
      { pathname: router.pathname, query },
      undefined,
      { shallow: true },
    )
  }

  const canonicalizeNflWeek = (key: string) => {
    setNflWeek(key)
    const query: Record<string, string | string[] | undefined> = {
      ...router.query,
      league: router.query.league || league,
      tab: 'schedule',
      week: key,
    }
    delete query.date
    void router.replace( // replace so default/invalid don't pollute history
      { pathname: router.pathname, query },
      undefined,
      { shallow: true },
    )
  }

  return {
    league,
    isWorldCup,
    isUFC,
    supportsTeamStats,
    offerable,
    coverageLoading,
    validTabs,
    activeTab,
    scheduleDate,
    dateIntent,
    nflWeek,
    selectTab,
    selectScheduleDate,
    resolveScheduleDate,
    selectNflWeek,
    canonicalizeNflWeek,
  }
}
