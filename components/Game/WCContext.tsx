import { useEffect, useState } from 'react'

type Scorer = { team: string; player: string; odds: number }
type Insight = { tag: string; subject: string; quote: string; strength: number; ts?: string }
type Prop = { player: string; market: string; line: string; lean: string }
type Read = { headline: string; evidence?: string; prop?: Prop }

const LEAN_STYLE: Record<string, { cls: string; mark: string }> = {
  back: { cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30', mark: '▲' },
  fade: { cls: 'bg-red-500/15 text-red-300 border-red-500/30', mark: '▼' },
  watch: { cls: 'bg-zinc-700/40 text-zinc-300 border-zinc-600/50', mark: '•' },
}

function PropChip({ prop }: { prop: Prop }) {
  const s = LEAN_STYLE[prop.lean] || LEAN_STYLE.watch
  return (
    <span className={`mt-1 inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium ${s.cls}`}>
      <span className="text-[10px]">{s.mark}</span>
      <span className="uppercase tracking-wide text-[9px] opacity-70">{prop.lean}</span>
      <span className="font-semibold">{prop.player}</span>
      <span className="opacity-80">{prop.market}</span>
      <span className="font-mono tabular-nums">{prop.line}</span>
    </span>
  )
}
type Ctx = {
  headline: string
  status?: string
  teams: { home: { abbr: string; name: string; form?: string | null }; away: { abbr: string; name: string; form?: string | null } }
  top_scorers: Scorer[]
  read?: Read[]
  insights: Insight[]
}

// Broadcast-derived reads are colored by their tag so a fan can scan the timeline.
const TAG_STYLE: Record<string, string> = {
  'Key man': 'bg-amber-500/15 text-amber-300 border-amber-500/25',
  Momentum: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25',
  Tactical: 'bg-sky-500/15 text-sky-300 border-sky-500/25',
  Mentality: 'bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/25',
  Fatigue: 'bg-orange-500/15 text-orange-300 border-orange-500/25',
}

function FormChips({ form }: { form?: string | null }) {
  if (!form) return null
  return (
    <span className="inline-flex gap-0.5">
      {form.split('').map((r, i) => (
        <span key={i} className={`inline-flex h-4 w-4 items-center justify-center rounded-sm text-[9px] font-bold ${
          r === 'W' ? 'bg-emerald-500/20 text-emerald-300' : r === 'L' ? 'bg-red-500/20 text-red-300' : 'bg-zinc-700/50 text-zinc-400'
        }`}>{r}</span>
      ))}
    </span>
  )
}

const fmtOdds = (o: number) => (o > 0 ? `+${o}` : `${o}`)

export default function WCContext({ gameId }: { gameId: string }) {
  const [ctx, setCtx] = useState<Ctx | null | undefined>(undefined)

  useEffect(() => {
    let alive = true
    fetch(`/api/wc/${gameId}/context`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (alive) setCtx(d) })
      .catch(() => { if (alive) setCtx(null) })
    return () => { alive = false }
  }, [gameId])

  if (ctx === undefined) return (
    <div className="border-l-2 border-emerald-600/40 pl-3 space-y-2 animate-pulse">
      <div className="h-3 bg-zinc-800 rounded w-1/2" />
      <div className="h-3 bg-zinc-800 rounded w-3/4" />
    </div>
  )
  if (!ctx) return null

  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-hidden">
      {/* header */}
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-2.5">
        <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-emerald-400">Game Context</span>
        <span className="text-[10px] text-zinc-500">from the broadcast · market · form</span>
      </div>

      {/* The Read: synthesized intel, takeaway-first (the value; quotes are the receipts in the tab) */}
      {ctx.read && ctx.read.length > 0 && (
        <ul className="divide-y divide-zinc-800/70">
          {ctx.read.map((r, i) => (
            <li key={i} className="px-4 py-3">
              <div className="flex gap-2.5">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
                <div>
                  <p className="text-sm font-semibold leading-snug text-zinc-100">{r.headline}</p>
                  {r.evidence && <p className="mt-0.5 text-xs leading-snug text-zinc-500">{r.evidence}</p>}
                  {r.prop && <div><PropChip prop={r.prop} /></div>}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* form + most likely to score */}
      <div className="grid gap-px border-t border-zinc-800 bg-zinc-800 sm:grid-cols-2">
        {[ctx.teams.away, ctx.teams.home].map(t => {
          const scorer = ctx.top_scorers.find(s => s.team === t.abbr)
          return (
            <div key={t.abbr} className="bg-zinc-900 px-4 py-3">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-zinc-100">{t.name}</span>
                <FormChips form={t.form} />
              </div>
              {scorer && (
                <div className="mt-2 flex items-baseline justify-between">
                  <span className="text-xs text-zinc-500">Most likely to score</span>
                  <span className="text-sm text-zinc-200">
                    <span className="font-semibold">{scorer.player}</span>
                    <span className="ml-1.5 font-mono tabular-nums text-emerald-400">{fmtOdds(scorer.odds)}</span>
                  </span>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* fallback: raw booth reads only if synthesis is unavailable */}
      {(!ctx.read || ctx.read.length === 0) && ctx.insights.length > 0 && (
        <div className="space-y-2.5 px-4 py-3">
          {ctx.insights.map((it, i) => (
            <div key={i} className="flex items-start gap-2.5">
              <span className={`mt-0.5 shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium ${TAG_STYLE[it.tag] || 'bg-zinc-800 text-zinc-400 border-zinc-700'}`}>
                {it.tag}
              </span>
              <p className="text-sm leading-snug text-zinc-300">
                {it.subject && <span className="font-semibold text-zinc-100">{it.subject}: </span>}
                <span className="text-zinc-400">“{it.quote}”</span>
              </p>
            </div>
          ))}
          <p className="pt-1 text-[10px] text-zinc-600">Insight pulled live from the match broadcast.</p>
        </div>
      )}
    </section>
  )
}
