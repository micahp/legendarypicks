import { useEffect, useState } from 'react'
import { useRouter } from 'next/router'
import { localToday, validScheduleDate } from '../presentation'
import type { HubTab } from '../types'

export function useLeagueRouteState() {
  const router = useRouter()
  const leagueQuery = router.query.league
  const league = (typeof leagueQuery === 'string' ? leagueQuery : '').toLowerCase()
  const isWorldCup = league === 'wc'
  const isUFC = league === 'ufc'
  const isNFL = league === 'nfl'
  const supportsTeamStats = ['mlb', 'nba', 'nhl', 'nfl'].includes(league)
  const validTabs: HubTab[] = isUFC
    ? ['rankings', 'schedule', 'predict']
    : isWorldCup
      ? ['standings', 'schedule']
      : isNFL
        ? ['camp', 'standings', 'stats', 'schedule']
        : ['standings', 'stats', 'schedule']

  const [activeTab, setActiveTab] = useState<HubTab>('standings')
  const [scheduleDate, setScheduleDate] = useState(() => localToday())

  useEffect(() => {
    if (!router.isReady || !league) return
    const queryTab = typeof router.query.tab === 'string' ? router.query.tab : ''
    const nextTab = validTabs.includes(queryTab as HubTab)
      ? queryTab as HubTab
      : validTabs[0]
    const nextDate = validScheduleDate(router.query.date)
      ? router.query.date
      : localToday()
    setActiveTab(nextTab)
    setScheduleDate(nextDate)

    const tabNeedsUpdate = router.query.tab !== nextTab
    const dateNeedsUpdate = nextTab === 'schedule' && router.query.date !== nextDate
    if (tabNeedsUpdate || dateNeedsUpdate) {
      const query: Record<string, string | string[] | undefined> = {
        ...router.query,
        league: router.query.league || league,
        tab: nextTab,
      }
      if (nextTab === 'schedule') query.date = nextDate
      void router.replace(
        { pathname: router.pathname, query },
        undefined,
        { shallow: true },
      )
    }
  }, [router.isReady, router.query.tab, router.query.date, league])

  const updateRoute = (tab: HubTab, date = scheduleDate) => {
    const query: Record<string, string | string[] | undefined> = {
      ...router.query,
      league: router.query.league || league,
      tab,
    }
    if (tab === 'schedule') query.date = date
    void router.replace(
      { pathname: router.pathname, query },
      undefined,
      { shallow: true },
    )
  }

  const selectTab = (tab: HubTab) => {
    setActiveTab(tab)
    updateRoute(tab)
  }

  const selectScheduleDate = (date: string) => {
    if (!validScheduleDate(date)) return
    setScheduleDate(date)
    updateRoute('schedule', date)
  }

  const shiftScheduleDay = (delta: number) => {
    const date = new Date(`${scheduleDate}T12:00:00`)
    date.setDate(date.getDate() + delta)
    selectScheduleDate(date.toLocaleDateString('en-CA'))
  }

  return {
    league,
    isWorldCup,
    isUFC,
    supportsTeamStats,
    validTabs,
    activeTab,
    scheduleDate,
    selectTab,
    selectScheduleDate,
    shiftScheduleDay,
  }
}
