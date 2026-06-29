import { useState, useEffect, useRef } from 'react'
import Head from 'next/head'

/* ---------------- types ---------------- */
type Player = { name: string; rating: number | null; clock: number | null }
type ChessLive = {
  live: boolean
  url?: string
  white?: Player
  black?: Player
  clocks?: { white: number | null; black: number | null }
  winPct?: number | null
  winSwing?: number | null
  moment?: string | null
}

type Team = { name: string; code: string; image: string | null; rank: number | null; winPct: number; marketPct: number | null; edge: number | null; wins: number | null }
type Match = { startTime: string; state: string; bestOf: number; teamA: Team; teamB: Team; favorite: string; hasMarket?: boolean }
type MSIData = { event: string; model?: string; matches: Match[]; error?: string }

type LivePlayer = { name: string; role: string; champ: string | null; champImg: string | null; kills: number | null; deaths: number | null; assists: number | null; cs: number | null; gold: number | null; level: number | null }
type LiveTeam = Team & { gold: number | null; kills: number | null; towers: number | null; dragons: number | null; barons: number | null; players?: LivePlayer[] }
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

const POLL_MS = 10_000
const PRED_POLL_MS = 60_000

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

function fmtTime(iso: string) {
  try {
    return new Date(iso).toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' })
  } catch { return iso }
}

/* ---------------- pre-game prediction cards ---------------- */
function TeamLine({ t, fav }: { t: Team; fav: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex min-w-0 items-center gap-2">
        <TeamCrest src={t.image} />
        <span className={`truncate text-sm font-semibold ${fav ? 'text-zinc-50' : 'text-zinc-400'}`}>{t.name}</span>
        {t.rank ? <span className="font-mono text-[10px] text-zinc-600">#{t.rank}</span> : null}
      </div>
      <div className="text-right leading-none">
        <div className={`font-mono text-sm tabular-nums ${fav ? 'text-emerald-300' : 'text-zinc-400'}`}>{t.winPct.toFixed(0)}%</div>
        {t.marketPct !== null ? <div className="mt-1 font-mono text-[10px] tabular-nums text-zinc-600">mkt {t.marketPct.toFixed(0)}%</div> : null}
      </div>
    </div>
  )
}

function MatchCard({ m }: { m: Match }) {
  const a = m.teamA, b = m.teamB
  const aFav = m.favorite === a.code
  const done = m.state === 'completed'
  const live = m.state === 'inProgress'
  const correct = done && a.wins !== null && b.wins !== null ? (a.wins > b.wins) === aFav : null
  const valueTeam = (a.edge ?? -99) >= (b.edge ?? -99) ? a : b
  const valueEdge = Math.max(a.edge ?? -99, b.edge ?? -99)
  const showEdge = !!m.hasMarket && !done

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
      <div className="mb-2.5 flex items-center justify-between text-[10px] font-medium uppercase tracking-[0.18em]">
        {live ? (
          <span className="flex items-center gap-1.5 text-red-400">
            <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse motion-reduce:animate-none" /> live
          </span>
        ) : done ? <span className="text-zinc-500">final</span> : <span className="text-zinc-400">{fmtTime(m.startTime)}</span>}
        <span className="font-mono text-zinc-600">Bo{m.bestOf}</span>
      </div>

      <TeamLine t={a} fav={aFav} />
      <div className="my-2 flex h-2 w-full overflow-hidden rounded-full bg-zinc-800">
        <div className={aFav ? 'bg-emerald-500' : 'bg-zinc-600'} style={{ width: `${a.winPct}%` }} />
        <div className={aFav ? 'bg-zinc-600' : 'bg-emerald-500'} style={{ width: `${b.winPct}%` }} />
      </div>
      <TeamLine t={b} fav={!aFav} />

      {showEdge ? (
        valueEdge >= 4 ? (
          <div className="mt-2.5 flex items-center gap-2 border-t border-zinc-800 pt-2 text-xs">
            <span className="rounded bg-amber-400/15 px-1.5 py-0.5 font-mono font-semibold text-amber-300">EDGE {valueTeam.code} +{valueEdge.toFixed(0)}</span>
            <span className="font-mono tabular-nums text-zinc-500">model {valueTeam.winPct.toFixed(0)}% vs mkt {valueTeam.marketPct?.toFixed(0)}%</span>
          </div>
        ) : (
          <div className="mt-2.5 border-t border-zinc-800 pt-2 font-mono text-[11px] tabular-nums text-zinc-600">model ≈ market — no edge</div>
        )
      ) : null}

      {done ? (
        <div className="mt-2.5 flex items-center gap-2 border-t border-zinc-800 pt-2 text-xs">
          <span className="font-mono tabular-nums text-zinc-300">Final {a.wins}–{b.wins}</span>
          <span className={correct ? 'text-emerald-400' : 'text-red-400'}>{correct ? '✓ pick hit' : '✗ pick missed'}</span>
        </div>
      ) : null}
    </div>
  )
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

/* ---------------- chess (demoted "also live" test) ---------------- */
function WinBar({ white }: { white: number }) {
  return (
    <div className="relative h-3 w-full overflow-hidden rounded-sm bg-zinc-700/60 ring-1 ring-inset ring-black/40">
      <div className="h-full bg-zinc-100 transition-[width] duration-700 ease-out motion-reduce:transition-none" style={{ width: `${white}%` }} />
      <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-emerald-400/40" />
    </div>
  )
}

function ChessSection({ chess }: { chess: ChessLive | null }) {
  const wp = chess?.winPct ?? null
  const leaderWhite = wp !== null && wp >= 50
  const leadPct = wp === null ? null : Math.max(wp, 100 - wp)
  const swing = chess?.winSwing ?? null
  const swingMag = swing === null ? 0 : Math.abs(swing)

  return (
    <section className="space-y-4">
      <SectionHeader live eyebrow="Live now · Featured" title="Chess — top board" meta="lichess tv" />
      <div className="grid gap-5 md:grid-cols-[minmax(0,480px)_minmax(0,340px)]">
        <div className="overflow-hidden rounded-xl border border-zinc-800 bg-ink-900">
          <iframe src="https://lichess.org/tv/frame?theme=auto&bg=dark" title="Live chess board"
                  className="h-[420px] w-full sm:h-[480px]" style={{ border: 'none' }} />
        </div>

        <aside className="space-y-3">
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
            <div className="flex items-center justify-between text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">
              <span>Top live game</span><span className="font-mono">stockfish</span>
            </div>
            {!chess ? (
              <div className="mt-4 space-y-3 animate-pulse motion-reduce:animate-none">
                <div className="h-9 w-24 rounded bg-zinc-800" /><div className="h-3 w-full rounded bg-zinc-800" />
              </div>
            ) : !chess.live ? (
              <p className="mt-4 text-sm text-zinc-500">No featured game right now — back in a minute.</p>
            ) : (
              <>
                {wp !== null ? (
                  <div className="mt-3">
                    <div className="flex items-end justify-between">
                      <div>
                        <div className="text-[10px] uppercase tracking-[0.18em] text-zinc-500">{leaderWhite ? 'White' : 'Black'} to win</div>
                        <div className="font-mono text-4xl font-bold leading-none tabular-nums text-zinc-50">{leadPct!.toFixed(0)}<span className="text-xl text-zinc-500">%</span></div>
                      </div>
                      <div className="text-right font-mono text-xs tabular-nums">
                        {swingMag >= 2
                          ? <span className="text-amber-300">{swing! > 0 ? '▲' : '▼'} {swingMag.toFixed(1)} → {swing! > 0 ? 'White' : 'Black'}</span>
                          : <span className="text-zinc-600">steady</span>}
                        <div className="mt-0.5 text-[10px] uppercase tracking-wider text-zinc-600">last moves</div>
                      </div>
                    </div>
                    <div className="mt-3"><WinBar white={wp} /></div>
                  </div>
                ) : null}
                <div className="mt-4 space-y-2.5 border-t border-zinc-800 pt-3">
                  {(['white', 'black'] as const).map((c) => {
                    const p = c === 'white' ? chess.white : chess.black
                    const low = (p?.clock ?? 99) <= 20
                    return (
                      <div key={c} className="flex items-center justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-2">
                          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ring-1 ring-zinc-600 ${c === 'white' ? 'bg-zinc-100' : 'bg-zinc-800'}`} />
                          <span className="truncate text-sm font-medium text-zinc-100">{p?.name ?? '—'}</span>
                          {p?.rating ? <span className="font-mono text-xs text-zinc-500">{p.rating}</span> : null}
                        </div>
                        <span className={`font-mono text-sm tabular-nums ${low ? 'text-red-400' : 'text-zinc-300'}`}>{low ? '⏱ ' : ''}{clock(p?.clock)}</span>
                      </div>
                    )
                  })}
                </div>
              </>
            )}
          </div>
          {chess?.live && chess.moment ? (
            <div className="rounded-xl border-l-2 border-emerald-500 bg-emerald-500/[0.07] p-4">
              <Eyebrow>Moment that matters</Eyebrow>
              <p className="mt-1.5 text-sm font-semibold text-emerald-200">{chess.moment}</p>
            </div>
          ) : null}
        </aside>
      </div>
    </section>
  )
}

/* ---------------- page ---------------- */
export default function EsportsPage() {
  const [msi, setMsi] = useState<MSIData | null>(null)
  const [live, setLive] = useState<LiveMatch | null>(null)
  const [chess, setChess] = useState<ChessLive | null>(null)
  const timers = useRef<ReturnType<typeof setInterval>[]>([])

  useEffect(() => {
    let alive = true
    const j = (url: string, set: (d: any) => void) => async () => {
      try { const r = await fetch(url, { cache: 'no-store' }); const d = await r.json(); if (alive) set(d) } catch {}
    }
    const loadPred = j('/api/esports/lol/msi/predictions', setMsi)
    const loadLive = j('/api/esports/lol/msi/live', setLive)
    const loadChess = j('/api/esports/chess/live', setChess)
    loadPred(); loadLive(); loadChess()
    timers.current = [setInterval(loadPred, PRED_POLL_MS), setInterval(loadLive, 15_000), setInterval(loadChess, POLL_MS)]
    return () => { alive = false; timers.current.forEach(clearInterval) }
  }, [])

  const matches = msi?.matches ?? []
  const anyLive = !!live?.live || !!chess?.live

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

        {/* Feature exactly one live match — MSI if it's on, else the chess fallback */}
        {live?.live ? <LiveMSI m={live} /> : chess?.live ? <ChessSection chess={chess} /> : null}

        <section className="space-y-4">
          <SectionHeader eyebrow="Pre-game · MSI 2026" title="Win Predictions" meta={msi?.model ?? 'power-ranking prior'} />
          {msi?.error ? (
            <p className="text-sm text-zinc-500">Schedule unavailable right now — retrying.</p>
          ) : matches.length === 0 ? (
            <div className="grid gap-4 sm:grid-cols-2">
              {[0, 1].map((i) => <div key={i} className="h-32 animate-pulse rounded-xl border border-zinc-800 bg-zinc-900/40 motion-reduce:animate-none" />)}
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">{matches.map((m, i) => <MatchCard key={i} m={m} />)}</div>
          )}
          <p className="max-w-2xl text-xs text-zinc-600">
            Win % from expert power rankings (Elo → Bo5), priced against the Bovada line — the gap is the edge.
            Once a game is live, gold and objectives take over.
          </p>
        </section>
      </div>
    </>
  )
}
