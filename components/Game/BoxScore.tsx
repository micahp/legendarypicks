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
// A team's total for one box-score column, or '' when the column does not add up.
// Counts add. LONG is the team's longest. "a/b" (C/ATT) and "a-b" (SACKS) add each part. Averages, rates and ratings
// are not sums, so they stay blank rather than show a number nobody published.
const NOT_ADDITIVE = ['AVG', 'PCT', 'RATE', 'RTG', 'QBR', 'YDS/G', 'Y/A', 'Y/C', 'Y/R', 'CMP%']
export function columnTotal(column: string, values: string[]): string {
  const name = (column || '').toUpperCase()
  if (NOT_ADDITIVE.some(k => name.includes(k))) return ''
  const present = values.map(v => (v ?? '').trim()).filter(v => v !== '' && v !== '-' && v !== '--')
  if (present.length === 0) return ''
  for (const [sep, pattern] of [['/', /^\d+\/\d+$/], ['-', /^\d+-\d+$/]] as [string, RegExp][]) {
    if (present.every(v => pattern.test(v))) {
      const parts = present.map(v => v.split(sep).map(n => parseInt(n)))
      return `${parts.reduce((t, p) => t + p[0], 0)}${sep}${parts.reduce((t, p) => t + p[1], 0)}`
    }
  }
  if (!present.every(v => /^-?\d+$/.test(v))) return ''
  const numbers = present.map(v => parseInt(v))
  if (name === 'LONG' || name === 'LNG') return String(Math.max(...numbers))
  return String(numbers.reduce((t, n) => t + n, 0))
}

export function NFLBoxScore({ data }: { data: BoxScoreData }) {
  if (!data.available || !data.players || data.players.length === 0) {
    return (
      <div className="text-zinc-500 text-sm text-center py-12">
        Box score available at kickoff.
      </div>
    )
  }

  // The backend names each group from ESPN's own name (Passing, Interceptions, Kick Returns, ...). A payload saved
  // before that fix has empty names, so the group is read from its columns. INT, YDS, TD alone is the
  // interceptions group, not passing; a column set we cannot place keeps its own heading rather than merge.
  function detectGroupType(grp: typeof data.players[0]): string {
    if (grp.group && grp.group !== '') return grp.group
    const cols = (grp.columns || []).map(c => c.toUpperCase())
    if (cols.some(c => ['C/ATT', 'CMP'].includes(c))) return 'Passing'
    if (cols.length === 3 && cols[0] === 'INT' && cols.includes('YDS') && cols.includes('TD')) return 'Interceptions'
    if (cols.includes('FUM') && cols.includes('LOST')) return 'Fumbles'
    if (cols.includes('FG') && cols.includes('XP')) return 'Kicking'
    if (cols.includes('TB') && cols.includes('IN 20')) return 'Punting'
    if (cols.some(c => ['ATT', 'CAR'].includes(c)) && cols.includes('YDS') && cols.includes('TD') && !cols.includes('C/ATT')) return 'Rushing'
    if (cols.some(c => ['REC', 'TGT'].includes(c)) && cols.includes('YDS') && cols.includes('TD')) return 'Receiving'
    if (cols.some(c => ['TACK', 'TOT', 'SOLO', 'SACK'].includes(c))) return 'Defense'
    return `Stats (${(grp.columns || []).join(', ')})`
  }

  const players = data.players.map(g => ({ ...g, group: detectGroupType(g) }))
  const groups: Record<string, typeof players> = {}
  for (const g of players) {
    if (!groups[g.group]) groups[g.group] = []
    groups[g.group].push(g)
  }

  const awayAbbrev = data.teams?.[0]?.abbrev || ''
  const homeAbbrev = data.teams?.[1]?.abbrev || ''

  function renderTable(key: string, grpSet: typeof players) {
    const grp = grpSet[0]
    if (!grp || grpSet.every(g => !g.rows || g.rows.length === 0)) return null  // neither team has a row
    const cols = grp.columns || []
    const byTeam = (abbrev: string) => grpSet.flatMap(g => (g.team === abbrev ? g.rows : []))
    const known = byTeam(awayAbbrev).length > 0 || byTeam(homeAbbrev).length > 0
    // A group with no team on its rows is shown as one block with no team split: the split cannot be read, so it is not guessed.
    const sides = known
      ? [{ team: awayAbbrev || 'Away', rows: byTeam(awayAbbrev) }, { team: homeAbbrev || 'Home', rows: byTeam(homeAbbrev) }]
      : [{ team: '', rows: grpSet.flatMap(g => g.rows) }]

    return (
      <section key={key} className="border-t border-zinc-800 pt-4 first:border-0 first:pt-0">
        <h3 className="text-[10px] tracking-widest text-zinc-500 uppercase mb-2">{grp.group}</h3>
        <div className="overflow-x-auto min-w-0">
          <table className="w-full text-xs tabular-nums">
            <thead>
              <tr className="border-b border-zinc-700 text-[10px] tracking-widest text-zinc-500 uppercase">
                <th className="sticky left-0 bg-zinc-900 text-left font-normal pb-1 pr-3 w-full"></th>
                {cols.map((c, i) => (
                  <th key={i} className="text-right font-normal pb-1 pl-2 sm:pl-3 whitespace-nowrap">{c}</th>
                ))}
              </tr>
            </thead>
            {sides.filter(side => side.rows.length > 0).map(side => (
              <tbody key={side.team || 'all'}>
                {side.team && (
                  <tr>
                    <td colSpan={cols.length + 1} className="pt-3 pb-1 text-[10px] text-zinc-500 uppercase tracking-wider">
                      {side.team}
                    </td>
                  </tr>
                )}
                {side.rows.map((r, i) => (
                  <tr key={i} className="border-b border-zinc-800/40">
                    <td className="sticky left-0 bg-zinc-900 py-1 pr-3 text-zinc-200 whitespace-nowrap">{r.name}</td>
                    {cols.map((c, j) => {
                      const value = r.stats[j] ?? ''
                      const isTD = ['TD', 'TDS'].includes((c || '').toUpperCase()) && parseInt(value) > 0
                      return (
                        <td key={j} className={`py-1 pl-2 sm:pl-3 text-right font-mono ${isTD ? 'text-amber-400' : 'text-zinc-300'}`}>
                          {value}
                        </td>
                      )
                    })}
                  </tr>
                ))}
                <tr className="font-semibold text-zinc-100">
                  <td className="sticky left-0 bg-zinc-900 py-1.5 pr-3">{side.team ? `${side.team} total` : 'Total'}</td>
                  {cols.map((c, j) => (
                    <td key={j} className="py-1.5 pl-2 sm:pl-3 text-right font-mono">
                      {columnTotal(c, side.rows.map(r => r.stats[j]))}
                    </td>
                  ))}
                </tr>
              </tbody>
            ))}
          </table>
        </div>
      </section>
    )
  }

  // One table per group, full width, in reading order. Side by side, the tables overflowed the card and their
  // columns could not line up.
  const displayOrder = ['Passing', 'Rushing', 'Receiving', 'Fumbles', 'Defense', 'Interceptions', 'Kick Returns',
                        'Punt Returns', 'Kicking', 'Punting']
  const ordered = [...displayOrder.filter(k => groups[k]), ...Object.keys(groups).filter(k => !displayOrder.includes(k))]
  return (
    <div className="space-y-6">
      {ordered.map(key => renderTable(key, groups[key]))}
    </div>
  )
}
