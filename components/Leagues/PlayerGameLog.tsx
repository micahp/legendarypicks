import { useEffect, useState } from 'react'

interface GameRow {
  week: number | null
  played: boolean
  opponent: string | null
  home?: boolean | null
  team: string | null
  date: string | null
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

/* The league-aware profile endpoint — /api/player/{id} — serves recent games
   for every league. Non-NFL leagues have no dedicated game-log endpoint
   (backend gap, see below), so the log surface is built from this. */
interface LeagueProfileResponse {
  season: number | null
  league?: string | null
  recent_games?: Array<{
    date: string | null
    opponent: string | null
    home?: boolean | null
    game_no: string | number | null
    stats: Record<string, number | null>
  }>
  regular_season_games?: number | null
  coverage?: { game_logs?: boolean }
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
  /* NFL: the team's own published game count. Non-NFL: null — the profile
     endpoint does not publish a team-game count, and the N-of-M rate line
     must not render from a made-up M. A future generic game-log endpoint
     can fill this and the rate line turns on by itself. */
  team_games: number | null
  games_played: number | null
  games: GameRow[]
  /* Non-NFL: total regular-season appearances from the profile count, which
     can exceed the 25-row page the profile returns. */
  played_total?: number | null
  league?: string
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
  /* Soccer (MLS, and whatever inherits the soccer scaffold): the per-match
     stat line. `minutes` is only rendered when the data carries it — it is
     the honest denominator for a substitute appearance, and the ingest does
     not publish it yet. */
  goals: 'G', assists: 'A', shots: 'Sh', sot: 'SOT', minutes: 'Min',
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
  'goals', 'assists', 'shots', 'sot', 'minutes',
])

/* Soccer logs are always the same four columns plus minutes when present. */
const SOCCER_FIELDS = ['goals', 'assists', 'shots', 'sot']

/* NCAAF logs carry the offensive line. The shared HEAD map would render two
   columns both labelled "Yds" (rush_yds and rec_yds) and two labelled "TD" —
   fine inside NFL's per-tab tables, wrong in one flat college table. */
const NCAAF_FIELDS = [
  'att', 'pass_yds', 'pass_td', 'intc', 'rush_yds', 'rush_td',
  'rec', 'rec_yds', 'rec_td',
]
const NCAAF_HEAD: Record<string, string> = {
  att: 'Att', pass_yds: 'PaYd', pass_td: 'PaTD', intc: 'INT',
  rush_yds: 'RuYd', rush_td: 'RuTD', rec: 'Rec', rec_yds: 'ReYd',
  rec_td: 'ReTD',
}

const LEAGUE_LABEL: Record<string, string> = { mls: 'MLS', ncaaf: 'NCAAF' }
const MATCH_NOUN: Record<string, string> = { mls: 'matches' }

function columnFor(league: string, field: string): string {
  if (league === 'ncaaf') return NCAAF_HEAD[field] ?? HEAD[field] ?? field
  return HEAD[field] ?? field
}

function cell(field: string, value: number | null) {
  if (value == null) return <span className="text-zinc-700">—</span>
  if (RATIO.has(field)) return `${(value * 100).toFixed(0)}%`
  if (INTEGER.has(field)) return String(value)
  return value.toFixed(1)
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(`${value}T00:00:00`)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

/* Non-NFL log surface: one row per game the player has a published line for.
   Every row is a played row — a substitute appearance is an appearance, and
   there is no week concept to render as an absence. Rows arrive newest-first
   (recent_games is a page of the latest 25) and are reversed to read
   chronologically, matching the NFL table. */
function leagueLog(profile: LeagueProfileResponse, league: string, playerId: number): GameLogResponse {
  const rows: GameRow[] = (profile.recent_games ?? []).slice().reverse().map(game => ({
    week: null,
    played: true,
    opponent: game.opponent ?? null,
    home: game.home ?? null,
    team: null,
    date: game.date ?? null,
    stats: game.stats ?? {},
  }))
  return {
    contract: 'league-player-game-log-v1',
    player_id: playerId,
    name: '',
    position: '',
    reference_season: profile.season ?? 0,
    anchor: null,
    tabs: [],
    fields: [],
    team_games: null,
    games_played: rows.length,
    played_total: profile.regular_season_games ?? rows.length,
    games: rows,
    league,
    unavailable:
      !profile.coverage?.game_logs && rows.length === 0
        ? 'No game log for the last completed season.'
        : undefined,
  }
}

/* Columns the league's logs actually carry — declared from the keys, per
   NEW-LEAGUE-CHECKLIST §4. A substitute appearance is a played row; minutes
   is the honest denominator and is shown only when the data has it. */
function leagueStatFields(league: string, games: GameRow[]): string[] {
  if (league === 'mls') {
    const hasMinutes = games.some(
      game => game.stats['minutes'] != null || game.stats['min'] != null,
    )
    return hasMinutes ? [...SOCCER_FIELDS, 'minutes'] : [...SOCCER_FIELDS]
  }
  if (league === 'ncaaf') {
    const present = new Set<string>()
    for (const game of games) {
      for (const key of Object.keys(game.stats)) {
        if (NCAAF_FIELDS.includes(key)) present.add(key)
      }
    }
    return NCAAF_FIELDS.filter(field => present.has(field))
  }
  return []
}

/**
 * The per-game log — the research half of the player overlay.
 *
 * League-aware: the NFL surface (default) renders one row per week the
 * player's TEAM played, not one row per game he appeared in — a log that
 * lists only appearances makes a 12-game season read like a full one. Weeks
 * he missed are rows, and they carry the accent, per honest-data-ui §5: the
 * colour marks absence, never achievement.
 *
 * Soccer (mls) and NCAAF have no dedicated game-log endpoint yet (backend
 * gap: nfl_mock_draft.py owns the only one, /api/nfl/draft/player/{id}/
 * game-log). Their surface is built from the league-aware profile endpoint,
 * which serves recent games for every league. Every row is a played row — a
 * substitute appearance is not an absence — and the rate line renders only
 * when the team's own game count is published (NFL today, NCAAF when the
 * backend supplies it); an unknown denominator never produces a fraction.
 *
 * The width fix is ESPN's segmented control: one narrow table per tab. Wk,
 * Opp and the points anchor repeat in every tab; only the stat columns
 * change, and no tab declares more than five of them, so the widest view is
 * eight columns and nothing needs the horizontal scrollbar.
 */
export default function PlayerGameLog({ playerId, league = 'nfl' }: { playerId: number; league?: string }) {
  const [data, setData] = useState<GameLogResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<string | null>(null)
  const isNfl = league === 'nfl'

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    // A stale index on a QB after viewing a WR is the obvious bug here; reset
    // on every player change and let the render fall back to the first tab.
    setActiveTab(null)

    if (isNfl) {
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
                const scheduled = schedule.get(game.week ?? -1)
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
    } else {
      fetch(`/api/player/${playerId}`)
        .then(r => {
          if (!r.ok) throw new Error(`Failed to load player (${r.status})`)
          return r.json()
        })
        .then((profile: LeagueProfileResponse) => {
          if (!cancelled) setData(leagueLog(profile, league, playerId))
        })
        .catch(e => { if (!cancelled) setError(e.message) })
    }

    return () => { cancelled = true }
  }, [playerId, league, isNfl])

  if (error) return <p className="px-1 py-3 text-sm text-red-400">{error}</p>
  if (!data) {
    // Component-signature skeleton: the header line plus the table rows it
    // will become, never a silent null.
    return (
      <div className="space-y-1.5 py-2" role="status" aria-label="Loading game log">
        <div className="mb-3 h-3 w-40 animate-pulse rounded bg-zinc-800" />
        {[0, 1, 2, 3, 4].map(i => <div key={i} className="h-6 animate-pulse rounded bg-zinc-800" />)}
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

  const missed = data.team_games != null ? data.team_games - (data.games_played ?? 0) : 0
  const sample = data.games.length
  const truncated = data.played_total != null && sample < data.played_total
  const noun = MATCH_NOUN[league] ?? 'games'

  // A response from before tabs shipped is a single implicit table.
  const tabs = league === 'nfl' && data.tabs && data.tabs.length > 0
    ? data.tabs
    : [{ id: 'all', label: 'All', fields: data.fields }]
  const anchor = league === 'nfl' ? (data.anchor ?? null) : null
  const activeId = activeTab ?? tabs[0]?.id ?? null
  const active = tabs.find(t => t.id === activeId) ?? tabs[0]
  const statFields = league === 'nfl'
    ? (active ? active.fields : [])
    : leagueStatFields(league, data.games)
  // Date (non-NFL) or Wk (NFL) + Opp + anchor + the tab's fields.
  const missColSpan = 1 + (league === 'nfl' ? 0 : 1) + (anchor != null ? 1 : 0) + statFields.length

  return (
    <div>
      <p className="mb-2 text-[11px] text-zinc-500">
        {data.reference_season} {LEAGUE_LABEL[league] ?? ''} regular season ·{' '}
        {data.team_games != null ? (
          <>
            <span className="tabular-nums">{data.games_played}</span> of{' '}
            <span className="tabular-nums">{data.team_games}</span> team games
            {missed > 0 && (
              <span className="text-amber-400"> · missed {missed}</span>
            )}
          </>
        ) : truncated ? (
          <>
            last <span className="tabular-nums">{sample}</span> of{' '}
            <span className="tabular-nums">{data.played_total}</span> {noun}
          </>
        ) : (
          <>
            <span className="tabular-nums">{data.played_total ?? sample}</span> {noun}
          </>
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
              {league === 'nfl' ? (
                <th className="py-1.5 pr-2 text-left font-medium">Wk</th>
              ) : (
                <th className="py-1.5 pr-2 text-left font-medium whitespace-nowrap">Date</th>
              )}
              <th className="py-1.5 pr-2 text-left font-medium min-w-[5rem] whitespace-nowrap">Opp</th>
              {anchor != null && (
                <th className="py-1.5 px-1.5 text-right font-medium">
                  {HEAD[anchor] ?? anchor}
                </th>
              )}
              {statFields.map(f => (
                <th key={f} className="py-1.5 px-1.5 text-right font-medium">
                  {columnFor(league, f)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.games.map((g, i) => (
              <tr
                key={g.week ?? `${g.date ?? 'row'}-${i}`}
                className={`border-b border-zinc-800/40 ${g.played ? '' : 'bg-amber-500/5'}`}
              >
                {league === 'nfl' ? (
                  <td className="py-1.5 pr-2 tabular-nums text-zinc-500">{g.week}</td>
                ) : (
                  <td className="py-1.5 pr-2 whitespace-nowrap tabular-nums text-zinc-500">
                    {formatDate(g.date)}
                  </td>
                )}
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
