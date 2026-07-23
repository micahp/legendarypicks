import { useState, useEffect } from 'react'
import Head from 'next/head'
import { SportsService } from '../services/sports'

const LEAGUES = ['MLB', 'NBA', 'NHL', 'NFL']

interface Bucket {
  bucket: string
  n: number
  mean_predicted: number
  mean_realized: number
  error: number
  confidence: string
}
interface Calibration {
  buckets: Bucket[]
  brier_score: number | null
  brier_decomposition: { reliability: number; resolution: number; uncertainty: number }
  n_total: number
  n_paired: number
  n_single_excluded: number
}
interface EvProp {
  prop_id: number
  player_name: string
  team: string
  market: string
  line: number
  side: string
  odds_american: number
  p_implied: number
  p_fair: number
  ev: number
  de_vig_confidence: string
  settled: boolean
  hit: boolean | null
}
interface EvResp {
  props: EvProp[]
  summary: { total_props: number; positive_ev_pct: number; mean_ev: number | null; mean_ev_positive_only: number | null }
}
interface ClvResp {
  props: any[]
  summary: { mean_clv: number | null; positive_clv_pct: number; n_props: number }
  note: string | null
}

type Tab = 'calibration' | 'ev' | 'clv'

const fmtPct = (x: number) => `${(x * 100).toFixed(1)}%`
const fmtSigned = (x: number) => `${x >= 0 ? '+' : ''}${x.toFixed(4)}`

export default function AnalyticsPage() {
  const [league, setLeague] = useState('MLB')
  const [tab, setTab] = useState<Tab>('calibration')
  const [loading, setLoading] = useState(false)
  const [calib, setCalib] = useState<Calibration | null>(null)
  const [ev, setEv] = useState<EvResp | null>(null)
  const [clv, setClv] = useState<ClvResp | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      const lc = league.toLowerCase()
      const [c, e, v] = await Promise.all([
        SportsService.getCalibration(lc),
        SportsService.getPropsEV(lc, { limit: 50, min_ev: -1 }),
        SportsService.getPropsCLV(lc, { limit: 50 }),
      ])
      if (cancelled) return
      setCalib(c); setEv(e); setClv(v); setLoading(false)
    }
    load()
    return () => { cancelled = true }
  }, [league])

  return (
    <>
      <Head><title>Analytics — Legendary Picks</title></Head>
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight">Analytics</h1>
          <p className="text-zinc-500 text-sm mt-1">
            EV, calibration, and closing-line value from the Bovada odds-snapshot backbone (M7).
          </p>
        </div>

        {/* League selector */}
        <div className="flex items-center gap-2 flex-wrap">
          {LEAGUES.map((l) => (
            <button key={l} onClick={() => setLeague(l)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                league === l
                  ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                  : 'bg-zinc-900 text-zinc-400 border border-zinc-800 hover:text-zinc-200'}`}>
              {l}
            </button>
          ))}
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 border-b border-zinc-800">
          {([['calibration', 'Calibration'], ['ev', 'Expected Value'], ['clv', 'Closing-Line Value']] as [Tab, string][]).map(([t, label]) => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-2 text-sm font-medium -mb-px border-b-2 transition-colors ${
                tab === t ? 'border-emerald-400 text-emerald-400' : 'border-transparent text-zinc-400 hover:text-zinc-200'}`}>
              {label}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="text-zinc-500 text-sm">Loading...</div>
        ) : (
          <>
            {tab === 'calibration' && <CalibrationView data={calib} league={league} />}
            {tab === 'ev' && <EvView data={ev} league={league} />}
            {tab === 'clv' && <ClvView data={clv} league={league} />}
          </>
        )}
      </div>
    </>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-3">
      <div className="text-xs uppercase tracking-wider text-zinc-500">{label}</div>
      <div className="text-xl font-semibold text-zinc-100 mt-1">{value}</div>
    </div>
  )
}

function CalibrationView({ data, league }: { data: Calibration | null; league: string }) {
  if (!data || !data.buckets.length) return <Empty league={league} />
  const maxN = Math.max(...data.buckets.map((b) => b.n))
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="Brier" value={data.brier_score != null ? data.brier_score.toFixed(4) : '—'} />
        <Stat label="Reliability" value={data.brier_decomposition.reliability.toFixed(4)} />
        <Stat label="Resolution" value={data.brier_decomposition.resolution.toFixed(4)} />
        <Stat label="Paired props" value={`${data.n_paired}`} />
      </div>
      <p className="text-xs text-zinc-500">
        Brier 0.25 = coin-flip. Lower is better. Predicted = de-vigged fair probability;
        realized = actual hit rate. {data.n_single_excluded} single-side props excluded (vig-biased).
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-400 text-xs uppercase tracking-wider">
              <th className="text-left py-3 pr-4">Prob bucket</th>
              <th className="text-right py-3 px-3">N</th>
              <th className="text-right py-3 px-3">Predicted</th>
              <th className="text-right py-3 px-3">Realized</th>
              <th className="text-right py-3 px-3">Error</th>
              <th className="text-left py-3 pl-4 w-1/3">Predicted vs realized</th>
            </tr>
          </thead>
          <tbody>
            {data.buckets.map((b) => (
              <tr key={b.bucket} className="border-b border-zinc-800/50 hover:bg-zinc-900/50">
                <td className="py-3 pr-4 text-zinc-200 font-medium">{b.bucket}</td>
                <td className="py-3 px-3 text-right text-zinc-400">{b.n}</td>
                <td className="py-3 px-3 text-right text-zinc-300">{fmtPct(b.mean_predicted)}</td>
                <td className="py-3 px-3 text-right text-zinc-300">{fmtPct(b.mean_realized)}</td>
                <td className="py-3 px-3 text-right">
                  <span className={Math.abs(b.error) < 0.05 ? 'text-emerald-400' : 'text-amber-400'}>
                    {fmtSigned(b.error)}
                  </span>
                </td>
                <td className="py-3 pl-4">
                  <Bars predicted={b.mean_predicted} realized={b.mean_realized} weight={b.n / maxN} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Bars({ predicted, realized, weight }: { predicted: number; realized: number; weight: number }) {
  return (
    <div className="space-y-1" style={{ opacity: 0.4 + 0.6 * weight }}>
      <div className="flex items-center gap-2">
        <span className="text-[10px] w-10 text-zinc-500">pred</span>
        <div className="flex-1 h-2 bg-zinc-800 rounded">
          <div className="h-2 bg-zinc-400 rounded" style={{ width: `${predicted * 100}%` }} />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-[10px] w-10 text-zinc-500">real</span>
        <div className="flex-1 h-2 bg-zinc-800 rounded">
          <div className="h-2 bg-emerald-500 rounded" style={{ width: `${realized * 100}%` }} />
        </div>
      </div>
    </div>
  )
}

function EvView({ data, league }: { data: EvResp | null; league: string }) {
  if (!data || !data.props.length) return <Empty league={league} />
  const s = data.summary
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="Props" value={`${s.total_props}`} />
        <Stat label="Positive EV" value={fmtPct(s.positive_ev_pct / 100)} />
        <Stat label="Mean EV" value={s.mean_ev != null ? fmtSigned(s.mean_ev) : '—'} />
        <Stat label="Mean +EV only" value={s.mean_ev_positive_only != null ? fmtSigned(s.mean_ev_positive_only) : '—'} />
      </div>
      <p className="text-xs text-zinc-500">
        Fair probability comes from our own projection (recent game-log performance vs. the line) when
        there's enough history; otherwise it falls back to the market's de-vigged price, which only
        measures the vig you pay. Sorted by EV.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-400 text-xs uppercase tracking-wider">
              <th className="text-left py-3 pr-4">Player</th>
              <th className="text-left py-3 px-3">Market</th>
              <th className="text-right py-3 px-3">Line</th>
              <th className="text-right py-3 px-3">Odds</th>
              <th className="text-right py-3 px-3">Implied</th>
              <th className="text-right py-3 px-3">Fair</th>
              <th className="text-right py-3 px-3">EV</th>
              <th className="text-right py-3 pl-3">Result</th>
            </tr>
          </thead>
          <tbody>
            {data.props.map((p) => (
              <tr key={p.prop_id} className="border-b border-zinc-800/50 hover:bg-zinc-900/50">
                <td className="py-3 pr-4">
                  <span className="font-semibold text-zinc-200">{p.player_name}</span>
                  {p.team && <span className="text-zinc-500 ml-2">{p.team}</span>}
                </td>
                <td className="py-3 px-3 text-zinc-400">{p.market} <span className="uppercase text-zinc-600">{p.side}</span></td>
                <td className="py-3 px-3 text-right text-zinc-300">{p.line}</td>
                <td className="py-3 px-3 text-right text-zinc-300">{p.odds_american > 0 ? `+${p.odds_american}` : p.odds_american}</td>
                <td className="py-3 px-3 text-right text-zinc-400">{fmtPct(p.p_implied)}</td>
                <td className="py-3 px-3 text-right text-zinc-300">{fmtPct(p.p_fair)}</td>
                <td className="py-3 px-3 text-right">
                  <span className={p.ev > 0 ? 'text-emerald-400' : p.ev < 0 ? 'text-red-400' : 'text-zinc-400'}>{fmtSigned(p.ev)}</span>
                </td>
                <td className="py-3 pl-3 text-right">
                  {!p.settled ? <span className="text-zinc-600">—</span>
                    : p.hit ? <span className="text-emerald-400">hit</span>
                    : <span className="text-red-400">miss</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ClvView({ data, league }: { data: ClvResp | null; league: string }) {
  if (!data) return <Empty league={league} />
  if (!data.props.length) {
    return (
      <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg px-4 py-4 text-amber-300 text-sm">
        <div className="font-medium mb-1">No closing-line value yet</div>
        <div className="text-amber-300/80">
          {data.note || 'CLV needs closing odds snapshots, which are not captured yet.'} This view will
          populate once closing-snapshot capture is wired up — it is not a bug.
        </div>
      </div>
    )
  }
  const s = data.summary
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Stat label="Props" value={`${s.n_props}`} />
        <Stat label="Mean CLV" value={s.mean_clv != null ? fmtSigned(s.mean_clv) : '—'} />
        <Stat label="Positive CLV" value={fmtPct(s.positive_clv_pct / 100)} />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-400 text-xs uppercase tracking-wider">
              <th className="text-left py-3 pr-4">Player</th>
              <th className="text-left py-3 px-3">Market</th>
              <th className="text-right py-3 px-3">Open</th>
              <th className="text-right py-3 px-3">Close</th>
              <th className="text-right py-3 pl-3">CLV</th>
            </tr>
          </thead>
          <tbody>
            {data.props.map((p) => (
              <tr key={p.prop_id} className="border-b border-zinc-800/50 hover:bg-zinc-900/50">
                <td className="py-3 pr-4 font-semibold text-zinc-200">{p.player_name}</td>
                <td className="py-3 px-3 text-zinc-400">{p.market} <span className="uppercase text-zinc-600">{p.side}</span></td>
                <td className="py-3 px-3 text-right text-zinc-400">{fmtPct(p.p_open_implied)}</td>
                <td className="py-3 px-3 text-right text-zinc-300">{fmtPct(p.p_close_implied)}</td>
                <td className="py-3 pl-3 text-right">
                  <span className={p.clv > 0 ? 'text-emerald-400' : 'text-red-400'}>{fmtSigned(p.clv)}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Empty({ league }: { league: string }) {
  return <div className="text-zinc-500 text-sm">No analytics data available for {league}.</div>
}
