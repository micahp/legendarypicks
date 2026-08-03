import { useEffect, useState } from 'react'

interface GameRow {
  week: number
  played: boolean
  opponent: string | null
  home?: boolean | null
  team: string | null
  stats: Record<string, number | null>
}

interface LogTab {
  id: string
  label: string
  fields: string[]
}

interface ProfileScheduleResponse {
  season: number | null
  nfl_schedule_games?: Array<{
    week: number
    phase: 'regular' | 'postseason' | 'preseason'
    opponent: string
    home: boolean
  }>
}

interface GameLogResponse {
  contract: string
  player_id: number
  name: string
  position: string
  reference_season: number
  anchor: string | null
  tabs: LogTab[]
  fields: string[]
  team_games: number
  games_played: number
  games: GameRow[]
  unavailable?: string
}

/* Column headers keyed by the field names the endpoint publishes. Short on
   purpose — a research table is read by scanning columns, and a header long
   enough to wrap costs more than the word it saved. */
const HEAD: Record<string, string> = {
  off_pct: 'Snap', targets: 'Tgt', target_share: 'Tgt%', rec: 'Rec',
  rec_yds: 'Yds', rec_td: 'TD', adot: 'aDOT', separation: 'Sep',
  fpts_ppr: 'PPR', xfpts_ppr: 'xPPR', carries: 'Car', rush_yds: 'Yds',
  rush_td: 'TD', cmp: 'Comp', att: 'Att', pass_yds: 'PaYd',
  pass_td: 'PaTD', intc: 'INT', fg_made: 'FGM', fg_att: 'FGA',
  fg_long: 'Long', pat_made: 'XPM', pat_att: 'XPA', sacks: 'Sk',
  interceptions: 'INT', tds: 'TD', safeties: 'Sfty', fumble_rec: 'FR',
  points_allowed: 'PA', fantasy_pts: 'Pts',
  /* `sacks` above is the D/ST column and means sacks recorded. This one is a
     quarterback's sacks taken — opposite sign, same word, so it gets its own
     field name and shares only the abbreviation ESPN uses. */
  sacks_taken: 'Sk', fum_lost: 'FL', misc_td: 'mTD',
}

/* Fields that arrive as a 0–1 ratio and must be rendered as a percentage.
   Getting this wrong prints "0.4" for a 39% target share. */
const RATIO = new Set(['off_pct', 'target_share'])
/* Fields that are counts, not rates — no decimal place. */
const INTEGER = new Set([
  'targets', 'rec', 'rec_yds', 'rec_td', 'carries', 'rush_yds', 'rush_td',
  'cmp', 'att', 'pass_yds', 'pass_td', 'intc', 'fg_made', 'fg_att', 'fg_long',
  'pat_made', 'pat_att', 'tds', 'safeties', 'fumble_rec', 'points_allowed',
  'interceptions', 'sacks_taken', 'fum_lost', 'misc_td',
])

function cell(field: string, value: number | null) {
  if (value == null) return <span className="text-zinc-700">—</span>
  if (RATIO.has(field)) return `${(value * 100).toFixed(0)}%`
  if (INTEGER.has(field)) return String(value)
  return value.toFixed(1)
}

/**
 * The per-game log — the research half of the player overlay.
 *
 * The defining choice: this renders one row per week the player's TEAM played,
 * not one row per game he appeared in. A log that lists only appearances makes
 * a 12-game season read like a full one, which is the same flattering-average
 * problem the availability work exists to fix — except worse, because a table
 * feels like a complete record. Weeks he missed are rows, and they carry the
 * accent, per honest-data-ui §5: the colour marks absence, never achievement.
 *
 * The width fix is ESPN's segmented control: one narrow table per tab. Wk, Opp
 * and the points anchor repeat in every tab; only the stat columns change, and
 * no tab declares more than five of them, so the widest view is eight columns
 * and nothing needs the horizontal scrollbar.
 */
export default function PlayerGameLog({ playerId }: { playerId: number }) {
  const [data, setData] = useState<GameLogResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    // A stale index on a QB after viewing a WR is the obvious bug here; reset
    // on every player change and let the render fall back to the first tab.
    setActiveTab(null)
    Promise.all([
      fetch(`/api/nfl/draft/player/${playerId}/game-log`)
        .then(r => { if (!r.ok) throw new Error(`Failed to load game log (${r.status})`); return r.json() }),
      fetch(`/api/player/${playerId}`)
        .then(r => r.ok ? r.json() : null)
        .catch(() => null),
    ])
      .then(([d, profile]: [GameLogResponse, ProfileScheduleResponse | null]) => {
        if (profile?.season === d.reference_season) {
          const schedule = new Map(
            (profile.nfl_schedule_games ?? [])
              .filter(game => game.phase === 'regular')
              .map(game => [game.week, game]),
          )
          d = {
            ...d,
            games: d.games.map(game => {
              const scheduled = schedule.get(game.week)
              return scheduled ? {
                ...game,
                opponent: scheduled.opponent,
                home: scheduled.home,
              } : game
            }),
          }
        }
        if (!cancelled) setData(d)
      })
      .catch(e => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }, [playerId])

  if (error) return <p className="px-1 py-3 text-sm text-red-400">{error}</p>
  if (!data) {
    return (
      <div className="space-y-1.5 py-2 animate-pulse">
        {[0, 1, 2, 3, 4].map(i => <div key={i} className="h-6 rounded bg-zinc-800" />)}
      </div>
    )
  }
  if (data.unavailable || data.games.length === 0) {
    return (
      <p className="px-1 py-3 text-sm text-zinc-500">
        {data.unavailable ?? 'No game log for the last completed season.'}
      </p>
    )
  }

  const missed = data.team_games - data.games_played

  // A response from before tabs shipped is a single implicit table.
  const tabs = data.tabs && data.tabs.length > 0
    ? data.tabs
    : [{ id: 'all', label: 'All', fields: data.fields }]
  const anchor = data.anchor ?? null
  const activeId = activeTab ?? tabs[0]?.id ?? null
  const active = tabs.find(t => t.id === activeId) ?? tabs[0]
  const statFields = active ? active.fields : []
  // Opp + anchor + the tab's fields; the Wk cell sits outside the span.
  const missColSpan = 1 + (anchor != null ? 1 : 0) + statFields.length

  return (
    <div>
      <p className="mb-2 text-[11px] text-zinc-500">
        {data.reference_season} regular season ·{' '}
        <span className="tabular-nums">{data.games_played}</span> of{' '}
        <span className="tabular-nums">{data.team_games}</span> team games
        {missed > 0 && (
          <span className="text-amber-400"> · missed {missed}</span>
        )}
      </p>

      {tabs.length > 1 && (
        <div
          role="tablist"
          aria-label="Game log stats"
          className="mb-2 inline-flex gap-0.5 rounded-lg bg-zinc-800 p-0.5"
        >
          {tabs.map(t => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={t.id === activeId}
              onClick={() => setActiveTab(t.id)}
              className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
                t.id === activeId
                  ? 'bg-zinc-600 text-zinc-100'
                  : 'text-zinc-400 hover:text-zinc-300'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-500 uppercase tracking-wider">
              <th className="py-1.5 pr-2 text-left font-medium">Wk</th>
              <th className="py-1.5 pr-2 text-left font-medium min-w-[5rem] whitespace-nowrap">Opp</th>
              {anchor != null && (
                <th className="py-1.5 px-1.5 text-right font-medium">
                  {HEAD[anchor] ?? anchor}
                </th>
              )}
              {statFields.map(f => (
                <th key={f} className="py-1.5 px-1.5 text-right font-medium">
                  {HEAD[f] ?? f}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.games.map(g => (
              <tr
                key={g.week}
                className={`border-b border-zinc-800/40 ${g.played ? '' : 'bg-amber-500/5'}`}
              >
                <td className="py-1.5 pr-2 tabular-nums text-zinc-500">{g.week}</td>
                {g.played ? (
                  <>
                    <td className="py-1.5 pr-2 text-zinc-500 min-w-[5rem] whitespace-nowrap">
                      {g.opponent ? `${g.home === false ? '@ ' : ''}${g.opponent}` : '—'}
                    </td>
                    {anchor != null && (
                      <td className="py-1.5 px-1.5 text-right font-mono tabular-nums text-zinc-300">
                        {cell(anchor, g.stats[anchor] ?? null)}
                      </td>
                    )}
                    {statFields.map(f => (
                      <td key={f} className="py-1.5 px-1.5 text-right font-mono tabular-nums text-zinc-300">
                        {cell(f, g.stats[f] ?? null)}
                      </td>
                    ))}
                  </>
                ) : (
                  <td
                    colSpan={missColSpan}
                    className="py-1.5 text-center whitespace-nowrap text-amber-400"
                  >
                    did not play
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
