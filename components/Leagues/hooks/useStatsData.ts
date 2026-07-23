import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/router'
import type {
  HubTab,
  LeadersData,
  SubView,
  TeamAggregatesData,
} from '../types'

type MlbType = 'batting' | 'pitching'

interface StatsDataOptions {
  league: string
  activeTab: HubTab
  isWorldCup: boolean
  isUFC: boolean
  supportsTeamStats: boolean
}

export function useStatsData({
  league,
  activeTab,
  isWorldCup,
  isUFC,
  supportsTeamStats,
}: StatsDataOptions) {
  const router = useRouter()
  const [subView, setSubView] = useState<SubView>('players')
  const [leaders, setLeaders] = useState<LeadersData | null>(null)
  const [playerLoading, setPlayerLoading] = useState(false)
  const [playerError, setPlayerError] = useState<string | null>(null)
  const [playerFilterError, setPlayerFilterError] = useState(false)
  const [mlbType, setMlbType] = useState<MlbType>('batting')
  const [teamAggregates, setTeamAggregates] = useState<TeamAggregatesData | null>(null)
  const [teamLoading, setTeamLoading] = useState(false)
  const [teamError, setTeamError] = useState<string | null>(null)
  const [teamCategory, setTeamCategory] = useState<string | null>(null)

  // These refs preserve the race guards from the original page controller.
  const subViewRef = useRef<SubView>('players')
  const queryRef = useRef(router.query)
  const canonicalRef = useRef<string | null>(null)

  useEffect(() => {
    if (!router.isReady || !league || router.query.tab !== 'stats') return
    const nextView: SubView = supportsTeamStats && router.query.view === 'teams'
      ? 'teams'
      : 'players'
    const nextType: MlbType = router.query.type === 'pitching'
      ? 'pitching'
      : 'batting'
    setSubView(nextView)
    if (league === 'mlb' && nextView === 'players') setMlbType(nextType)

    const query: Record<string, string | string[] | undefined> = { ...router.query }
    let needsUpdate = false
    if (router.query.view !== nextView) {
      query.view = nextView
      needsUpdate = true
    }
    if (league === 'mlb' && nextView === 'players') {
      if (router.query.type !== nextType) {
        query.type = nextType
        needsUpdate = true
      }
    } else if (router.query.type !== undefined) {
      delete query.type
      needsUpdate = true
    }
    if (nextView === 'teams') {
      for (const key of ['category', 'stat']) {
        if (query[key] !== undefined) {
          delete query[key]
          needsUpdate = true
        }
      }
    }
    if (needsUpdate) {
      void router.replace(
        { pathname: router.pathname, query },
        undefined,
        { shallow: true },
      )
    }
  }, [
    router.isReady,
    router.query.tab,
    router.query.view,
    router.query.type,
    router.query.category,
    router.query.stat,
    league,
    supportsTeamStats,
  ])

  useEffect(() => {
    setLeaders(null)
    setPlayerError(null)
    setPlayerFilterError(false)
  }, [league, mlbType])

  useEffect(() => {
    setTeamAggregates(null)
    setTeamError(null)
  }, [league])

  const replaceStatsQuery = (
    updates: Record<string, string>,
    remove: string[] = [],
  ) => {
    const query: Record<string, string | string[] | undefined> = {
      ...router.query,
      league: router.query.league || league,
      tab: 'stats',
      ...updates,
    }
    for (const key of remove) delete query[key]
    if (league !== 'mlb') delete query.type
    void router.replace(
      { pathname: router.pathname, query },
      undefined,
      { shallow: true },
    )
  }

  const selectSubView = (view: SubView) => {
    setSubView(view)
    if (view === 'teams') {
      replaceStatsQuery({ view }, ['type', 'category', 'stat'])
    } else {
      replaceStatsQuery(
        league === 'mlb' ? { view, type: mlbType } : { view },
        ['category', 'stat'],
      )
    }
  }

  const selectMlbType = (type: MlbType) => {
    setLeaders(null)
    replaceStatsQuery({ view: 'players', type }, ['category', 'stat'])
  }

  const selectSeason = (season: string) => {
    setLeaders(null)
    const updates: Record<string, string> = { view: 'players', season }
    if (league === 'mlb') updates.type = mlbType
    replaceStatsQuery(updates, ['category', 'stat'])
  }

  const selectStatCategory = (category: string) => {
    replaceStatsQuery({ view: 'players', category }, ['stat'])
  }

  const selectSortMetric = (stat: string) => {
    if (!leaders?.category) return
    replaceStatsQuery({ view: 'players', category: leaders.category, stat })
  }

  const resetStatsFilters = () => {
    setPlayerError(null)
    setPlayerFilterError(false)
    const updates: Record<string, string> = { view: 'players' }
    if (league === 'mlb') {
      updates.type = router.query.type === 'pitching' ? 'pitching' : 'batting'
      setMlbType(updates.type as MlbType)
    }
    replaceStatsQuery(updates, ['category', 'stat'])
  }

  useEffect(() => {
    if (
      !router.isReady
      || !league
      || activeTab !== 'stats'
      || subView !== 'players'
      || isWorldCup
      || isUFC
    ) return
    if (league === 'mlb' && router.query.type !== mlbType) return

    const requestedCategory = typeof router.query.category === 'string'
      ? router.query.category
      : ''
    const requestedStat = typeof router.query.stat === 'string'
      ? router.query.stat
      : ''
    const requestedSeason = typeof router.query.season === 'string'
      ? router.query.season
      : ''
    const signature = `${league}|${mlbType}|${requestedSeason}|${requestedCategory}|${requestedStat}`
    if (canonicalRef.current === signature) {
      canonicalRef.current = null
      return
    }

    let ignore = false
    const load = async () => {
      setPlayerLoading(true)
      setPlayerError(null)
      setPlayerFilterError(false)
      try {
        const params = new URLSearchParams({ limit: '25' })
        if (league === 'mlb') params.set('type', mlbType)
        const category = requestedCategory || null
        const stat = requestedStat || null
        const season = requestedSeason || null
        if (category) params.set('category', category)
        if (stat) params.set('stat', stat)
        if (season) params.set('season', season)
        const response = await fetch(`/api/${league}/leaders?${params.toString()}`)
        if (!response.ok) {
          let detail = `HTTP ${response.status}`
          try {
            const payload = await response.json()
            if (typeof payload?.detail === 'string') detail = payload.detail
            else if (payload?.detail != null) detail = JSON.stringify(payload.detail)
          } catch { /* retain the HTTP detail */ }
          const requestError: any = new Error(detail)
          requestError.status = response.status
          throw requestError
        }
        const payload: any = await response.json()
        if (!Array.isArray(payload?.categories) || !Array.isArray(payload?.columns)) {
          const contractError: any = new Error('Incompatible stats response.')
          if (category || stat) contractError.status = 400
          throw contractError
        }
        const data: LeadersData = {
          ...payload,
          change_metric: payload.change_metric ?? null,
          comparison: payload.comparison ?? null,
          changes: Array.isArray(payload.changes) ? payload.changes : [],
        }
        if (!ignore) {
          setLeaders(data)
          if (
            queryRef.current.tab === 'stats'
            && ((!category && data.category) || (!stat && data.stat) || (!season && data.season != null))
          ) {
            const query: Record<string, string | string[] | undefined> = {
              ...queryRef.current,
            }
            if (!category && data.category) query.category = data.category
            if (!stat && data.stat) query.stat = data.stat
            if (!season && data.season != null) query.season = String(data.season)
            canonicalRef.current = `${league}|${mlbType}|${(query.season as string) || ''}|${(query.category as string) || ''}|${(query.stat as string) || ''}`
            void router.replace(
              { pathname: router.pathname, query },
              undefined,
              { shallow: true },
            )
          }
        }
      } catch (loadError: any) {
        if (!ignore) {
          setLeaders(null)
          setPlayerFilterError(loadError?.status === 400)
          setPlayerError(
            `Unable to load player stats: ${loadError?.message || 'Unknown error'}`,
          )
        }
      } finally {
        if (!ignore) setPlayerLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [
    router.isReady,
    router.query.category,
    router.query.stat,
    router.query.type,
    router.query.season,
    league,
    mlbType,
    isWorldCup,
    isUFC,
    activeTab,
    subView,
  ])

  useEffect(() => { subViewRef.current = subView }, [subView])
  useEffect(() => { queryRef.current = router.query }, [router.query])

  useEffect(() => {
    if (!router.isReady || !supportsTeamStats || activeTab !== 'stats') return
    let ignore = false
    const load = async () => {
      setTeamLoading(true)
      setTeamError(null)
      try {
        const response = await fetch(`/api/${league}/team-aggregates`)
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const payload: TeamAggregatesData = await response.json()
        if (!payload.supported || !Array.isArray(payload.teams)) {
          throw new Error('Measured team coverage is incomplete.')
        }
        if (!ignore) setTeamAggregates(payload)
      } catch (loadError: any) {
        if (!ignore) {
          setTeamAggregates(null)
          setTeamError(loadError?.message || 'Unable to load team stats.')
          if (subViewRef.current === 'teams') {
            setSubView('players')
            const query: Record<string, string | string[] | undefined> = {
              ...queryRef.current,
              view: 'players',
            }
            if (league === 'mlb') query.type = mlbType
            delete query.category
            delete query.stat
            void router.replace(
              { pathname: router.pathname, query },
              undefined,
              { shallow: true },
            )
          }
        }
      } finally {
        if (!ignore) setTeamLoading(false)
      }
    }
    load()
    return () => { ignore = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router.isReady, league, supportsTeamStats, activeTab])

  return {
    subView,
    leaders,
    playerLoading,
    playerError,
    playerFilterError,
    mlbType,
    teamAggregates,
    teamLoading,
    teamError,
    teamCategory,
    selectSubView,
    selectMlbType,
    selectSeason,
    selectStatCategory,
    selectSortMetric,
    resetStatsFilters,
    selectTeamCategory: setTeamCategory,
  }
}
