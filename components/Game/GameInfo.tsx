import { GameContext, StrengthRow, GameInfoData } from './types'

// ── game info tab ──
export default function GameInfo({
  ctx, homeStrength, awayStrength, extraInfo,
}: {
  ctx: GameContext | null; homeStrength?: StrengthRow; awayStrength?: StrengthRow
  extraInfo?: GameInfoData | null
}) {
  // Weather emoji mapping
  function weatherEmoji(condition: string): string {
    const c = (condition || '').toLowerCase()
    if (c.includes('rain') || c.includes('drizzle') || c.includes('shower')) return '🌧'
    if (c.includes('snow') || c.includes('flurries')) return '❄️'
    if (c.includes('wind') && !c.includes('rain')) return '💨'
    if (c.includes('cloud') || c.includes('overcast')) return '☁️'
    if (c.includes('sun') || c.includes('clear') || c.includes('fair')) return '☀️'
    return ''
  }

  function numFmt(n: number | undefined | null): string {
    if (n === undefined || n === null) return '-'
    return n.toLocaleString()
  }

  const info = extraInfo
  const hasOdds = info?.odds && (info.odds.spread || info.odds.overUnder || info.odds.favorite)
  const hasWeather = info?.weather && (info.weather.temperature !== null || info.weather.condition)
  const hasBroadcasts = info?.broadcasts && info.broadcasts.length > 0

  return (
    <div className="space-y-5">
      {/* Venue & Details */}
      <div className="space-y-3">
        {info?.venue && (
          <div className="flex justify-between text-sm">
            <span className="text-zinc-500">Venue</span>
            <span className="text-zinc-200 text-right">{info.venue}{info.city ? `, ${info.city}` : ''}</span>
          </div>
        )}
        {!info?.venue && ctx && (
          <div className="flex justify-between text-sm">
            <span className="text-zinc-500">Venue</span>
            <span className="text-zinc-200">{ctx.venue_name}{ctx.venue_city ? `, ${ctx.venue_city}` : ''}</span>
          </div>
        )}

        {(info?.attendance !== undefined && info.attendance !== null) && (
          <div className="flex justify-between text-sm">
            <span className="text-zinc-500">Attendance</span>
            <span className="text-zinc-200">
              {numFmt(info.attendance)}
              {info.capacity ? (
                <span className="text-zinc-500 ml-1">({Math.round((info.attendance! / info.capacity) * 100)}% full)</span>
              ) : null}
            </span>
          </div>
        )}
        {(!info || info.attendance === undefined || info.attendance === null) && ctx && (
          <div className="flex justify-between text-sm">
            <span className="text-zinc-500">Attendance</span>
            <span className="text-zinc-200">{ctx.attendance?.toLocaleString() || '-'}</span>
          </div>
        )}

        {info?.capacity && (
          <div className="flex justify-between text-sm">
            <span className="text-zinc-500">Capacity</span>
            <span className="text-zinc-200">{numFmt(info.capacity)}</span>
          </div>
        )}

        {/* Officials */}
        {info?.officials && info.officials.length > 0 && (
          <div className="flex justify-between text-sm">
            <span className="text-zinc-500">Officials</span>
            <span className="text-zinc-200 text-right">{info.officials.join(', ')}</span>
          </div>
        )}
        {(!info?.officials || info.officials.length === 0) && ctx && ctx.officials.length > 0 && (
          <div className="flex justify-between text-sm">
            <span className="text-zinc-500">Officials</span>
            <span className="text-zinc-200 text-right">{ctx.officials.join(', ')}</span>
          </div>
        )}
      </div>

      {/* Weather (NFL only — render only when weather data exists) */}
      {hasWeather && (
        <div className="bg-zinc-800/30 border border-zinc-800 rounded-lg px-3 py-2 flex items-center gap-2 text-sm">
          {info.weather.condition ? (
            <span className="text-base">{weatherEmoji(info.weather.condition)}</span>
          ) : null}
          {info.weather.temperature !== null && info.weather.temperature !== undefined ? (
            <span className="text-zinc-200 font-medium">{info.weather.temperature}°F</span>
          ) : null}
          {info.weather.wind ? (
            <>
              <span className="text-zinc-700">·</span>
              <span className="text-zinc-400">Wind {info.weather.wind}</span>
            </>
          ) : null}
          {info.weather.condition ? (
            <>
              <span className="text-zinc-700">·</span>
              <span className="text-zinc-400">{info.weather.condition}</span>
            </>
          ) : null}
        </div>
      )}

      {/* Odds (if available) */}
      {hasOdds && (
        <div>
          <div className="text-xs text-zinc-500 font-bold uppercase tracking-wide mb-3">Game Odds</div>
          <div className="flex flex-wrap gap-3">
            {info.odds.spread ? (
              <div className="bg-zinc-800/50 border border-zinc-800 rounded-lg px-4 py-3 min-w-[100px]">
                <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Spread</div>
                <div className="font-mono tabular-nums text-sm text-zinc-200">{info.odds.spread}</div>
              </div>
            ) : null}
            {info.odds.overUnder ? (
              <div className="bg-zinc-800/50 border border-zinc-800 rounded-lg px-4 py-3 min-w-[100px]">
                <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">O/U</div>
                <div className="font-mono tabular-nums text-sm text-zinc-200">{info.odds.overUnder}</div>
              </div>
            ) : null}
            {info.odds.favorite ? (
              <div className="bg-zinc-800/50 border border-zinc-800 rounded-lg px-4 py-3 min-w-[100px]">
                <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Favorite</div>
                <div className="text-sm text-zinc-200">
                  {info.odds.favorite !== 'EVEN' ? (
                    <span className="text-emerald-500">● </span>
                  ) : null}
                  {info.odds.favorite === 'EVEN' ? 'Pick \'em' : info.odds.favorite}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}

      {/* Broadcasts */}
      {hasBroadcasts && (
        <div className="flex justify-between text-sm">
          <span className="text-zinc-500">TV</span>
          <span className="text-zinc-200 text-right">{info.broadcasts.join(', ')}</span>
        </div>
      )}

      {/* Season records — a heading over an empty grid claims data that isn't
          there. Renders only when at least one side resolved (both sides null
          was the fallout of the abbrev/name key mismatch fixed 2026-08-30;
          this guard also covers the honest case, a league with no strength
          data at all, e.g. ATP/WTA pre-season). */}
      {(awayStrength || homeStrength) && (
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
      )}
    </div>
  )
}
