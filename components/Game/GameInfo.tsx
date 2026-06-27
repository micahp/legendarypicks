import { GameContext, StrengthRow } from './types'

// ── game info tab ──
export default function GameInfo({ ctx, homeStrength, awayStrength }: {
  ctx: GameContext | null; homeStrength?: StrengthRow; awayStrength?: StrengthRow
}) {
  return (
    <div className="space-y-5">
      {ctx && (
        <div className="space-y-3">
          <div className="flex justify-between text-sm">
            <span className="text-zinc-500">Venue</span>
            <span className="text-zinc-200">{ctx.venue_name}{ctx.venue_city ? `, ${ctx.venue_city}` : ''}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-zinc-500">Attendance</span>
            <span className="text-zinc-200">{ctx.attendance?.toLocaleString() || '-'}</span>
          </div>
          {ctx.officials.length > 0 && (
            <div className="flex justify-between text-sm">
              <span className="text-zinc-500">Officials</span>
              <span className="text-zinc-200 text-right">{ctx.officials.join(', ')}</span>
            </div>
          )}
        </div>
      )}

      {/* Season records */}
      <div>
        <div className="text-xs text-zinc-500 font-bold uppercase tracking-wide mb-3">Season Records</div>
        <div className="grid grid-cols-2 gap-4">
          {[awayStrength, homeStrength].map((s, i) => s ? (
            <div key={i} className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
              <div className="text-[10px] text-zinc-600 uppercase tracking-widest mb-1">{i === 0 ? 'Away' : 'Home'}</div>
              <div className="font-bold text-sm">{s.name} ({s.abbrev})</div>
              <div className="text-sm text-zinc-400 mt-1">{s.wins}-{s.losses}</div>
              <div className="text-xs text-zinc-500 mt-0.5">Win%: {(s.win_pct * 100).toFixed(1)}% · Streak: {s.streak}</div>
            </div>
          ) : null)}
        </div>
      </div>
    </div>
  )
}
