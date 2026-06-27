import { TeamStat, fmt } from './types'

// ── NBA box score (team stats, two-column) ──
export function NBABoxScore({ stats }: { stats: TeamStat[] }) {
  const away = stats.find(s => s.home_away === 'away')
  const home = stats.find(s => s.home_away === 'home')
  if (!home || !away) return null
  const rows: [string, keyof TeamStat, keyof TeamStat, boolean?][] = [
    ['Field Goals', 'fgm_fga', 'fgm_fga'],
    ['Field Goal %', 'fg_pct', 'fg_pct', true],
    ['3-Pointers', 'tpm_tpa', 'tpm_tpa'],
    ['3-Point %', 'tp_pct', 'tp_pct', true],
    ['Free Throws', 'ftm_fta', 'ftm_fta'],
    ['Free Throw %', 'ft_pct', 'ft_pct', true],
    ['Rebounds', 'rebounds', 'rebounds'],
    ['Offensive Rebounds', 'off_rebounds', 'off_rebounds'],
    ['Assists', 'assists', 'assists'],
    ['Steals', 'steals', 'steals'],
    ['Blocks', 'blocks', 'blocks'],
    ['Turnovers', 'turnovers', 'turnovers'],
    ['Fouls', 'fouls', 'fouls'],
    ['Fast Break Pts', 'fast_break_pts', 'fast_break_pts'],
    ['Points in Paint', 'pts_in_paint', 'pts_in_paint'],
    ['Largest Lead', 'largest_lead', 'largest_lead'],
  ]
  return (
    <div>
      {/* Column headers */}
      <div className="grid grid-cols-[1fr_100px_100px] gap-3 text-xs text-zinc-500 font-bold pb-2 border-b border-zinc-700 mb-1">
        <span></span>
        <span className="text-right">{away.team_abbrev}</span>
        <span className="text-right">{home.team_abbrev}</span>
      </div>
      {rows.map(([label, aKey, hKey, pct]) => {
        const av = away[aKey]; const hv = home[hKey]
        if (av === undefined && hv === undefined) return null
        if (av === null && hv === null) return null
        return (
          <div key={label} className="grid grid-cols-[1fr_100px_100px] gap-3 text-sm py-1.5 border-b border-zinc-800/40 last:border-0">
            <span className="text-zinc-400">{label}</span>
            <span className="text-right font-mono text-zinc-200">
              {pct && typeof av === 'number' ? av.toFixed(1) : fmt(av)}
            </span>
            <span className="text-right font-mono text-zinc-200">
              {pct && typeof hv === 'number' ? hv.toFixed(1) : fmt(hv)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

export function NHLBoxScore({ stats }: { stats: TeamStat[] }) {
  const away = stats.find(s => s.home_away === 'away')
  const home = stats.find(s => s.home_away === 'home')
  if (!home || !away) return null
  const rows: [string, keyof TeamStat, keyof TeamStat, boolean?][] = [
    ['Shots', 'shots', 'shots'],
    ['Blocked Shots', 'blocked_shots', 'blocked_shots'],
    ['Hits', 'hits', 'hits'],
    ['Faceoffs Won', 'faceoffs_won', 'faceoffs_won'],
    ['Faceoff %', 'faceoff_pct', 'faceoff_pct', true],
    ['Takeaways', 'takeaways', 'takeaways'],
    ['Giveaways', 'giveaways', 'giveaways'],
    ['Power Play Goals', 'powerplay_goals', 'powerplay_goals'],
    ['Power Play Opps', 'powerplay_opps', 'powerplay_opps'],
    ['Penalties', 'penalties', 'penalties'],
    ['Penalty Minutes', 'penalty_min', 'penalty_min'],
  ]
  return (
    <div>
      <div className="grid grid-cols-[1fr_100px_100px] gap-3 text-xs text-zinc-500 font-bold pb-2 border-b border-zinc-700 mb-1">
        <span></span>
        <span className="text-right">{away.team_abbrev}</span>
        <span className="text-right">{home.team_abbrev}</span>
      </div>
      {rows.map(([label, aKey, hKey, pct]) => {
        const av = away[aKey]; const hv = home[hKey]
        if (av === undefined && hv === undefined) return null
        if (av === null && hv === null) return null
        return (
          <div key={label} className="grid grid-cols-[1fr_100px_100px] gap-3 text-sm py-1.5 border-b border-zinc-800/40 last:border-0">
            <span className="text-zinc-400">{label}</span>
            <span className="text-right font-mono text-zinc-200">
              {pct && typeof av === 'number' ? av.toFixed(1) : fmt(av)}
            </span>
            <span className="text-right font-mono text-zinc-200">
              {pct && typeof hv === 'number' ? hv.toFixed(1) : fmt(hv)}
            </span>
          </div>
        )
      })}
    </div>
  )
}
