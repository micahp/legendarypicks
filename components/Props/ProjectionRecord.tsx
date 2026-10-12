import { useEffect, useState } from 'react'

// The graded record of the NFL player projections: version 2 against Marcel-lite and ESPN's published
// weekly projection, per week and stat, on the player-games every listed version projected. Counts and
// errors only; a week with no graded games is not drawn as a zero.

type Version = 'v2' | 'marcel-lite' | 'espn-weekly'
interface StatResult { n: number; [version: string]: any }
interface WeekRecord {
  week: number
  counts: Record<string, { graded: number | null; dnp: number | null }>
  stats: Record<string, StatResult>
}
interface Record_ { season: number | null; weeks: WeekRecord[]; note: string }

const STATS: { key: string; label: string; digits: number }[] = [
  { key: 'rec_yds', label: 'Receiving yards', digits: 1 },
  { key: 'rec', label: 'Receptions', digits: 2 },
  { key: 'tgt', label: 'Targets', digits: 2 },
  { key: 'rec_td', label: 'Receiving TDs', digits: 3 },
]
const COLS: { key: Version; label: string }[] = [
  { key: 'v2', label: 'Ours (v2)' },
  { key: 'marcel-lite', label: 'Marcel-lite' },
  { key: 'espn-weekly', label: 'ESPN' },
]

export default function ProjectionRecord() {
  const [data, setData] = useState<Record_ | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let live = true
    fetch('/api/nfl/projections/record')
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (live) setData(d) })
      .catch(() => { if (live) setFailed(true) })
    return () => { live = false }
  }, [])

  if (failed) return <p data-record-error className="text-xs text-amber-400">The projection record could not be loaded.</p>
  if (!data) return <div className="h-24 animate-pulse rounded-lg bg-zinc-800/60" />
  return (
    <section data-projection-record className="rounded-lg bg-zinc-900 border border-zinc-800">
      <header className="px-4 pt-3 pb-2">
        <h2 className="text-sm font-semibold text-zinc-200">Projection record</h2>
        <p className="text-[11px] text-zinc-500">
          Mean absolute error in the stat's own units (lower is better), over the player-games every column
          projected. Players who did not play are not scored.
        </p>
      </header>
      {!data.weeks.length ? (
        <p data-record-empty className="px-4 pb-4 text-xs text-zinc-500">No graded weeks yet. A week is graded once its games are final.</p>
      ) : (
        [...data.weeks].reverse().map(w => {
          const counts = w.counts['v2']
          return (
            <div key={w.week} data-record-week={w.week} className="border-t border-zinc-800 px-4 py-3">
              <div className="mb-1 flex items-baseline justify-between text-xs">
                <span className="font-semibold text-zinc-300">Week {w.week}</span>
                <span className="tabular-nums text-zinc-500">
                  {counts ? `${counts.graded ?? 0} scored · ${counts.dnp ?? 0} did not play` : ''}
                </span>
              </div>
              <table className="w-full text-xs tabular-nums">
                <thead>
                  <tr className="text-left text-[11px] text-zinc-500">
                    <th className="py-1 font-normal">Stat</th>
                    {COLS.map(c => <th key={c.key} className="py-1 text-right font-normal">{c.label}</th>)}
                    <th className="py-1 text-right font-normal">n</th>
                  </tr>
                </thead>
                <tbody>
                  {STATS.filter(s => w.stats[s.key]).map(s => {
                    const row = w.stats[s.key]
                    const maes = COLS.map(c => row[c.key]?.mae).filter((x: any) => typeof x === 'number')
                    const best = maes.length ? Math.min(...maes) : null
                    return (
                      <tr key={s.key} className="border-t border-zinc-800/70">
                        <td className="py-1 text-zinc-400">{s.label}</td>
                        {COLS.map(c => {
                          const m = row[c.key]?.mae
                          return (
                            <td key={c.key} className={`py-1 text-right ${m === best && best !== null ? 'font-semibold text-zinc-100' : 'text-zinc-400'}`}>
                              {typeof m === 'number' ? m.toFixed(s.digits) : '—'}
                            </td>
                          )
                        })}
                        <td className="py-1 text-right text-zinc-500">{row.n}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )
        })
      )}
    </section>
  )
}
