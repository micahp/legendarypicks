import { useCallback, useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/router'
import Head from 'next/head'
import { getDeviceId } from '../lib/deviceId'
import { trackPickMade } from '../lib/analytics'

type Side = 'A' | 'B' | 'D'
interface Match { matchKey: string; teamA: string; teamB: string; title: string; league: string; startTime: number | null; logoA: string | null; logoB: string | null; seedA?: number | null; seedB?: number | null; live: boolean; finished: boolean; allowDraw?: boolean; favorite?: { name: string; pct: number } | null }
interface TitleOption { slug: string; label: string; match_count: number; live_count: number; result_count: number; next_start: number | null }
interface PredictSlate { schema_version: string; selected_title: { slug: string; label: string }; titles: TitleOption[]; matches: Match[]; match_count: number; has_more: boolean; building: boolean; error: string | null; source: string | null }
interface MyPick { matchKey: string; side: Side; teamA?: string; teamB?: string; league?: string; createdAt: number; lockAt: number | null; settledAt: number | null; result: 'win' | 'loss' | 'void' | null; points: number | null }
interface RecordT { wins: number; losses: number; voids: number; streak: number }
interface CrowdT { countA: number; countB: number; countDraw?: number; total: number; shareA: number | null }

const EMPTY_RECORD: RecordT = { wins: 0, losses: 0, voids: 0, streak: 0 }
const SPORTS = [
  ['esports', 'Esports'], ['mlb', 'MLB'], ['nba', 'NBA'], ['wnba', 'WNBA'], ['nhl', 'NHL'],
  ['nfl', 'NFL'], ['ncaaf', 'NCAAF'], ['mls', 'MLS'], ['lcup', 'Leagues Cup'],
  ['wc', 'World Cup'], ['atp', 'ATP'], ['wta', 'WTA'], ['ufc', 'UFC'],
] as const

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
  const sport = SPORTS.some(([slug]) => slug === requestedSport) ? requestedSport : 'esports'
  const urlTitle = typeof router.query.title === 'string' ? router.query.title : undefined
  const isEsports = sport === 'esports'
  const isUfc = sport === 'ufc'
  const sportLabel = SPORTS.find(([slug]) => slug === sport)?.[1] || sport.toUpperCase()
  const [slate, setSlate] = useState<PredictSlate | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [reloadTick, setReloadTick] = useState(0)
  const [myPicks, setMyPicks] = useState<MyPick[]>([])
  const [apiRecord, setApiRecord] = useState<RecordT>(EMPTY_RECORD)
  const [submittingKey, setSubmittingKey] = useState<string | null>(null)
  const [crowd, setCrowd] = useState<Record<string, CrowdT>>({})

  const loadPicks = useCallback(async () => {
    const endpoint = isEsports ? '/api/esports/picks/me' : isUfc ? '/api/ufc/picks/me' : `/api/sports/picks/me?league=${encodeURIComponent(sport)}`
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
  }, [isEsports, isUfc, sport])

  useEffect(() => {
    if (!router.isReady) return
    let active = true
    ;(async () => {
      setLoading(true); setFetchError(null); setSlate(null); setCrowd({})
      try {
        const endpoint = isEsports ? `/api/esports/predict${urlTitle ? `?title=${encodeURIComponent(urlTitle)}` : ''}` : isUfc ? '/api/ufc/upcoming' : `/api/sports/predict?league=${encodeURIComponent(sport)}`
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
  }, [router.isReady, sport, isEsports, isUfc, urlTitle, reloadTick])

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
        const endpoint = isEsports ? `/api/esports/crowd?matchKey=${encodeURIComponent(key)}` : isUfc ? `/api/ufc/crowd?fightKey=${encodeURIComponent(key)}` : `/api/sports/crowd?league=${encodeURIComponent(sport)}&matchKey=${encodeURIComponent(key)}`
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
  }, [myPicks, crowd, isEsports, isUfc, sport])

  const makePick = async (match: Match, side: Side) => {
    setSubmittingKey(match.matchKey)
    try {
      const endpoint = isEsports ? '/api/esports/picks' : isUfc ? '/api/ufc/picks' : '/api/sports/picks'
      const body = isUfc ? { fightKey: match.matchKey, side: side === 'A' ? 'away' : 'home', method: null } : isEsports ? { matchKey: match.matchKey, side, lockAt: match.startTime } : { league: sport, matchKey: match.matchKey, side }
      const response = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Device-Id': getDeviceId() }, body: JSON.stringify(body) })
      if (response.ok) { trackPickMade({ league: sport, surface: 'predict', pick_id: match.matchKey }); await loadPicks() }
    } finally { setSubmittingKey(null) }
  }
  const selectSport = (slug: string) => router.push({ pathname: '/predict', query: slug === 'esports' && urlTitle ? { sport: slug, title: urlTitle } : { sport: slug } }, undefined, { shallow: true })
  const selectTitle = (slug: string) => router.push({ pathname: '/predict', query: { sport: 'esports', title: slug } }, undefined, { shallow: true })

  const selectedLabel = slate?.selected_title.label || sportLabel
  const record = useMemo(() => isEsports && slate ? recordForTitle(myPicks, slate.selected_title.label) : apiRecord, [isEsports, slate, myPicks, apiRecord])
  const settled = useMemo(() => myPicks.filter(p => p.settledAt !== null && (!isEsports || !slate || p.matchKey.split('||')[2] === slate.selected_title.label)).sort((a, b) => (b.settledAt || 0) - (a.settledAt || 0)), [myPicks, isEsports, slate])
  const hasRecord = record.wins + record.losses + record.voids > 0
  const selectedTitle = slate?.titles.find(title => title.slug === slate.selected_title.slug)

  return <>
    <Head><title>Predict — Legendary Picks</title><meta name="description" content="Pick winners across every sport and track your record." /></Head>
    <div className="mx-auto max-w-2xl px-4 py-6">
      <div className="flex items-center justify-between gap-3">
        <div><div className="flex items-center gap-2"><h1 className="text-3xl font-extrabold tracking-tight text-zinc-50">Predict</h1><span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-400">{sportLabel}</span></div><p className="mt-1 text-sm text-zinc-500">Pick winners across every sport. Track your record.</p></div>
        <div className="text-right">{!hasRecord ? <span className="text-sm text-zinc-500">Make your first pick</span> : <div className="flex items-center gap-2"><span className="font-mono text-lg font-bold tabular-nums text-zinc-100">{record.wins}–{record.losses}</span>{record.streak !== 0 && <span className="text-zinc-500">·</span>}{record.streak > 0 && <span className="font-mono text-lg font-bold text-[#22c55e]">W{record.streak}</span>}{record.streak < 0 && <span className="font-mono text-lg font-bold text-[#ff3d71]">L{-record.streak}</span>}</div>}</div>
      </div>
      <div className="mt-6 flex gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" aria-label="Prediction sports">{SPORTS.map(([slug, label]) => <FilterPill key={slug} active={sport === slug} onClick={() => selectSport(slug)}>{label}</FilterPill>)}</div>
      {isEsports && slate && slate.titles.length > 0 && <div className="mt-3 flex gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" aria-label="Esports titles">{slate.titles.map(title => <FilterPill key={title.slug} active={title.slug === slate.selected_title.slug} onClick={() => selectTitle(title.slug)}>{title.live_count > 0 && <span className="mr-1 text-emerald-400">●</span>}{title.label}{title.match_count > 0 && <span className="ml-1 opacity-60">{title.match_count}</span>}</FilterPill>)}</div>}
      {fetchError && <div className="mt-4 flex items-center justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300"><span>{fetchError}</span><button onClick={() => setReloadTick(t => t + 1)} className="shrink-0 font-medium text-red-200 hover:text-red-100">Retry</button></div>}
      {!fetchError && slate?.error && <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">{slate.error}</div>}
      <div className="mt-6 mb-3 text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">{selectedLabel} matches</div>
      {loading ? <MatchSkeleton /> : !fetchError && slate && slate.matches.length === 0 ? <p className="text-sm text-zinc-500">{slate.building ? `Still loading the latest ${selectedLabel} slate — check back in a moment.` : `No open ${selectedLabel} games in the stored slate right now.`}{selectedTitle?.next_start ? <> Next match {new Date(selectedTitle.next_start).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}.</> : null}</p> : !fetchError && slate ? slate.matches.map(match => {
        const existing = myPicks.find(pick => pick.matchKey === match.matchKey)
        return <div key={match.matchKey} className="mb-3 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          <div className="mb-3 flex items-center justify-between"><div className="flex items-center gap-2 text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">{match.title}{match.league && ` · ${match.league}`}{match.live && <span className="text-[#ff3d71]"> · live</span>}</div><a href={isEsports ? '/esports' : '/scores'} className="shrink-0 text-[11px] font-medium uppercase tracking-wider text-zinc-500 hover:text-zinc-200">{isEsports ? 'Watch' : 'Scores'} ↗</a></div>
          <div className="flex items-center justify-between gap-3"><TeamLine name={match.teamA} logo={match.logoA} seed={match.seedA} /><span className="text-xs text-zinc-600">vs</span><TeamLine name={match.teamB} logo={match.logoB} seed={match.seedB} /></div>
          <div className="mt-3">{existing ? <><div className="text-sm"><span className="text-zinc-500">You picked </span><span className="font-semibold text-zinc-50">{existing.side === 'D' ? 'Draw' : existing.side === 'A' ? match.teamA : match.teamB}</span></div><CrowdReveal match={match} crowd={crowd[match.matchKey]} /></> : <div className={`grid gap-3 ${match.allowDraw ? 'grid-cols-3' : 'grid-cols-2'}`}><PickButton disabled={submittingKey === match.matchKey} onClick={() => makePick(match, 'A')}>Pick {match.teamA}</PickButton>{match.allowDraw && <PickButton disabled={submittingKey === match.matchKey} onClick={() => makePick(match, 'D')}>Pick Draw</PickButton>}<PickButton disabled={submittingKey === match.matchKey} onClick={() => makePick(match, 'B')}>Pick {match.teamB}</PickButton></div>}</div>
        </div>
      }) : null}
      <div className="mt-8 mb-3 text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">History</div>
      {settled.length === 0 ? <p className="text-sm text-zinc-500">No history yet.</p> : settled.map(pick => { const names = pickTeams(pick); return <div key={`${pick.league || sport}:${pick.matchKey}`} className="flex items-center justify-between border-b border-zinc-800/60 py-2 text-sm"><span className="text-zinc-300">{pick.side === 'D' ? 'Draw' : pick.side === 'A' ? names.teamA : names.teamB}<span className="text-zinc-600"> · {isEsports ? names.title : sportLabel}</span></span><span>{pick.result === 'win' && <span className="font-mono text-[#22c55e]">Won +{(pick.points ?? 0).toFixed(1)}</span>}{pick.result === 'loss' && <span className="font-mono text-[#ff3d71]">Lost</span>}{pick.result === 'void' && <span className="font-mono text-zinc-500">Void</span>}</span></div> })}
    </div>
  </>
}

function pickTeams(pick: MyPick) { const parts = pick.matchKey.split('||'); return { teamA: pick.teamA || parts[0] || 'Side A', teamB: pick.teamB || parts[1] || 'Side B', title: parts[2] || pick.league || '' } }
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
