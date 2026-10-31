import { useEffect, useState } from 'react'
import Head from 'next/head'
import ProjectionRecord from '../../components/Props/ProjectionRecord'

interface Line { mean: number; median: number | null; p10: number | null; p90: number | null }
interface SlatePlayer {
  game_id: string; player_id: number; team: string; name: string; position: string; p_plays: number | null
  v2: Record<string, Line>; marcel: Record<string, number>; espn: Record<string, number>
}
interface Slate { season: number | null; week: number | null; weeks: number[]; players: SlatePlayer[] }

const fmt = (v: number | undefined | null, d = 1) => (typeof v === 'number' ? v.toFixed(d) : '-')
const SHOWN = 40

export default function NflProjections() {
  const [week, setWeek] = useState<number | null>(null)
  const [slate, setSlate] = useState<Slate | null>(null)
  const [failed, setFailed] = useState(false)
  const [all, setAll] = useState(false)

  useEffect(() => {
    let live = true
    setSlate(null); setFailed(false)
    fetch(week === null ? '/api/nfl/projections' : `/api/nfl/projections?week=${week}`)
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (live) setSlate(d) })
      .catch(() => { if (live) setFailed(true) })
    return () => { live = false }
  }, [week])

  const receivers = slate ? slate.players.filter(p => p.v2.rec_yds) : []
  const passers = slate ? slate.players.filter(p => p.v2.pass_yds) : []
  const rows = all ? receivers : receivers.slice(0, SHOWN)
  return (
    <div className="space-y-4">
      <Head><title>NFL player projections</title></Head>
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">NFL player projections</h1>
        <p className="text-xs text-zinc-500">
          Running backs, wide receivers and tight ends, and each team's expected passer. Every figure is what we
          expect <em>if the player plays</em>;
          the last column is the chance he does. The band is the 10th to 90th percentile of the simulation and is
          wider than it needs to be: it is not calibrated.
        </p>
      </div>

      {failed && <p className="text-xs text-amber-400">The projections could not be loaded.</p>}
      {!failed && !slate && <div className="h-40 animate-pulse rounded-lg bg-zinc-800/60" />}
      {slate && (
        <section data-projection-slate className="rounded-lg bg-zinc-900 border border-zinc-800">
          <header className="flex items-center gap-2 px-4 pt-3 pb-2">
            <h2 className="text-sm font-semibold text-zinc-200">
              {slate.week === null ? 'No projections yet' : `Week ${slate.week}`}
            </h2>
            {slate.weeks.length > 1 && slate.weeks.map(w => (
              <button key={w} onClick={() => setWeek(w)}
                className={`px-2 py-0.5 rounded text-[11px] ${w === slate.week ? 'bg-zinc-700 text-zinc-200' : 'text-zinc-500 hover:text-zinc-300'}`}>{w}</button>
            ))}
          </header>
          {!receivers.length ? (
            <p className="px-4 pb-4 text-xs text-zinc-500">Nothing has been projected for this week.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-xs tabular-nums">
                <thead>
                  <tr className="border-t border-zinc-800 text-left text-[11px] text-zinc-500">
                    <th className="px-4 py-1.5 font-normal">Player</th>
                    <th className="py-1.5 text-right font-normal">Rec yds</th>
                    <th className="py-1.5 text-right font-normal">10 to 90</th>
                    <th className="py-1.5 text-right font-normal">Rec</th>
                    <th className="py-1.5 text-right font-normal">ESPN yds</th>
                    <th className="py-1.5 text-right font-normal">Marcel yds</th>
                    <th className="px-4 py-1.5 text-right font-normal">Plays</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(p => (
                    <tr key={`${p.game_id}-${p.player_id}`} className="border-t border-zinc-800/70">
                      <td className="px-4 py-1.5">
                        <a href={`/player/${p.player_id}`} className="text-zinc-300 hover:text-emerald-400">{p.name}</a>
                        <span className="ml-1.5 text-zinc-600">{p.team} {p.position}</span>
                      </td>
                      <td className="py-1.5 text-right font-semibold text-zinc-100">{fmt(p.v2.rec_yds?.mean)}</td>
                      <td className="py-1.5 text-right text-zinc-500">{fmt(p.v2.rec_yds?.p10, 0)} to {fmt(p.v2.rec_yds?.p90, 0)}</td>
                      <td className="py-1.5 text-right text-zinc-300">{fmt(p.v2.rec?.mean)}</td>
                      <td className="py-1.5 text-right text-zinc-400">{fmt(p.espn.rec_yds)}</td>
                      <td className="py-1.5 text-right text-zinc-400">{fmt(p.marcel.rec_yds)}</td>
                      <td className="px-4 py-1.5 text-right text-zinc-500">
                        {typeof p.p_plays === 'number' ? `${Math.round(p.p_plays * 100)}%` : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {receivers.length > SHOWN && (
                <button onClick={() => setAll(!all)} className="w-full border-t border-zinc-800 px-4 py-2 text-left text-[11px] text-zinc-500 hover:text-zinc-300">
                  {all ? `Show the top ${SHOWN}` : `Show all ${receivers.length}`}
                </button>
              )}
            </div>
          )}
        </section>
      )}

      {passers.length > 0 && (
        <section data-projection-passers className="rounded-lg bg-zinc-900 border border-zinc-800">
          <header className="px-4 pt-3 pb-2">
            <h2 className="text-sm font-semibold text-zinc-200">Quarterbacks</h2>
            <p className="text-[11px] text-zinc-500">The passer each team is expected to start, if he plays.</p>
          </header>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-xs tabular-nums">
              <thead>
                <tr className="border-t border-zinc-800 text-left text-[11px] text-zinc-500">
                  <th className="px-4 py-1.5 font-normal">Player</th>
                  <th className="py-1.5 text-right font-normal">Pass yds</th>
                  <th className="py-1.5 text-right font-normal">10 to 90</th>
                  <th className="py-1.5 text-right font-normal">Att</th>
                  <th className="py-1.5 text-right font-normal">Cmp</th>
                  <th className="py-1.5 text-right font-normal">TD</th>
                  <th className="py-1.5 text-right font-normal">Marcel yds</th>
                  <th className="px-4 py-1.5 text-right font-normal">Plays</th>
                </tr>
              </thead>
              <tbody>
                {[...passers].sort((a, b) => b.v2.pass_yds.mean - a.v2.pass_yds.mean).map(p => (
                  <tr key={`${p.game_id}-${p.player_id}`} className="border-t border-zinc-800/70">
                    <td className="px-4 py-1.5">
                      <a href={`/player/${p.player_id}`} className="text-zinc-300 hover:text-emerald-400">{p.name}</a>
                      <span className="ml-1.5 text-zinc-600">{p.team}</span>
                    </td>
                    <td className="py-1.5 text-right font-semibold text-zinc-100">{fmt(p.v2.pass_yds?.mean, 0)}</td>
                    <td className="py-1.5 text-right text-zinc-500">{fmt(p.v2.pass_yds?.p10, 0)} to {fmt(p.v2.pass_yds?.p90, 0)}</td>
                    <td className="py-1.5 text-right text-zinc-300">{fmt(p.v2.att?.mean)}</td>
                    <td className="py-1.5 text-right text-zinc-300">{fmt(p.v2.cmp?.mean)}</td>
                    <td className="py-1.5 text-right text-zinc-300">{fmt(p.v2.pass_td?.mean)}</td>
                    <td className="py-1.5 text-right text-zinc-400">{fmt(p.marcel.pass_yds, 0)}</td>
                    <td className="px-4 py-1.5 text-right text-zinc-500">
                      {typeof p.p_plays === 'number' ? `${Math.round(p.p_plays * 100)}%` : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <ProjectionRecord />
    </div>
  )
}
