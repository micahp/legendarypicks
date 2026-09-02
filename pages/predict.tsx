import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/router'
import Head from 'next/head'
import { getDeviceId } from '../lib/deviceId'
import { trackPickMade } from '../lib/analytics'
import { groupSportNavigation, leagueNavigationLabel, SportGroup } from '../components/Navigation/sports'
import HorizontalScrollRail from '../components/HorizontalScrollRail'

type Side = 'A' | 'B' | 'D'
interface Match { matchKey: string; teamA: string; teamB: string; title: string; league: string; startTime: number | null; logoA: string | null; logoB: string | null; seedA?: number | null; seedB?: number | null; live: boolean; finished: boolean; allowDraw?: boolean; favorite?: { name: string; pct: number } | null }
interface TitleOption { slug: string; label: string; match_count: number; live_count: number; result_count: number; next_start: number | null }
interface PredictSlate { schema_version: string; selected_title: { slug: string; label: string }; titles: TitleOption[]; matches: Match[]; match_count: number; has_more: boolean; building: boolean; error: string | null; source: string | null }
interface MyPick { matchKey: string; side: Side; teamA?: string; teamB?: string; league?: string; createdAt: number; lockAt: number | null; settledAt: number | null; result: 'win' | 'loss' | 'void' | null; points: number | null }
interface RecordT { wins: number; losses: number; voids: number; streak: number }
interface CrowdT { countA: number; countB: number; countDraw?: number; total: number; shareA: number | null }

const EMPTY_RECORD: RecordT = { wins: 0, losses: 0, voids: 0, streak: 0 }
const DISPLAY_TIME_ZONE = 'America/New_York'
const PREDICTION_COMPETITIONS = [
  { league: 'esports', sport: 'esports' },
  { league: 'mlb', sport: 'baseball' },
  { league: 'nba', sport: 'basketball' },
  { league: 'nhl', sport: 'hockey' },
  { league: 'nfl', sport: 'football' },
  { league: 'ncaaf', sport: 'football' },
  { league: 'mls', sport: 'soccer' },
  { league: 'lcup', sport: 'soccer' },
  { league: 'wc', sport: 'soccer' },
  { league: 'atp', sport: 'tennis' },
  { league: 'wta', sport: 'tennis' },
  { league: 'ufc', sport: 'mma' },
]
const SPORT_GROUPS = groupSportNavigation(PREDICTION_COMPETITIONS, 'predict')

function groupForRequest(value: string): { group: SportGroup; legacyLeague?: string } {
  const direct = SPORT_GROUPS.find(group => group.key === value || group.sport === value)
  if (direct) return { group: direct }
  const byLeague = SPORT_GROUPS.find(group => group.competitions.some(item => item.league === value))
  if (byLeague) return { group: byLeague, legacyLeague: value }
  return { group: SPORT_GROUPS.find(group => group.sport === 'esports') || SPORT_GROUPS[0] }
}

function dayKey(startTime: number | null): string {
  if (!startTime) return 'unscheduled'
  return new Intl.DateTimeFormat('en-CA', { timeZone: DISPLAY_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(startTime))
}

function dayLabel(startTime: number | null): string {
  if (!startTime) return 'Date to be announced'
  return new Intl.DateTimeFormat(undefined, { timeZone: DISPLAY_TIME_ZONE, weekday: 'long', month: 'long', day: 'numeric' }).format(new Date(startTime))
}

function timeLabel(startTime: number | null): string {
  if (!startTime) return 'Time TBA'
  return new Intl.DateTimeFormat(undefined, { timeZone: DISPLAY_TIME_ZONE, hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }).format(new Date(startTime))
}

function recordForTitle(picks: MyPick[], title: string): RecordT {
  const scoped = picks.filter(p => p.matchKey.split('||')[2] === title && p.settledAt !== null).sort((a, b) => (b.settledAt || 0) - (a.settledAt || 0))
  const results = scoped.map(p => p.result)
  let streak = 0
  for (const result of results) {
    if (result === 'void') continue
    if (!streak) streak = result === 'win' ? 1 : -1
    else if ((streak > 0 && result === 'win') || (streak < 0 && result === 'loss')) streak += streak > 0 ? 1 : -1
    else break
  }
  return { wins: results.filter(r => r === 'win').length, losses: results.filter(r => r === 'loss').length, voids: results.filter(r => r === 'void').length, streak }
}

function adaptUfcSlate(data: any): PredictSlate {
  const matches: Match[] = (data.fights || []).map((fight: any) => ({
    matchKey: fight.fightKey, teamA: fight.away.name, teamB: fight.home.name,
    title: fight.event || 'UFC', league: 'ufc', startTime: fight.lockAt,
    logoA: null, logoB: null, live: fight.state === 'in', finished: fight.state === 'post',
  }))
  return { schema_version: 'ufc-predict-adapter-v1', selected_title: { slug: 'ufc', label: 'UFC' }, titles: [], matches, match_count: matches.length, has_more: false, building: false, error: data.error || null, source: 'ufc' }
}

export default function PredictPage() {
  const router = useRouter()
  const requestedSport = typeof router.query.sport === 'string' ? router.query.sport.toLowerCase() : 'esports'
  const { group: selectedGroup, legacyLeague } = groupForRequest(requestedSport)
  const requestedLeague = typeof router.query.league === 'string' ? router.query.league.toLowerCase() : legacyLeague
  const selectedCompetition = requestedLeague && selectedGroup.competitions.some(item => item.league === requestedLeague) ? requestedLeague : undefined
  const selectedLeagues = selectedCompetition ? [selectedCompetition] : selectedGroup.competitions.map(item => item.league)
  const selectedLeagueKey = selectedLeagues.join(',')
  const sport = selectedGroup.sport
  const urlTitle = typeof router.query.title === 'string' ? router.query.title : undefined
  const isEsports = sport === 'esports'
  const isUfc = selectedLeagues.length === 1 && selectedLeagues[0] === 'ufc'
  const sportLabel = selectedCompetition ? leagueNavigationLabel(selectedCompetition) : selectedGroup.label
  const [slate, setSlate] = useState<PredictSlate | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [reloadTick, setReloadTick] = useState(0)
  const [myPicks, setMyPicks] = useState<MyPick[]>([])
  const [apiRecord, setApiRecord] = useState<RecordT>(EMPTY_RECORD)
  const [submittingKey, setSubmittingKey] = useState<string | null>(null)
  const [crowd, setCrowd] = useState<Record<string, CrowdT>>({})

  const loadPicks = useCallback(async () => {
    const leagueQuery = selectedLeagues.length === 1
      ? `league=${encodeURIComponent(selectedLeagues[0])}`
      : `leagues=${encodeURIComponent(selectedLeagueKey)}`
    const endpoint = isEsports ? '/api/esports/picks/me' : isUfc ? '/api/ufc/picks/me' : `/api/sports/picks/me?${leagueQuery}`
    const response = await fetch(endpoint, { headers: { 'X-Device-Id': getDeviceId() } })
    if (!response.ok) throw new Error('failed to load picks')
    const data = await response.json()
    const picks: MyPick[] = isUfc ? (data.picks || []).map((pick: any) => ({
      matchKey: pick.fightKey, side: pick.side === 'away' ? 'A' : 'B',
      teamA: pick.side === 'away' ? pick.fighterName : pick.opponentName,
      teamB: pick.side === 'home' ? pick.fighterName : pick.opponentName,
      league: 'ufc', createdAt: pick.createdAt, lockAt: pick.lockAt,
      settledAt: pick.settledAt, result: pick.result, points: pick.points,
    })) : (data.picks || [])
    setMyPicks(picks)
    setApiRecord(data.record || EMPTY_RECORD)
  }, [isEsports, isUfc, selectedLeagueKey])

  useEffect(() => {
    if (!router.isReady) return
    let active = true
    ;(async () => {
      setLoading(true); setFetchError(null); setSlate(null); setCrowd({})
      try {
        const leagueQuery = selectedLeagues.length === 1
          ? `league=${encodeURIComponent(selectedLeagues[0])}`
          : `leagues=${encodeURIComponent(selectedLeagueKey)}`
        const endpoint = isEsports ? `/api/esports/predict${urlTitle ? `?title=${encodeURIComponent(urlTitle)}` : ''}` : isUfc ? '/api/ufc/upcoming' : `/api/sports/predict?${leagueQuery}`
        const response = await fetch(endpoint)
        if (!response.ok) {
          const body = await response.json().catch(() => null)
          throw new Error(body?.detail || body?.error || `Failed to load predict slate (${response.status})`)
        }
        const body = await response.json()
        if (active) setSlate(isUfc ? adaptUfcSlate(body) : body)
      } catch (error) {
        if (active) setFetchError(error instanceof Error ? error.message : 'Failed to load predict slate')
      } finally { if (active) setLoading(false) }
    })()
    return () => { active = false }
  }, [router.isReady, sport, selectedLeagueKey, isEsports, isUfc, urlTitle, reloadTick])

  useEffect(() => {
    let active = true
    setMyPicks([]); setApiRecord(EMPTY_RECORD)
    loadPicks().catch(() => { if (active) setMyPicks([]) })
    return () => { active = false }
  }, [loadPicks])

  useEffect(() => {
    let active = true
    const missing = myPicks.map(p => p.matchKey).filter(key => !(key in crowd))
    if (!missing.length) return
    ;(async () => {
      const results = await Promise.all(missing.map(async key => {
        const pick = myPicks.find(candidate => candidate.matchKey === key)
        const endpoint = isEsports ? `/api/esports/crowd?matchKey=${encodeURIComponent(key)}` : isUfc ? `/api/ufc/crowd?fightKey=${encodeURIComponent(key)}` : `/api/sports/crowd?league=${encodeURIComponent(pick?.league || '')}&matchKey=${encodeURIComponent(key)}`
        try {
          const response = await fetch(endpoint)
          if (!response.ok) return [key, null] as const
          const value = await response.json()
          return [key, isUfc ? { countA: value.countAway, countB: value.countHome, total: value.total, shareA: value.total ? value.countAway / value.total : null } : value] as const
        } catch { return [key, null] as const }
      }))
      if (!active) return
      setCrowd(previous => { const next = { ...previous }; for (const [key, value] of results) if (value) next[key] = value; return next })
    })()
    return () => { active = false }
  }, [myPicks, crowd, isEsports, isUfc])

  const makePick = async (match: Match, side: Side) => {
    setSubmittingKey(match.matchKey)
    try {
      const endpoint = isEsports ? '/api/esports/picks' : isUfc ? '/api/ufc/picks' : '/api/sports/picks'
      const body = isUfc ? { fightKey: match.matchKey, side: side === 'A' ? 'away' : 'home', method: null } : isEsports ? { matchKey: match.matchKey, side, lockAt: match.startTime } : { league: match.league, matchKey: match.matchKey, side }
      const response = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Device-Id': getDeviceId() }, body: JSON.stringify(body) })
      if (response.ok) { trackPickMade({ league: match.league, surface: 'predict', pick_id: match.matchKey }); await loadPicks() }
    } finally { setSubmittingKey(null) }
  }
  const selectSport = (group: SportGroup) => {
    const routeSport = group.competitions.length === 1 ? group.competitions[0].league : group.sport
    return router.push({ pathname: '/predict', query: routeSport === 'esports' && urlTitle ? { sport: routeSport, title: urlTitle } : { sport: routeSport } }, undefined, { shallow: true })
  }
  const selectCompetition = (group: SportGroup, league?: string) => router.push({ pathname: '/predict', query: league ? { sport: group.sport, league } : { sport: group.sport } }, undefined, { shallow: true })
  const selectTitle = (slug: string) => router.push({ pathname: '/predict', query: { sport: 'esports', title: slug } }, undefined, { shallow: true })

  const selectedLabel = isEsports && slate ? slate.selected_title.label : sportLabel
  const allEsports = isEsports && slate?.selected_title.slug === 'all'
  const record = useMemo(() => isEsports && slate && !allEsports ? recordForTitle(myPicks, slate.selected_title.label) : apiRecord, [isEsports, slate, allEsports, myPicks, apiRecord])
  const settled = useMemo(() => myPicks.filter(p => p.settledAt !== null && (!isEsports || !slate || allEsports || p.matchKey.split('||')[2] === slate.selected_title.label)).sort((a, b) => (b.settledAt || 0) - (a.settledAt || 0)), [myPicks, isEsports, slate, allEsports])
  const hasRecord = record.wins + record.losses + record.voids > 0
  const selectedTitle = slate?.titles.find(title => title.slug === slate.selected_title.slug)
  const matchDays = useMemo(() => {
    const groups: Array<{ key: string; startTime: number | null; matches: Match[] }> = []
    for (const match of slate?.matches || []) {
      const key = dayKey(match.startTime)
      const current = groups.find(group => group.key === key)
      if (current) current.matches.push(match)
      else groups.push({ key, startTime: match.startTime, matches: [match] })
    }
    return groups
  }, [slate])

  return <>
    <Head><title>Predict — Legendary Picks</title><meta name="description" content="Pick winners across every sport and track your record." /></Head>
    <div className="mx-auto max-w-2xl px-4 py-6">
      <div className="flex items-center justify-between gap-3">
        <div><div className="flex items-center gap-2"><h1 className="text-3xl font-extrabold tracking-tight text-zinc-50">Predict</h1><span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-400">{sportLabel}</span></div><p className="mt-1 text-sm text-zinc-500">Pick winners across every sport. Track your record.</p></div>
        <div className="text-right">{!hasRecord ? <span className="text-sm text-zinc-500">Make your first pick</span> : <div className="flex items-center gap-2"><span className="font-mono text-lg font-bold tabular-nums text-zinc-100">{record.wins}–{record.losses}</span>{record.streak !== 0 && <span className="text-zinc-500">·</span>}{record.streak > 0 && <span className="font-mono text-lg font-bold text-[#22c55e]">W{record.streak}</span>}{record.streak < 0 && <span className="font-mono text-lg font-bold text-[#ff3d71]">L{-record.streak}</span>}</div>}</div>
      </div>
      <PredictionSportPills groups={SPORT_GROUPS} selectedGroup={selectedGroup} selectedLeague={selectedCompetition} onSelectGroup={selectSport} onSelectCompetition={selectCompetition} />
      {isEsports && slate && slate.titles.length > 0 && <HorizontalScrollRail
        className="mt-3"
        label="Esports titles"
        previousLabel="Previous esports titles"
        nextLabel="Next esports titles"
        railClassName="flex gap-1.5 pb-1"
      ><FilterPill active={allEsports} onClick={() => selectTitle('all')}>All Esports{slate.titles.some(title => title.match_count > 0) && <span className="ml-1 opacity-60">{slate.titles.reduce((total, title) => total + title.match_count, 0)}</span>}</FilterPill>{slate.titles.map(title => <FilterPill key={title.slug} active={title.slug === slate.selected_title.slug} onClick={() => selectTitle(title.slug)}>{title.live_count > 0 && <span className="mr-1 text-emerald-400">●</span>}{title.label}{title.match_count > 0 && <span className="ml-1 opacity-60">{title.match_count}</span>}</FilterPill>)}</HorizontalScrollRail>}
      {fetchError && <div className="mt-4 flex items-center justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300"><span>{fetchError}</span><button onClick={() => setReloadTick(t => t + 1)} className="shrink-0 font-medium text-red-200 hover:text-red-100">Retry</button></div>}
      {!fetchError && slate?.error && <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">{slate.error}</div>}
      <div className="mt-6 mb-3 text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">{selectedLabel} matches</div>
      {loading ? <MatchSkeleton /> : !fetchError && slate && slate.matches.length === 0 ? <p className="text-sm text-zinc-500">{slate.building ? `Still loading the latest ${selectedLabel} slate — check back in a moment.` : `No open ${selectedLabel} games in the stored slate right now.`}{selectedTitle?.next_start ? <> Next match {new Date(selectedTitle.next_start).toLocaleString(undefined, { timeZone: DISPLAY_TIME_ZONE, month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })}.</> : null}</p> : !fetchError && slate ? matchDays.map(day => <section key={day.key} className="mb-6" data-predict-day={day.key}>
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">{dayLabel(day.startTime)}</h2>
        {day.matches.map(match => {
        const existing = myPicks.find(pick => pick.matchKey === match.matchKey)
        const locked = match.live || match.finished || match.startTime === null || match.startTime <= Date.now()
        return <div key={match.matchKey} className="mb-3 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          <div className="mb-3 flex items-center justify-between"><div className="text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">{match.live ? <span className="text-[#ff3d71]">LIVE</span> : timeLabel(match.startTime)}{allEsports && <span className="ml-2 text-zinc-400">{match.title}</span>}</div><a href={isEsports ? '/esports' : '/scores'} className="shrink-0 text-[11px] font-medium uppercase tracking-wider text-zinc-500 hover:text-zinc-200">{isEsports ? 'Watch' : 'Scores'} ↗</a></div>
          <div className="flex items-center justify-between gap-3"><TeamLine name={match.teamA} logo={match.logoA} seed={match.seedA} /><span className="text-xs text-zinc-600">vs</span><TeamLine name={match.teamB} logo={match.logoB} seed={match.seedB} /></div>
          <div className="mt-3">{existing ? <><div className="text-sm"><span className="text-zinc-500">You picked </span><span className="font-semibold text-zinc-50">{existing.side === 'D' ? 'Draw' : existing.side === 'A' ? match.teamA : match.teamB}</span></div><CrowdReveal match={match} crowd={crowd[match.matchKey]} /></> : locked ? <p className="text-sm text-zinc-500">{match.live ? 'Picks closed — game in progress.' : 'Picks closed.'}</p> : <div className={`grid gap-3 ${match.allowDraw ? 'grid-cols-3' : 'grid-cols-2'}`}><PickButton disabled={submittingKey === match.matchKey} onClick={() => makePick(match, 'A')}>Pick {match.teamA}</PickButton>{match.allowDraw && <PickButton disabled={submittingKey === match.matchKey} onClick={() => makePick(match, 'D')}>Pick Draw</PickButton>}<PickButton disabled={submittingKey === match.matchKey} onClick={() => makePick(match, 'B')}>Pick {match.teamB}</PickButton></div>}</div>
        </div>
      })}</section>) : null}
      <div className="mt-8 mb-3 text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">History</div>
      {settled.length === 0 ? <p className="text-sm text-zinc-500">No history yet.</p> : settled.map(pick => { const names = pickTeams(pick); return <div key={`${pick.league || sport}:${pick.matchKey}`} className="flex items-center justify-between border-b border-zinc-800/60 py-2 text-sm"><span className="text-zinc-300">{pick.side === 'D' ? 'Draw' : pick.side === 'A' ? names.teamA : names.teamB}<span className="text-zinc-600"> · {isEsports ? names.title : leagueNavigationLabel(pick.league || '')}</span></span><span>{pick.result === 'win' && <span className="font-mono text-[#22c55e]">Won +{(pick.points ?? 0).toFixed(1)}</span>}{pick.result === 'loss' && <span className="font-mono text-[#ff3d71]">Lost</span>}{pick.result === 'void' && <span className="font-mono text-zinc-500">Void</span>}</span></div> })}
    </div>
  </>
}

function pickTeams(pick: MyPick) { const parts = pick.matchKey.split('||'); return { teamA: pick.teamA || parts[0] || 'Side A', teamB: pick.teamB || parts[1] || 'Side B', title: parts[2] || pick.league || '' } }
function PredictionSportPills({ groups, selectedGroup, selectedLeague, onSelectGroup, onSelectCompetition }: {
  groups: SportGroup[]
  selectedGroup: SportGroup
  selectedLeague?: string
  onSelectGroup: (group: SportGroup) => void
  onSelectCompetition: (group: SportGroup, league?: string) => void
}) {
  const [openGroup, setOpenGroup] = useState<string | null>(null)
  const navRef = useRef<HTMLElement>(null)

  useEffect(() => {
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (navRef.current && !navRef.current.contains(event.target as Node)) setOpenGroup(null)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpenGroup(null)
    }
    document.addEventListener('mousedown', closeOnOutsideClick)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('mousedown', closeOnOutsideClick)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [])

  const selectGroup = (group: SportGroup) => {
    if (selectedGroup.key !== group.key) {
      onSelectGroup(group)
      setOpenGroup(null)
      return
    }
    if (group.competitions.length > 1) {
      setOpenGroup(current => current === group.key ? null : group.key)
    }
  }

  return <nav ref={navRef} aria-label="Prediction sports" className="mt-6 flex max-w-full flex-wrap gap-1.5">
    {groups.map(group => {
      const active = selectedGroup.key === group.key
      const hasMenu = group.competitions.length > 1
      const menuOpen = openGroup === group.key
      const buttonLabel = active && selectedLeague ? leagueNavigationLabel(selectedLeague) : group.label
      return <div key={group.key} className="relative">
        <button
          type="button"
          onClick={() => selectGroup(group)}
          aria-label={buttonLabel}
          aria-pressed={active}
          aria-haspopup={hasMenu ? 'menu' : undefined}
          aria-expanded={hasMenu ? menuOpen : undefined}
          className={`flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors ${active ? 'bg-emerald-600 text-white' : 'border border-zinc-800 bg-zinc-900 text-zinc-400 hover:text-zinc-200'}`}
        >
          <span>{buttonLabel}</span>
          {hasMenu && active && <span aria-hidden="true" className="text-[10px]">▼</span>}
        </button>
        {hasMenu && menuOpen && <div role="menu" aria-label={`${group.label} filters`} className="absolute right-0 top-full z-50 mt-2 min-w-[170px] overflow-hidden rounded-xl border border-zinc-700 bg-zinc-900 p-1.5 shadow-2xl shadow-black/50">
          {[undefined, ...group.competitions.map(item => item.league)].map(league => {
            const selected = league ? selectedLeague === league : !selectedLeague
            return <button
              key={league || 'all'}
              type="button"
              role="menuitemradio"
              aria-checked={selected}
              onClick={() => { onSelectCompetition(group, league); setOpenGroup(null) }}
              className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition-colors ${selected ? 'bg-emerald-500/10 text-emerald-300' : 'text-zinc-300 hover:bg-zinc-800'}`}
            >
              <span>{league ? leagueNavigationLabel(league) : `All ${group.label}`}</span>
              {selected && <span aria-hidden="true" className="text-emerald-400">✓</span>}
            </button>
          })}
        </div>}
      </div>
    })}
  </nav>
}
function FilterPill({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) { return <button type="button" onClick={onClick} className={`shrink-0 rounded-full border px-3 py-1.5 text-[12px] font-medium transition-colors ${active ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300' : 'border-zinc-800 bg-zinc-900/60 text-zinc-500 hover:text-zinc-300'}`}>{children}</button> }
function PickButton({ disabled, onClick, children }: { disabled: boolean; onClick: () => void; children: React.ReactNode }) { return <button disabled={disabled} onClick={onClick} className="rounded-lg border border-zinc-700 bg-zinc-800/60 px-3 py-2 text-sm font-semibold text-zinc-200 hover:border-zinc-500 hover:text-zinc-50 disabled:cursor-not-allowed disabled:opacity-50">{children}</button> }
function TeamLine({ name, logo, seed }: { name: string; logo: string | null; seed?: number | null }) { return <div className="flex min-w-0 items-center gap-2">{logo && <img src={logo} alt="" className="h-6 w-6 rounded-sm object-contain" />}<span className="truncate text-sm font-semibold text-zinc-100">{seed ? `(${seed}) ` : ''}{name}</span></div> }
function MatchSkeleton() { return <div className="space-y-3" role="status" aria-label="Loading matches">{Array.from({ length: 4 }).map((_, index) => <div key={index} className="animate-pulse rounded-xl border border-zinc-800 bg-zinc-900 p-4" style={{ opacity: 1 - index * 0.18 }}><div className="flex items-center justify-between gap-4"><div className="flex-1 space-y-2"><div className="h-3.5 w-1/3 rounded bg-zinc-800" /><div className="h-3 w-1/2 rounded bg-zinc-800/70" /></div><div className="h-8 w-24 rounded-lg bg-zinc-800" /></div></div>)}</div> }
function CrowdReveal({ match, crowd }: { match: Match; crowd?: CrowdT }) {
  if (!crowd) return null
  if (crowd.total < 5) return <div className="mt-3 text-[11px] text-zinc-600">Be the first to pick this one.</div>
  const outcomes = [{ name: match.teamA, count: crowd.countA }, ...(match.allowDraw ? [{ name: 'Draw', count: crowd.countDraw || 0 }] : []), { name: match.teamB, count: crowd.countB }]
  const favorite = outcomes.reduce((best, item) => item.count > best.count ? item : best)
  const pct = Math.round((favorite.count / crowd.total) * 100)
  return <div className="mt-3"><div className="mb-1 flex items-center justify-between text-[11px] text-zinc-500"><span>Fans favor <span className="text-zinc-300">{favorite.name}</span></span><span className="font-mono tabular-nums">{pct}%</span></div><div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-800"><div className="h-full bg-zinc-400" style={{ width: `${pct}%` }} /></div></div>
}
