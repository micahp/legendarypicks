import { useState, useEffect, useRef } from 'react'
import Head from 'next/head'

/* ---------------- types ---------------- */
type Player = { name: string; rating: number | null; clock: number | null }


type LivePlayer = { name: string; role: string; champ: string | null; champImg: string | null; kills: number | null; deaths: number | null; assists: number | null; cs: number | null; gold: number | null; level: number | null }
type LiveTeam = { name: string; code: string; image: string | null; rank: number | null; winPct: number; marketPct: number | null; edge: number | null; wins: number | null; gold: number | null; kills: number | null; towers: number | null; dragons: number | null; barons: number | null; players?: LivePlayer[] }
type LiveMatch = {
  live: boolean
  gameNumber?: number
  bestOf?: number
  winsNeeded?: number
  games?: { number: number; state: string }[]
  gameState?: string | null
  youtube?: string | null
  twitch?: string | null
  teamA?: LiveTeam
  teamB?: LiveTeam
  goldLead?: { code: string; amount: number } | null
}

type CS2Player = { name: string; kills: number | null; deaths: number | null }
type CS2Team = { name: string; score: number | null; won: boolean; players: CS2Player[] }
type CS2Live = { live: boolean; title?: string; tournament?: string; stream?: { platform: string; channel: string } | null; teamA?: CS2Team; teamB?: CS2Team }

type UpMatch = { startTime: number | null; live: boolean; title: string; league: string; teamA: string; teamB: string; favorite: { name: string; pct: number } | null; watch: { platform: string; url: string; channel: string | null; online?: boolean | null } | null; score?: { a: number | null; b: number | null } | null; finished?: boolean | null; winner?: 'a' | 'b' | null; pinned?: boolean; model?: { favName: string; modelPct: number; marketPct: number | null; edge: number | null } | null; logoA?: string | null; logoB?: string | null }
type UpcomingData = { matches: UpMatch[]; source?: string; error?: string }

const POLL_MS = 10_000

/* ---------------- shared primitives ---------------- */
// One label system: tracked small-caps eyebrows, a red pulse when something is live.
function Eyebrow({ children, live = false }: { children: React.ReactNode; live?: boolean }) {
  return (
    <div className={`flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.2em] ${live ? 'text-red-400' : 'text-zinc-500'}`}>
      {live ? <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse motion-reduce:animate-none" /> : null}
      <span>{children}</span>
    </div>
  )
}

function SectionHeader({ eyebrow, title, meta, live = false }: { eyebrow: string; title: string; meta?: string; live?: boolean }) {
  return (
    <div className="space-y-2">
      <div className="flex items-end justify-between gap-3">
        <div className="space-y-1.5">
          <Eyebrow live={live}>{eyebrow}</Eyebrow>
          <h2 className="text-xl font-bold tracking-tight text-zinc-50">{title}</h2>
        </div>
        {meta ? <span className="shrink-0 pb-0.5 font-mono text-[10px] uppercase tracking-wider text-zinc-600">{meta}</span> : null}
      </div>
      <div className="h-px w-full bg-gradient-to-r from-zinc-700 to-transparent" />
    </div>
  )
}

function TeamCrest({ src, size = 'h-6 w-6' }: { src: string | null | undefined; size?: string }) {
  return src
    ? <img src={src} alt="" className={`${size} shrink-0 object-contain`} />
    : <span className={`${size} shrink-0 rounded bg-zinc-800`} />
}

function clock(s: number | null | undefined) {
  if (s === null || s === undefined) return '—'
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${String(r).padStart(2, '0')}`
}


/* ---------------- live MSI ---------------- */
function SeriesStrip({ m }: { m: LiveMatch }) {
  const a = m.teamA, b = m.teamB
  const aw = a?.wins ?? 0, bw = b?.wins ?? 0
  const games = m.games ?? []
  const pip = (state: string) =>
    state === 'completed' ? 'bg-zinc-300'
      : state === 'inProgress' ? 'bg-red-500 animate-pulse motion-reduce:animate-none ring-2 ring-red-500/30'
        : 'border border-zinc-700'
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 rounded-xl border border-zinc-800 bg-zinc-900/40 px-4 py-3">
      <div className="flex items-center gap-3">
        <TeamCrest src={a?.image} size="h-7 w-7" />
        <span className={`text-sm font-semibold ${aw > bw ? 'text-zinc-50' : 'text-zinc-400'}`}>{a?.code}</span>
        <span className="font-mono text-2xl font-bold tabular-nums text-zinc-100">{aw} <span className="text-zinc-600">–</span> {bw}</span>
        <span className={`text-sm font-semibold ${bw > aw ? 'text-zinc-50' : 'text-zinc-400'}`}>{b?.code}</span>
        <TeamCrest src={b?.image} size="h-7 w-7" />
      </div>
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2.5">
          {games.map((g) => (
            <div key={g.number} className="flex flex-col items-center gap-1">
              <span className={`h-3 w-3 rounded-full ${pip(g.state)}`} />
              <span className="font-mono text-[9px] text-zinc-600">G{g.number}</span>
            </div>
          ))}
        </div>
        <span className="text-[10px] font-medium uppercase tracking-wider text-zinc-500">First to {m.winsNeeded}</span>
      </div>
    </div>
  )
}

// Full roster — champion, role, live K/D/A and CS per player. The lane order (top→support)
// is the information: it's how the game is read, so we sort by it rather than by stats.
const ROLE_ORDER = ['top', 'jungle', 'mid', 'bottom', 'support']
function PlayerRoster({ team }: { team: LiveTeam }) {
  const ps = (team.players ?? []).slice().sort((p, q) => ROLE_ORDER.indexOf(p.role) - ROLE_ORDER.indexOf(q.role))
  if (!ps.length) return null
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
      <div className="mb-1 flex items-center gap-2 px-1 text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">
        <TeamCrest src={team.image} size="h-4 w-4" />{team.code}
      </div>
      <div className="divide-y divide-zinc-800/70">
        {ps.map((p, i) => (
          <div key={i} className="flex items-center gap-3 py-1.5">
            {p.champImg ? <img src={p.champImg} alt={p.champ ?? ''} className="h-8 w-8 rounded object-cover bg-zinc-800" /> : <span className="h-8 w-8 rounded bg-zinc-800" />}
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-zinc-100">{p.name}</div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-600">{p.role}{p.champ ? ` · ${p.champ}` : ''}</div>
            </div>
            <span className="font-mono text-sm tabular-nums text-zinc-200">{p.kills ?? 0}<span className="text-zinc-600">/</span>{p.deaths ?? 0}<span className="text-zinc-600">/</span>{p.assists ?? 0}</span>
            <span className="w-16 text-right font-mono text-xs tabular-nums text-zinc-500">{p.cs ?? 0} cs</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function LiveStatTeam({ t, lead }: { t: LiveTeam; lead: boolean }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <TeamCrest src={t.image} />
          <span className={`truncate text-sm font-semibold ${lead ? 'text-zinc-50' : 'text-zinc-300'}`}>{t.name}</span>
        </div>
        <span className="font-mono text-lg font-bold tabular-nums text-zinc-100">{t.kills ?? 0}</span>
      </div>
      <div className="flex items-center justify-between font-mono text-[11px] tabular-nums text-zinc-500">
        <span>{t.gold !== null ? `${(t.gold / 1000).toFixed(1)}k gold` : '—'}</span>
        <span>🏰 {t.towers ?? 0} · 🐉 {t.dragons ?? 0}{t.barons ? ` · 👑 ${t.barons}` : ''}</span>
      </div>
    </div>
  )
}

function LiveMSI({ m }: { m: LiveMatch }) {
  const a = m.teamA, b = m.teamB
  const hasState = a?.gold != null && b?.gold != null
  const ga = a?.gold ?? 0, gb = b?.gold ?? 0
  const aShare = (ga / (ga + gb || 1)) * 100
  const aLead = ga >= gb
  // Twitch embeds reliably (official streams often block YouTube embedding); parent must match the
  // page host, so read it at runtime — works on the tunnel, localhost, and prod alike.
  const [host, setHost] = useState('')
  const [source, setSource] = useState<'youtube' | 'twitch'>('youtube')
  useEffect(() => { setHost(window.location.hostname) }, [])
  const ytEmbed = m.youtube ? `https://www.youtube.com/embed/${m.youtube}?autoplay=1&mute=1` : null
  const twEmbed = (m.twitch && host) ? `https://player.twitch.tv/?channel=${m.twitch}&parent=${host}&muted=true` : null
  // YouTube is the primary stream; Twitch is the fallback (auto when there's no YouTube, or one tap if YT blocks embedding).
  const useTwitch = source === 'twitch' || !ytEmbed
  const embed = useTwitch ? twEmbed : ytEmbed

  return (
    <section className="space-y-4">
      <SectionHeader live eyebrow={`Live now · MSI 2026 · Game ${m.gameNumber} · Bo${m.bestOf}`} title={`${a?.name ?? ''} vs ${b?.name ?? ''}`} />
      <SeriesStrip m={m} />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-2">
          <div className="overflow-hidden rounded-xl border border-zinc-800 bg-black">
            {embed ? (
              <iframe key={embed} src={embed} title="MSI live broadcast" className="aspect-video w-full"
                      allow="autoplay; fullscreen; encrypted-media" allowFullScreen style={{ border: 'none' }} />
            ) : (
              <div className="flex aspect-video items-center justify-center text-sm text-zinc-500">Connecting to the broadcast…</div>
            )}
          </div>
          {ytEmbed && twEmbed ? (
            <div className="flex items-center gap-2 px-1 font-mono text-[10px] uppercase tracking-wider text-zinc-600">
              <span>stream</span>
              <button onClick={() => setSource('youtube')} className={!useTwitch ? 'text-emerald-400' : 'hover:text-zinc-300'}>youtube</button>
              <span className="text-zinc-700">·</span>
              <button onClick={() => setSource('twitch')} className={useTwitch ? 'text-emerald-400' : 'hover:text-zinc-300'}>twitch</button>
              <span className="ml-auto text-zinc-700 normal-case tracking-normal">won't play? switch to twitch</span>
            </div>
          ) : null}
        </div>

        <aside className="space-y-3">
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
            <div className="flex items-center justify-between text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">
              <span>Live game state</span><span className="font-mono">lolesports</span>
            </div>
            {hasState ? (
              <div className="mt-3">
                <LiveStatTeam t={a!} lead={aLead} />
                <div className="my-3 flex h-2 w-full overflow-hidden rounded-full bg-zinc-800">
                  <div className="bg-emerald-500 transition-[width] duration-700 ease-out motion-reduce:transition-none" style={{ width: `${aShare}%` }} />
                  <div className="bg-amber-500 transition-[width] duration-700 ease-out motion-reduce:transition-none" style={{ width: `${100 - aShare}%` }} />
                </div>
                <LiveStatTeam t={b!} lead={!aLead} />
              </div>
            ) : (
              <p className="mt-4 text-sm text-zinc-500">Game {m.gameNumber} — draft underway. Live stats start at first blood.</p>
            )}
          </div>

          {m.goldLead && m.goldLead.amount > 500 ? (
            <div className="rounded-xl border-l-2 border-emerald-500 bg-emerald-500/[0.07] p-4">
              <Eyebrow>Moment that matters</Eyebrow>
              <p className="mt-1.5 font-mono text-sm font-semibold text-emerald-200">{m.goldLead.code} +{m.goldLead.amount.toLocaleString()} gold</p>
            </div>
          ) : null}

          <div className="flex gap-4 font-mono text-xs text-zinc-500">
            {m.twitch ? <a className="hover:text-emerald-400 focus-visible:text-emerald-400 focus-visible:outline-none" href={`https://twitch.tv/${m.twitch}`} target="_blank" rel="noreferrer">twitch ↗</a> : null}
            {m.youtube ? <a className="hover:text-emerald-400 focus-visible:text-emerald-400 focus-visible:outline-none" href={`https://youtube.com/watch?v=${m.youtube}`} target="_blank" rel="noreferrer">youtube ↗</a> : null}
          </div>
        </aside>
      </div>

      {(a?.players?.length || b?.players?.length) ? (
        <div className="grid gap-4 md:grid-cols-2">
          <PlayerRoster team={a!} />
          <PlayerRoster team={b!} />
        </div>
      ) : null}
    </section>
  )
}

/* ---------------- CS2 (GRID official, data-only) ---------------- */
function CS2Roster({ team, lead }: { team?: CS2Team; lead: boolean }) {
  const ps = team?.players ?? []
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
      <div className="mb-1 flex items-center justify-between px-1">
        <span className={`text-sm font-semibold ${lead ? 'text-zinc-50' : 'text-zinc-300'}`}>{team?.name ?? '—'}</span>
        <span className="font-mono text-lg font-bold tabular-nums text-zinc-100">{team?.score ?? 0}</span>
      </div>
      <div className="divide-y divide-zinc-800/70">
        {ps.map((p, i) => {
          const diff = (p.kills ?? 0) - (p.deaths ?? 0)
          return (
            <div key={i} className="flex items-center justify-between gap-3 py-1.5">
              <span className="truncate text-sm font-medium text-zinc-100">{p.name}</span>
              <div className="flex items-center gap-3 font-mono text-sm tabular-nums">
                <span className="text-zinc-300">{p.kills ?? 0}<span className="text-zinc-600">–</span>{p.deaths ?? 0}</span>
                <span className={`w-8 text-right ${diff > 0 ? 'text-emerald-400' : diff < 0 ? 'text-red-400' : 'text-zinc-500'}`}>{diff > 0 ? '+' : ''}{diff}</span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function LiveGrid({ m }: { m: CS2Live }) {
  const a = m.teamA, b = m.teamB
  const aLead = (a?.score ?? 0) >= (b?.score ?? 0)
  const [host, setHost] = useState('')
  useEffect(() => { setHost(window.location.hostname) }, [])
  const s = m.stream
  const embed = !s ? null
    : s.platform === 'kick' ? `https://player.kick.com/${s.channel}?autoplay=true&muted=false`
    : s.platform === 'twitch' && host ? `https://player.twitch.tv/?channel=${s.channel}&parent=${host}&muted=false`
    : null
  return (
    <section className="space-y-4">
      <SectionHeader live eyebrow={`Live now · ${m.title ?? 'Esports'}${m.tournament ? ' · ' + m.tournament : ''}`} title={`${a?.name ?? ''} vs ${b?.name ?? ''}`} meta="grid · official" />
      {embed ? (
        <div className="overflow-hidden rounded-xl border border-zinc-800 bg-black">
          <iframe src={embed} title="Live broadcast" className="aspect-video w-full"
                  allow="autoplay; fullscreen" allowFullScreen style={{ border: 'none' }} />
        </div>
      ) : null}
      <div className="flex items-center justify-center gap-5 rounded-xl border border-zinc-800 bg-zinc-900/40 py-3">
        <span className={`text-sm font-semibold ${aLead ? 'text-zinc-50' : 'text-zinc-400'}`}>{a?.name}</span>
        <span className="font-mono text-2xl font-bold tabular-nums text-zinc-100">{a?.score ?? 0} <span className="text-zinc-600">–</span> {b?.score ?? 0}</span>
        <span className={`text-sm font-semibold ${!aLead ? 'text-zinc-50' : 'text-zinc-400'}`}>{b?.name}</span>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <CS2Roster team={a} lead={aLead} />
        <CS2Roster team={b} lead={!aLead} />
      </div>
    </section>
  )
}

/* ---------------- page ---------------- */
/* ---------------- upcoming slate (the rest of the off-board esports, chronological) ---------------- */
function dayKey(ms: number | null) {
  if (!ms) return ''
  const d = new Date(ms)
  const today = new Date()
  const tom = new Date(today); tom.setDate(today.getDate() + 1)
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString()
  if (same(d, today)) return 'Today'
  if (same(d, tom)) return 'Tomorrow'
  return d.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
}

function fmtClock(ms: number | null) {
  if (!ms) return ''
  try { return new Date(ms).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }) }
  catch { return '' }
}

function watchLabel(platform: string) {
  return platform === 'twitch' ? 'twitch' : platform === 'kick' ? 'kick'
    : platform === 'youtube' ? 'youtube' : 'watch'
}

function UpMatchRow({ m, host }: { m: UpMatch; host: string }) {
  const [open, setOpen] = useState(false)
  const iframeRef = useRef<HTMLIFrameElement>(null)
  // Only embed a LIVE match whose channel we've confirmed is on-air — never a dead player.
  const embeddable = m.live && m.watch?.online === true && !!m.watch?.channel && (m.watch.platform === 'twitch' || m.watch.platform === 'kick')

  const toggle = () => {
    const next = !open
    setOpen(next)
    const iframe = iframeRef.current
    if (!iframe) return
    if (next && m.watch?.channel) {
      const { platform, channel } = m.watch
      iframe.src = platform === 'kick'
        ? `https://player.kick.com/${channel}?muted=false`
        : `https://player.twitch.tv/?channel=${channel}&parent=${encodeURIComponent(host)}&muted=false`
    } else {
      iframe.src = ''
    }
  }

  return (
    <div className="py-2.5">
      <div className="flex items-center gap-3">
        <div className="w-16 shrink-0 font-mono text-[11px] tabular-nums">
          {m.live
            ? <span className="inline-flex items-center gap-1 text-red-400"><span className="h-1 w-1 rounded-full bg-red-500 animate-pulse motion-reduce:animate-none" />LIVE</span>
            : <span className="text-zinc-500">{fmtClock(m.startTime)}</span>}
        </div>
        {/* Map score — GRID-sourced, shown for live+finished CS2/Dota matches */}
        {m.score ? (
          <div className="shrink-0 w-10 text-center font-mono text-sm font-bold tabular-nums text-zinc-300">
            {m.score.a ?? '–'}<span className="text-zinc-600">–</span>{m.score.b ?? '–'}
          </div>
        ) : null}
        <div className="min-w-0 flex-1">
          <div className="text-sm text-zinc-200 leading-snug">
            <div className={`flex items-center gap-1.5 font-medium ${m.finished ? (m.winner === 'a' ? 'text-zinc-200' : 'text-zinc-500') : ''}`}>
              {m.logoA ? <TeamCrest src={m.logoA} size="h-4 w-4" /> : null}
              {m.teamA}
            </div>
            <div className="text-zinc-600 text-[11px]">v</div>
            <div className={`flex items-center gap-1.5 font-medium ${m.finished ? (m.winner === 'b' ? 'text-zinc-200' : 'text-zinc-500') : ''}`}>
              {m.logoB ? <TeamCrest src={m.logoB} size="h-4 w-4" /> : null}
              {m.teamB}
            </div>
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-600">
            <span>{m.finished ? 'Final' : ''}{m.finished && m.title ? ' — ' : ''}{m.title} · {m.league}</span>
            {m.model ? (
              <span className={`shrink-0 rounded px-1.5 py-px text-[10px] font-medium ${(m.model.edge && Math.abs(m.model.edge) >= 4) ? 'bg-amber-500/10 text-amber-300' : 'text-zinc-500'}`}>
                {(m.model.edge && Math.abs(m.model.edge) >= 4) ? `EDGE ${m.model.favName} +${Math.abs(m.model.edge).toFixed(0)}` : 'model ≈ market'}
              </span>
            ) : null}
            {embeddable ? (
              <>
                <span className="text-zinc-700">·</span>
                <button onClick={toggle}
                        className="shrink-0 text-emerald-400 hover:text-emerald-300 focus-visible:outline-none">
                  {open ? 'hide ▴' : 'watch here ▾'}
                </button>
              </>
            ) : m.live && m.watch && m.watch.online === false ? (
              <>
                <span className="text-zinc-700">·</span>
                <span className="shrink-0 text-zinc-600">stream offline</span>
              </>
            ) : m.watch ? (
              <>
                <span className="text-zinc-700">·</span>
                <a href={m.watch.url} target="_blank" rel="noreferrer"
                   className="shrink-0 text-zinc-500 hover:text-emerald-400 focus-visible:text-emerald-400 focus-visible:outline-none">
                  {watchLabel(m.watch.platform)} ↗
                </a>
              </>
            ) : null}
          </div>
        </div>
        {m.favorite ? (
          <div className="shrink-0 text-right leading-none">
            <div className="max-w-[7rem] truncate text-[11px] font-medium text-zinc-400">{m.favorite.name}</div>
            <div className="mt-1 font-mono text-xs tabular-nums text-emerald-300">{m.favorite.pct}%</div>
          </div>
        ) : null}
      </div>
      {embeddable ? (
        <div className={`mt-2 ${open ? '' : 'hidden'}`}>
          <div className="aspect-video w-full overflow-hidden rounded-lg border border-zinc-800 bg-black">
            <iframe ref={iframeRef} title="Live broadcast" allow="autoplay; fullscreen" allowFullScreen
                    className="h-full w-full" style={{ border: 'none' }} />
          </div>
          {open ? <p className="mt-1 text-[10px] text-zinc-600">Tap player for sound</p> : null}
        </div>
      ) : null}
    </div>
  )
}

function UpcomingSlate({ data }: { data: UpcomingData | null }) {
  const [host, setHost] = useState('')
  const [tab, setTab] = useState<'scheduled' | 'results'>('scheduled')
  useEffect(() => { setHost(window.location.hostname) }, [])
  const matches = data?.matches ?? []

  // Split: finished → Results (most-recent first); everything else → Scheduled
  const rs = matches.filter((m) => m.finished).sort((a, b) => (b.startTime || 0) - (a.startTime || 0))
  const sc = matches.filter((m) => !m.finished)
  // Group scheduled consecutively by day (the list is time-ordered: live first, then soonest).
  const days: { label: string; matches: UpMatch[] }[] = []
  for (const m of sc) {
    const label = dayKey(m.startTime)
    const last = days[days.length - 1]
    if (last && last.label === label && !m.live) last.matches.push(m)
    else if (m.live && last && last.label === 'Live now') last.matches.push(m)
    else days.push({ label: m.live ? 'Live now' : label, matches: [m] })
  }

  const show = tab === 'results' ? rs : sc

  return (
    <section className="space-y-5">
      <SectionHeader eyebrow="Across esports" title="What's next" meta="bovada line" />
      {data?.error ? (
        <p className="text-sm text-zinc-500">Schedule unavailable right now — retrying.</p>
      ) : data === null ? (
        <div className="h-48 animate-pulse rounded-xl border border-zinc-800 bg-zinc-900/40 motion-reduce:animate-none" />
      ) : matches.length === 0 ? (
        <p className="text-sm text-zinc-500">No upcoming esports matches on the board right now.</p>
      ) : (
        <>
          {/* Tab bar */}
          <div className="flex gap-1 rounded-lg bg-zinc-900/60 p-1 w-fit">
            {([
              ['scheduled', 'Scheduled', sc.length],
              ['results', 'Results', rs.length],
            ] as const).map(([key, label, count]) => (
              <button key={key} onClick={() => setTab(key)}
                      className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                        tab === key
                          ? 'bg-zinc-800 text-zinc-100'
                          : 'text-zinc-500 hover:text-zinc-300'
                      }`}>
                {label}{' '}<span className="tabular-nums">{count}</span>
              </button>
            ))}
          </div>

          {/* Content */}
          {tab === 'scheduled' ? (
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 sm:p-5">
              {days.length === 0 ? (
                <p className="text-sm text-zinc-500">No scheduled matches right now.</p>
              ) : (
                <div className="space-y-5">
                  {days.map((d, di) => (
                    <div key={di}>
                      <Eyebrow live={d.label === 'Live now'}>{d.label}</Eyebrow>
                      <div className="mt-1 divide-y divide-zinc-800/70">
                        {d.matches.map((m, i) => <UpMatchRow key={i} m={m} host={host} />)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 sm:p-5">
              {rs.length === 0 ? (
                <p className="text-sm text-zinc-500">No finished matches yet.</p>
              ) : (
                <div className="divide-y divide-zinc-800/70">
                  {rs.map((m, i) => <UpMatchRow key={i} m={m} host={host} />)}
                </div>
              )}
            </div>
          )}
        </>
      )}
      <p className="max-w-2xl text-xs text-zinc-600">
        Every off-board esports match on the board (LoL, Valorant, CS2, Dota, Rainbow Six, King of Glory),
        soonest first, priced by the Bovada favorite. Full schedules + standings move to the Leagues hub next.
      </p>
    </section>
  )
}

/* ---------------- featured upcoming live (hero fallback) ---------------- */

function FeaturedUpcoming({ m, host }: { m: UpMatch; host: string }) {
  const src = m.watch?.channel
    ? m.watch.platform === 'kick'
      ? `https://player.kick.com/${m.watch.channel}?muted=false`
      : m.watch.platform === 'twitch'
      ? `https://player.twitch.tv/?channel=${m.watch.channel}&parent=${encodeURIComponent(host)}&muted=false`
      : null
    : null

  return (
    <section className="space-y-4">
      <SectionHeader live eyebrow="Live now · Featured" title={`${m.title} · ${m.league}`} meta={m.watch?.platform ?? 'watch'} />
      <div className="overflow-hidden rounded-xl border border-zinc-800 bg-ink-900">
        <div className="p-4 flex items-center justify-between gap-4">
          <div className="min-w-0">
            <div className={`text-lg font-bold ${m.finished ? (m.winner === 'a' ? 'text-zinc-100' : 'text-zinc-500') : 'text-zinc-100'}`}>{m.teamA}</div>
            <div className="text-xs text-zinc-500 mt-0.5">vs</div>
            <div className={`text-lg font-bold ${m.finished ? (m.winner === 'b' ? 'text-zinc-100' : 'text-zinc-500') : 'text-zinc-100'}`}>{m.teamB}</div>
          </div>
          {m.score ? (
            <div className="shrink-0 text-center">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500">{m.finished ? 'Final' : 'Map score'}</div>
              <div className="font-mono text-2xl font-bold tabular-nums text-zinc-100">{m.score.a ?? '–'}<span className="text-zinc-600">{'–'}</span>{m.score.b ?? '–'}</div>
            </div>
          ) : m.favorite ? (
            <div className="shrink-0 text-right">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500">Favorite</div>
              <div className="text-sm font-semibold text-zinc-300">{m.favorite.name}</div>
              <div className="font-mono text-xl font-bold tabular-nums text-emerald-300">{m.favorite.pct}%</div>
            </div>
          ) : null}
        </div>
        {src ? (
          <div>
            <div className="aspect-video w-full bg-black overflow-hidden rounded-b-xl">
              <iframe src={src} title="Live broadcast" allow="autoplay; fullscreen" allowFullScreen
                      className="h-full w-full" style={{ border: 'none' }} />
            </div>
            <p className="px-4 pb-3 pt-1.5 text-[10px] text-zinc-600">Tap player for sound</p>
          </div>
        ) : (
          <div className="aspect-video w-full bg-black" />
        )}
      </div>
    </section>
  )
}

export default function EsportsPage() {
  const [live, setLive] = useState<LiveMatch | null>(null)
  const [upcoming, setUpcoming] = useState<UpcomingData | null>(null)
  const [host, setHost] = useState('')
  const timers = useRef<ReturnType<typeof setInterval>[]>([])

  useEffect(() => { setHost(window.location.hostname) }, [])

  useEffect(() => {
    let alive = true
    const j = (url: string, set: (d: any) => void) => async () => {
      try { const r = await fetch(url, { cache: 'no-store' }); const d = await r.json(); if (alive) set(d) } catch {}
    }
    const loadLive = j('/api/esports/lol/msi/live', setLive)
    const loadUpcoming = j('/api/esports/upcoming', setUpcoming)
    loadLive(); loadUpcoming()
    timers.current = [setInterval(loadLive, 15_000), setInterval(loadUpcoming, POLL_MS)]
    return () => { alive = false; timers.current.forEach(clearInterval) }
  }, [])

  // Hero features a live match whose stream we've CONFIRMED is on-air — never a dead embed.
  const upcomingLive = (upcoming?.matches ?? []).find((m) => m.live && m.watch?.online === true) ?? null
  const anyLive = !!live?.live || !!upcomingLive

  // Featured hero: one source of truth. MSI live > slate live (CS2/Dota/etc., GRID-verified with
  // the correct stream). The old /grid/live path was a second match-picker on a freshness gate that
  // toggled on/off and fought the slate — causing the hero to flip between two different matches /
  // streams. The slate already carries live CS2/Dota with score + the right channel, so use only it.
  let hero: React.ReactNode = null
  if (live?.live) {
    hero = <LiveMSI m={live} />
  } else if (upcomingLive) {
    hero = <FeaturedUpcoming m={upcomingLive} host={host} />
  }

  return (
    <>
      <Head><title>Esports — Legendary Picks</title></Head>

      <div className="space-y-10">
        <header className="space-y-2">
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-extrabold tracking-tight text-zinc-50">Esports</h1>
            {anyLive ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-red-400">
                <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse motion-reduce:animate-none" /> Live
              </span>
            ) : null}
          </div>
          <p className="text-sm text-zinc-400">Who wins — and the moment it turns.</p>
        </header>

        {/* Feature exactly one live match — MSI > CS2/Dota (GRID official) > upcoming slate */}
        {hero}

        <UpcomingSlate data={upcoming} />
      </div>
    </>
  )
}
