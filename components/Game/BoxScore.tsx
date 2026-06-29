import { TeamStat, fmt, BoxScoreData } from './types'

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

// ── MLB box score (batting + pitching tables) ──
export function MLBBoxScore({ data }: { data: BoxScoreData }) {
  if (!data.available || !data.players || data.players.length === 0) {
    return (
      <div className="text-zinc-500 text-sm text-center py-12">
        Box score available at first pitch.
      </div>
    )
  }

  // Detect group type from column names (handles empty group names from ESPN)
  function detectGroupType(grp: typeof data.players[0]): string {
    if (grp.group && grp.group !== '') return grp.group
    const cols = (grp.columns || []).map(c => c.toUpperCase())
    if (cols.some(c => ['AVG', 'OBP', 'SLG', 'OPS'].includes(c))) return 'Batting'
    if (cols.some(c => ['ERA', 'WHIP'].includes(c))) return 'Pitching'
    if (cols.some(c => ['IP', 'PC-ST'].includes(c)) && !cols.some(c => ['AVG'].includes(c))) return 'Pitching'
    return 'Stats'
  }

  // Collect all groups with detected type
  const allGroups = data.players.map(g => ({ ...g, group: detectGroupType(g) }))

  // Identify away/home teams
  const awayAbbrev = data.teams?.[0]?.abbrev || ''
  const homeAbbrev = data.teams?.[1]?.abbrev || ''

  // Each group is team-specific — collect batting/pitching groups per team
  function getTeamRows(groups: typeof allGroups, groupType: string, teamAbbrev: string) {
    return groups.filter(g => g.group === groupType && g.team === teamAbbrev) || []
  }

  function computeTotals(rows: { stats: string[] }[], cols: string[]): string[] {
    const totals: string[] = []
    for (let ci = 0; ci < cols.length; ci++) {
      const colName = (cols[ci] || '').toUpperCase()
      if (colName === 'AVG' || colName === 'OBP' || colName === 'SLG' || colName === 'OPS') {
        const abIdx = cols.findIndex(c => (c || '').toUpperCase() === 'AB')
        const hIdx = cols.findIndex(c => (c || '').toUpperCase() === 'H')
        if (abIdx >= 0 && hIdx >= 0) {
          let totalAB = 0, totalH = 0
          for (const r of rows) {
            totalAB += parseInt(r.stats[abIdx]) || 0
            totalH += parseInt(r.stats[hIdx]) || 0
          }
          totals.push(totalAB > 0 ? (totalH / totalAB).toFixed(3).replace(/^0/, '') : '.000')
        } else {
          totals.push('')
        }
      } else if (colName === 'ERA') {
        const ipIdx = cols.findIndex(c => (c || '').toUpperCase() === 'IP')
        const erIdx = cols.findIndex(c => (c || '').toUpperCase() === 'ER')
        if (ipIdx >= 0 && erIdx >= 0) {
          let totalIP = 0, totalER = 0
          for (const r of rows) {
            totalIP += parseFloat(r.stats[ipIdx]) || 0
            totalER += parseInt(r.stats[erIdx]) || 0
          }
          totals.push(totalIP > 0 ? ((totalER * 9) / totalIP).toFixed(2) : '0.00')
        } else {
          totals.push('')
        }
      } else {
        let sum = 0
        for (const r of rows) sum += parseInt(r.stats[ci]) || 0
        totals.push(String(sum))
      }
    }
    return totals
  }

  function renderTable(groups: typeof allGroups, groupType: string) {
    const awayGroups = groups.filter(g => g.group === groupType && g.team === awayAbbrev)
    const homeGroups = groups.filter(g => g.group === groupType && g.team === homeAbbrev)

    if (awayGroups.length === 0 && homeGroups.length === 0) return null

    // Use columns from first available group
    const firstGroup = awayGroups[0] || homeGroups[0]
    if (!firstGroup || !firstGroup.rows || firstGroup.rows.length === 0) return null
    const cols = firstGroup.columns || []

    return (
      <div className="mb-6">
        {/* Eyebrow */}
        <div className="text-[10px] tracking-widest text-zinc-500 uppercase mb-2">{groupType}</div>

        {/* Column headers */}
        <div className="overflow-x-auto">
          <div className="grid border-b border-zinc-700 pb-1.5 mb-1"
               style={{ gridTemplateColumns: `minmax(120px,1fr) repeat(${cols.length}, 48px)` }}>
            <span></span>
            {cols.map((c, i) => (
              <span key={i} className="text-xs text-zinc-500 font-medium text-center min-w-[48px]">
                {c}
              </span>
            ))}
          </div>

          {/* Away team */}
          <div className="text-[11px] text-zinc-500 uppercase tracking-wide pt-3 pb-1">{awayAbbrev} (away)</div>
          {awayGroups.flatMap(g => g.rows).map((r, i) => (
            <div key={`a-${i}`} className="grid py-1.5 border-b border-zinc-800/30 text-sm"
                 style={{ gridTemplateColumns: `minmax(120px,1fr) repeat(${cols.length}, 48px)` }}>
              <span className="text-zinc-200 truncate">{r.name}</span>
              {r.stats.map((s, j) => {
                const colName = (cols[j] || '').toUpperCase()
                const isHR = colName === 'HR' && parseInt(s) > 0
                const isAVG = colName === 'AVG' && parseFloat(s) >= 0.300
                return (
                  <span key={j} className={`font-mono tabular-nums text-center text-sm ${
                    isHR ? 'text-amber-500' : isAVG ? 'text-amber-400/80' : 'text-zinc-300'
                  }`}>
                    {isHR ? `◆${s}` : s}
                  </span>
                )
              })}
            </div>
          ))}
          {/* Away totals */}
          {awayGroups.length > 0 && (
            <div className="grid py-2 border-t border-zinc-700 font-bold text-zinc-100 text-sm"
                 style={{ gridTemplateColumns: `minmax(120px,1fr) repeat(${cols.length}, 48px)` }}>
              <span>Totals</span>
              {computeTotals(awayGroups.flatMap(g => g.rows), cols).map((t, j) => (
                <span key={j} className="font-mono tabular-nums text-center">{t}</span>
              ))}
            </div>
          )}

          {/* Home team */}
          <div className="text-[11px] text-zinc-500 uppercase tracking-wide pt-4 pb-1">{homeAbbrev} (home)</div>
          {homeGroups.flatMap(g => g.rows).map((r, i) => (
            <div key={`h-${i}`} className="grid py-1.5 border-b border-zinc-800/30 text-sm"
                 style={{ gridTemplateColumns: `minmax(120px,1fr) repeat(${cols.length}, 48px)` }}>
              <span className="text-zinc-200 truncate">{r.name}</span>
              {r.stats.map((s, j) => {
                const colName = (cols[j] || '').toUpperCase()
                const isHR = colName === 'HR' && parseInt(s) > 0
                const isAVG = colName === 'AVG' && parseFloat(s) >= 0.300
                return (
                  <span key={j} className={`font-mono tabular-nums text-center text-sm ${
                    isHR ? 'text-amber-500' : isAVG ? 'text-amber-400/80' : 'text-zinc-300'
                  }`}>
                    {isHR ? `◆${s}` : s}
                  </span>
                )
              })}
            </div>
          ))}
          {/* Home totals */}
          {homeGroups.length > 0 && (
            <div className="grid py-2 border-t border-zinc-700 font-bold text-zinc-100 text-sm"
                 style={{ gridTemplateColumns: `minmax(120px,1fr) repeat(${cols.length}, 48px)` }}>
              <span>Totals</span>
              {computeTotals(homeGroups.flatMap(g => g.rows), cols).map((t, j) => (
                <span key={j} className="font-mono tabular-nums text-center">{t}</span>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      {renderTable(allGroups, 'Batting')}
      {renderTable(allGroups, 'Pitching')}
    </div>
  )
}

// ── NFL box score (passing / rushing / receiving tables + defense) ──
export function NFLBoxScore({ data }: { data: BoxScoreData }) {
  if (!data.available || !data.players || data.players.length === 0) {
    return (
      <div className="text-zinc-500 text-sm text-center py-12">
        Box score available at kickoff.
      </div>
    )
  }

  // Group by stat group name — use column detection if group name is empty
  function detectGroupType(grp: typeof data.players[0]): string {
    if (grp.group && grp.group !== '') return grp.group
    const cols = (grp.columns || []).map(c => c.toUpperCase())
    if (cols.some(c => ['C/ATT', 'CMP'].includes(c)) || (cols.includes('YDS') && cols.includes('TD') && cols.includes('INT'))) return 'Passing'
    if (cols.some(c => ['ATT', 'CAR'].includes(c)) && cols.includes('YDS') && cols.includes('TD') && !cols.includes('C/ATT')) return 'Rushing'
    if (cols.some(c => ['REC', 'TGT'].includes(c)) && cols.includes('YDS') && cols.includes('TD')) return 'Receiving'
    if (cols.some(c => ['TACK', 'TOT', 'SOLO', 'SACK'].includes(c))) return 'Defense'
    return grp.group || 'Stats'
  }

  const players = data.players.map(g => ({ ...g, group: detectGroupType(g) }))

  // Group by stat group name
  const groups: Record<string, typeof players> = {}
  for (const g of players) {
    if (!groups[g.group]) groups[g.group] = []
    groups[g.group].push(g)
  }

  const awayAbbrev = data.teams?.[0]?.abbrev || ''
  const homeAbbrev = data.teams?.[1]?.abbrev || ''

  // For NFL, each group might be team-specific (like MLB)
  function getTeamRows(grpSet: typeof players, teamAbbrev: string) {
    return grpSet.flatMap(g => (g.team === teamAbbrev ? g.rows : []))
  }

  function renderMiniTable(grpSet: typeof players) {
    const grp = grpSet[0]
    if (!grp || !grp.rows || grp.rows.length === 0) return null
    const cols = grp.columns || []
    const awayRows = getTeamRows(grpSet, awayAbbrev)
    const homeRows = getTeamRows(grpSet, homeAbbrev)

    // If all rows are from same team (team field might be empty), split evenly
    const allRows = awayRows.length > 0 || homeRows.length > 0 
      ? { away: awayRows, home: homeRows }
      : { away: grp.rows.slice(0, Math.ceil(grp.rows.length / 2)), home: grp.rows.slice(Math.ceil(grp.rows.length / 2)) }

    function computeSums(rows: { stats: string[] }[]): string[] {
      const sums: string[] = []
      for (let ci = 0; ci < cols.length; ci++) {
        const colName = (cols[ci] || '').toLowerCase()
        if (colName.includes('avg') || colName.includes('pct') || colName.includes('rate')) {
          sums.push('')
        } else {
          let total = 0
          for (const r of rows) {
            const parts = (r.stats[ci] || '').split('/')
            if (parts.length === 2) total += parseInt(parts[0]) || 0
            else total += parseInt(r.stats[ci]) || 0
          }
          sums.push(String(total))
        }
      }
      return sums
    }

    return (
      <div className="mb-6">
        {/* Group eyebrow */}
        <div className="text-[10px] tracking-widest text-zinc-500 uppercase mb-1.5 text-center">{grp.group}</div>

        <div className="overflow-x-auto">
          {/* Column headers */}
          <div className="grid border-b border-zinc-700 pb-1 mb-1"
               style={{ gridTemplateColumns: `minmax(100px,1fr) repeat(${cols.length}, minmax(44px, auto))` }}>
            <span></span>
            {cols.map((c, i) => (
              <span key={i} className="text-[10px] tracking-widest text-zinc-500 uppercase text-center">{c}</span>
            ))}
          </div>

          {/* Away players */}
          {allRows.away.length > 0 && (
            <>
              <div className="text-[10px] text-zinc-500 uppercase tracking-wider py-1.5 text-center">{awayAbbrev || 'AWAY'}</div>
              {allRows.away.map((r, i) => (
                <div key={`a-${i}`} className="grid py-1 border-b border-zinc-800/20 text-xs"
                     style={{ gridTemplateColumns: `minmax(100px,1fr) repeat(${cols.length}, minmax(44px, auto))` }}>
                  <span className="text-zinc-200 truncate pr-1">{r.name}</span>
                  {r.stats.map((s, j) => {
                    const colName = (cols[j] || '').toUpperCase()
                    const isTD = ['TD', 'TDS'].includes(colName) && parseInt(s) > 0
                    return (
                      <span key={j} className={`font-mono tabular-nums text-center text-zinc-300 ${isTD ? 'text-amber-400' : ''}`}>
                        {s}
                      </span>
                    )
                  })}
                </div>
              ))}
            </>
          )}

          {/* Home players */}
          {allRows.home.length > 0 && (
            <>
              <div className="text-[10px] text-zinc-500 uppercase tracking-wider py-1.5 text-center">{homeAbbrev || 'HOME'}</div>
              {allRows.home.map((r, i) => (
                <div key={`h-${i}`} className="grid py-1 border-b border-zinc-800/20 text-xs"
                     style={{ gridTemplateColumns: `minmax(100px,1fr) repeat(${cols.length}, minmax(44px, auto))` }}>
                  <span className="text-zinc-200 truncate pr-1">{r.name}</span>
                  {r.stats.map((s, j) => {
                    const colName = (cols[j] || '').toUpperCase()
                    const isTD = ['TD', 'TDS'].includes(colName) && parseInt(s) > 0
                    return (
                      <span key={j} className={`font-mono tabular-nums text-center text-zinc-300 ${isTD ? 'text-amber-400' : ''}`}>
                        {s}
                      </span>
                    )
                  })}
                </div>
              ))}
            </>
          )}

          {/* Totals */}
          <div className="grid py-1.5 border-t border-zinc-700 font-bold text-zinc-100 text-xs"
               style={{ gridTemplateColumns: `minmax(100px,1fr) repeat(${cols.length}, minmax(44px, auto))` }}>
            <span className="text-center">Totals</span>
            {computeSums([...allRows.away, ...allRows.home]).map((t, j) => (
              <span key={j} className="font-mono tabular-nums text-center">{t}</span>
            ))}
          </div>
        </div>
      </div>
    )
  }

  // Order: Passing, Rushing, Receiving, Defense
  const displayOrder = ['Passing', 'Rushing', 'Receiving', 'Defense', 'Defensive', 'Kicking', 'Punting', 'Returns']
  const offenseKeys = displayOrder.filter(k => k !== 'Defense' && k !== 'Defensive' && k !== 'Kicking' && k !== 'Punting' && k !== 'Returns' && k !== 'Stats')
  const defenseKeys = displayOrder.filter(k => k === 'Defense' || k === 'Defensive' || k === 'Kicking' || k === 'Punting' || k === 'Returns')

  return (
    <div>
      {/* Desktop: 3-column grid for offensive stats */}
      <div className="hidden lg:grid lg:grid-cols-[1fr_1fr_1fr] lg:gap-4">
        {offenseKeys.flatMap(key => {
          const grpSet = groups[key]
          if (!grpSet) return []
          return [renderMiniTable(grpSet)]
        })}
      </div>

      {/* Mobile: stack vertically */}
      <div className="lg:hidden space-y-0">
        {offenseKeys.map(key => {
          const grpSet = groups[key]
          if (!grpSet) return null
          return (
            <div key={key} className="border-t border-zinc-800 pt-4 mt-4 first:border-0 first:pt-0 first:mt-0">
              {renderMiniTable(grpSet)}
            </div>
          )
        })}
      </div>

      {/* Defense / special teams — full width below */}
      {defenseKeys.map(key => {
        const grpSet = groups[key]
        if (!grpSet) return null
        return (
          <div key={key} className="mt-6 pt-6 border-t border-zinc-800">
            {renderMiniTable(grpSet)}
          </div>
        )
      })}
    </div>
  )
}
