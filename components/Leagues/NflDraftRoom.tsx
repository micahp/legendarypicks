import { useCallback, useEffect, useMemo, useState } from 'react'
import type { MockDraftPick, MockDraftPool, PlayerDetailResponse, PoolPlayer } from './types'

// ── constants ──────────────────────────────────────────────────────────────

const POOL_POSITIONS = ['ALL', 'QB', 'RB', 'WR', 'TE', 'PK'] as const
type PoolPosition = typeof POOL_POSITIONS[number]

const ROSTER_SLOTS = ['QB', 'RB1', 'RB2', 'WR1', 'WR2', 'TE', 'FLEX'] as const
const BENCH_COUNT = 8

const NFL_TEAMS: Record<string, string> = {
  ARI: 'Cardinals', ATL: 'Falcons', BAL: 'Ravens', BUF: 'Bills',
  CAR: 'Panthers', CHI: 'Bears', CIN: 'Bengals', CLE: 'Browns',
  DAL: 'Cowboys', DEN: 'Broncos', DET: 'Lions', GB: 'Packers',
  HOU: 'Texans', IND: 'Colts', JAX: 'Jaguars', KC: 'Chiefs',
  LAC: 'Chargers', LAR: 'Rams', LV: 'Raiders', MIA: 'Dolphins',
  MIN: 'Vikings', NE: 'Patriots', NO: 'Saints', NYG: 'Giants',
  NYJ: 'Jets', PHI: 'Eagles', PIT: 'Steelers', SEA: 'Seahawks',
  SF: '49ers', TB: 'Buccaneers', TEN: 'Titans', WAS: 'Commanders',
}

const BYE_WEEKS = [5, 6, 7, 8, 9, 10, 11, 12, 13, 14] as const

interface RosterSlot {
  playerId: number | null
  playerName?: string
  playerPos?: string
}

// ── hook ───────────────────────────────────────────────────────────────────

function useMockDraftRoom() {
  const [pool, setPool] = useState<MockDraftPool | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Filters
  const [posFilter, setPosFilter] = useState<PoolPosition>('ALL')
  const [teamFilter, setTeamFilter] = useState<string>('ALL')
  const [byeFilter, setByeFilter] = useState<number | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  // Draft state
  const [picks, setPicks] = useState<MockDraftPick[]>([])
  const seatNumber = 7 // default middle seat in a 12-team draft
  const teams = 12
  const rounds = 15

  // Roster
  const [roster, setRoster] = useState<Record<string, RosterSlot>>(() => {
    const initial: Record<string, RosterSlot> = {}
    for (const slot of ROSTER_SLOTS) {
      initial[slot] = { playerId: null }
    }
    for (let i = 0; i < BENCH_COUNT; i++) {
      initial[`BENCH_${i}`] = { playerId: null }
    }
    return initial
  })

  // Player detail overlay
  const [detailPlayer, setDetailPlayer] = useState<PlayerDetailResponse | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // Clock (60 seconds per pick, simulated)
  const [clockEnd, setClockEnd] = useState<number | null>(null)
  const [clockRemaining, setClockRemaining] = useState(60)

  // ── fetch pool ──
  useEffect(() => {
    let ignore = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await fetch('/api/nfl/mock-draft/pool?season=2026')
        if (!res.ok) {
          if (!ignore) setError(`Pool unavailable (${res.status})`)
          return
        }
        const json = await res.json()
        if (!ignore) setPool(json)
      } catch {
        if (!ignore) setError('Unable to load player pool.')
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [])

  // ── clock tick ──
  useEffect(() => {
    if (clockEnd === null) return
    const tick = () => {
      const remaining = Math.max(0, Math.ceil((clockEnd - Date.now()) / 1000))
      setClockRemaining(remaining)
      if (remaining <= 0) {
        setClockEnd(null)
      }
    }
    tick()
    const interval = setInterval(tick, 250)
    return () => clearInterval(interval)
  }, [clockEnd])

  const startClock = useCallback(() => {
    setClockEnd(Date.now() + 60000)
    setClockRemaining(60)
  }, [])

  // ── filtered players ──
  const filteredPlayers = useMemo(() => {
    if (!pool) return []
    let result = pool.players

    if (posFilter !== 'ALL') {
      result = result.filter(p => p.position === posFilter)
    }
    if (teamFilter !== 'ALL') {
      result = result.filter(p => p.team === teamFilter)
    }
    if (byeFilter !== null) {
      // Bye week filter: exclude players whose team plays that week
      // (team_weeks includes all weeks the team plays; if byeFilter is not in team_weeks, it's their bye)
      result = result.filter(p => !p.team_weeks.includes(byeFilter))
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase()
      result = result.filter(p => p.name.toLowerCase().includes(q))
    }

    return result
  }, [pool, posFilter, teamFilter, byeFilter, searchQuery])

  // ── current round / pick ──
  const totalPicks = picks.length
  const currentRound = Math.floor(totalPicks / teams) + 1
  const remainder = totalPicks % teams
  const currentPickInRound = remainder === 0 ? teams : remainder

  // Is it the user's turn?
  const isMyTurn = currentPickInRound === seatNumber

  // ── next 3 upcoming picks ──
  const upcomingPicks = useMemo(() => {
    const result: { round: number; pick: number; team: number }[] = []
    let r = currentRound
    let p = currentPickInRound
    for (let i = 0; i < 3; i++) {
      p++
      if (p > teams) {
        p = 1
        r++
      }
      result.push({ round: r, pick: p, team: p })
    }
    return result
  }, [currentRound, currentPickInRound, teams])

  // ── draft board grid: teams × rounds ──
  const draftGrid = useMemo(() => {
    // Build a map of (round, pick) → player name
    const pickMap: Record<string, string> = {}
    for (const pick of picks) {
      const r = Math.floor((pick.pick_no - 1) / teams) + 1
      const tp = ((pick.pick_no - 1) % teams) + 1
      pickMap[`${r}-${tp}`] = pick.player_name || `#${pick.player_id}`
    }
    return pickMap
  }, [picks, teams])

  // ── draft a player ──
  const draftPlayer = useCallback((player: PoolPlayer) => {
    const pickNo = totalPicks + 1
    const teamNo = ((pickNo - 1) % teams) + 1
    const newPick: MockDraftPick = {
      pick_no: pickNo,
      team_no: teamNo,
      player_id: player.player_id,
      player_name: player.name,
      player_position: player.position,
      player_team: player.team,
      auto: false,
      created_at: Date.now(),
    }
    setPicks(prev => [...prev, newPick])

    // If it's the user's pick, add to roster
    if (teamNo === seatNumber) {
      setRoster(prev => {
        const next = { ...prev }
        // Find first empty slot
        for (const slot of ROSTER_SLOTS) {
          if (next[slot]?.playerId === null) {
            next[slot] = { playerId: player.player_id, playerName: player.name, playerPos: player.position }
            return next
          }
        }
        // Fall into bench
        for (let i = 0; i < BENCH_COUNT; i++) {
          const key = `BENCH_${i}`
          if (next[key]?.playerId === null) {
            next[key] = { playerId: player.player_id, playerName: player.name, playerPos: player.position }
            break
          }
        }
        return next
      })
    }

    startClock()
  }, [totalPicks, teams, seatNumber, startClock])

  // ── player detail ──
  const openPlayerDetail = useCallback(async (playerId: number) => {
    setDetailLoading(true)
    setDetailPlayer(null)
    try {
      const res = await fetch(`/api/nfl/draft/player/${playerId}`)
      if (res.ok) {
        const json = await res.json()
        setDetailPlayer(json)
      }
    } catch {
      // silently fail
    } finally {
      setDetailLoading(false)
    }
  }, [])

  const closePlayerDetail = useCallback(() => {
    setDetailPlayer(null)
  }, [])

  // ── unique teams from pool for team filter ──
  const availableTeams = useMemo(() => {
    if (!pool) return []
    const teamSet = new Set(pool.players.map(p => p.team))
    return Array.from(teamSet).sort()
  }, [pool])

  return {
    pool,
    loading,
    error,
    posFilter,
    teamFilter,
    byeFilter,
    searchQuery,
    setPosFilter,
    setTeamFilter,
    setByeFilter,
    setSearchQuery,
    filteredPlayers,
    picks,
    totalPicks,
    currentRound,
    currentPickInRound,
    isMyTurn,
    seatNumber,
    teams,
    rounds,
    upcomingPicks,
    draftGrid,
    roster,
    clockRemaining,
    detailPlayer,
    detailLoading,
    draftPlayer,
    openPlayerDetail,
    closePlayerDetail,
    availableTeams,
  }
}

// ── component ──────────────────────────────────────────────────────────────

interface Props {
  enabled: boolean
}

export default function NflDraftRoom({ enabled }: Props) {
  const room = useMockDraftRoom()

  if (!enabled) {
    return (
      <div className="text-center py-12 text-zinc-500 text-sm">
        Draft room inactive.
      </div>
    )
  }

  if (room.loading) {
    return (
      <div className="space-y-3 animate-pulse">
        {[0, 1, 2].map(i => (
          <div key={i} className="h-32 rounded-xl bg-zinc-800" />
        ))}
      </div>
    )
  }

  if (room.error) {
    return (
      <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400">
        {room.error}
      </div>
    )
  }

  return (
    <section className="space-y-3">
      {/* ── Filters bar ── */}
      <FiltersBar
        posFilter={room.posFilter}
        teamFilter={room.teamFilter}
        byeFilter={room.byeFilter}
        searchQuery={room.searchQuery}
        availableTeams={room.availableTeams}
        onPositionChange={room.setPosFilter}
        onTeamChange={room.setTeamFilter}
        onByeChange={room.setByeFilter}
        onSearchChange={room.setSearchQuery}
      />

      {/* ── Draft status: round/pick + clock ── */}
      <DraftStatus
        currentRound={room.currentRound}
        currentPick={room.currentPickInRound}
        seatNumber={room.seatNumber}
        isMyTurn={room.isMyTurn}
        clockRemaining={room.clockRemaining}
        totalPicks={room.totalPicks}
      />

      {/* ── 3-panel layout ── */}
      <div className="grid grid-cols-12 gap-3 min-h-0">
        {/* Left: Pick Queue + Draft Grid */}
        <div className="col-span-3 space-y-3">
          <PickQueue
            upcomingPicks={room.upcomingPicks}
            currentRound={room.currentRound}
            currentPick={room.currentPickInRound}
            seatNumber={room.seatNumber}
          />
          <DraftGrid
            grid={room.draftGrid}
            teams={room.teams}
            rounds={Math.min(room.rounds, 6)} // show first 6 rounds in grid
            seatNumber={room.seatNumber}
          />
        </div>

        {/* Center: Player Pool */}
        <div className="col-span-6">
          <PlayerPool
            players={room.filteredPlayers}
            draftedPlayerIds={new Set(room.picks.map(p => p.player_id))}
            onDraft={room.draftPlayer}
            onDetail={room.openPlayerDetail}
          />
        </div>

        {/* Right: Roster */}
        <div className="col-span-3">
          <RosterPanel
            roster={room.roster}
            seatNumber={room.seatNumber}
            totalPicks={room.totalPicks}
          />
        </div>
      </div>

      {/* ── Player Detail Overlay (M5) ── */}
      {(room.detailPlayer || room.detailLoading) && (
        <PlayerDetailOverlay
          player={room.detailPlayer}
          loading={room.detailLoading}
          onClose={room.closePlayerDetail}
        />
      )}
    </section>
  )
}

// ── sub-components ─────────────────────────────────────────────────────────

function FiltersBar({
  posFilter,
  teamFilter,
  byeFilter,
  searchQuery,
  availableTeams,
  onPositionChange,
  onTeamChange,
  onByeChange,
  onSearchChange,
}: {
  posFilter: PoolPosition
  teamFilter: string
  byeFilter: number | null
  searchQuery: string
  availableTeams: string[]
  onPositionChange: (p: PoolPosition) => void
  onTeamChange: (t: string) => void
  onByeChange: (w: number | null) => void
  onSearchChange: (q: string) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-3">
      {/* Position filter */}
      <div className="flex items-center gap-1">
        <span className="text-[11px] font-medium text-zinc-500 mr-1">Pos:</span>
        {POOL_POSITIONS.map(pos => (
          <button
            key={pos}
            type="button"
            onClick={() => onPositionChange(pos)}
            className={`rounded-md border px-2 py-0.5 text-[11px] font-semibold uppercase transition-colors ${
              posFilter === pos
                ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                : 'border-zinc-700/50 bg-zinc-800/40 text-zinc-500 hover:border-zinc-600 hover:text-zinc-300'
            }`}
          >
            {pos}
          </button>
        ))}
      </div>

      {/* Team filter */}
      <div className="flex items-center gap-1">
        <span className="text-[11px] font-medium text-zinc-500 mr-1">Team:</span>
        <select
          value={teamFilter}
          onChange={e => onTeamChange(e.target.value)}
          className="rounded-md border border-zinc-700/50 bg-zinc-800/40 px-2 py-0.5 text-[11px] font-medium text-zinc-300 focus:border-emerald-500 focus:outline-none"
        >
          <option value="ALL">All</option>
          {availableTeams.map(t => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      {/* Bye week filter */}
      <div className="flex items-center gap-1">
        <span className="text-[11px] font-medium text-zinc-500 mr-1">Bye:</span>
        <select
          value={byeFilter ?? ''}
          onChange={e => onByeChange(e.target.value ? Number(e.target.value) : null)}
          className="rounded-md border border-zinc-700/50 bg-zinc-800/40 px-2 py-0.5 text-[11px] font-medium text-zinc-300 focus:border-emerald-500 focus:outline-none"
        >
          <option value="">All</option>
          {BYE_WEEKS.map(w => (
            <option key={w} value={w}>Week {w}</option>
          ))}
        </select>
      </div>

      {/* Search */}
      <div className="relative ml-auto">
        <input
          type="search"
          value={searchQuery}
          onChange={e => onSearchChange(e.target.value)}
          placeholder="Search players..."
          className="w-40 rounded-md border border-zinc-700 bg-zinc-800/60 py-1 pl-7 pr-2 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        />
        <span className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-xs text-zinc-600">
          ⌕
        </span>
      </div>
    </div>
  )
}

function DraftStatus({
  currentRound,
  currentPick,
  seatNumber,
  isMyTurn,
  clockRemaining,
  totalPicks,
}: {
  currentRound: number
  currentPick: number
  seatNumber: number
  isMyTurn: boolean
  clockRemaining: number
  totalPicks: number
}) {
  const clockMin = Math.floor(clockRemaining / 60)
  const clockSec = clockRemaining % 60
  const clockStr = `${clockMin}:${clockSec.toString().padStart(2, '0')}`

  return (
    <div className="flex items-center gap-4 rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-2 text-sm">
      <div className="flex items-center gap-2">
        <span className="text-zinc-500">Round</span>
        <span className="font-bold text-zinc-100 tabular-nums">{currentRound}</span>
        <span className="text-zinc-600">·</span>
        <span className="text-zinc-500">Pick</span>
        <span className="font-bold text-zinc-100 tabular-nums">{currentPick}</span>
        <span className="text-zinc-600">of {12}</span>
      </div>

      <div className="flex items-center gap-2 border-l border-zinc-800 pl-4">
        <span className="text-zinc-500">Your next:</span>
        <span className={`font-bold tabular-nums ${isMyTurn ? 'text-emerald-400' : 'text-zinc-400'}`}>
          {isMyTurn ? 'ON THE CLOCK' : `Pick ${seatNumber} in round ${currentRound}`}
        </span>
      </div>

      {/* Clock */}
      <div className="flex items-center gap-2 border-l border-zinc-800 pl-4 ml-auto">
        <span className="text-zinc-500">Clock:</span>
        <span className={`font-mono font-bold tabular-nums text-lg ${
          clockRemaining <= 10 ? 'text-red-400' : clockRemaining <= 30 ? 'text-amber-400' : 'text-zinc-200'
        }`}>
          {clockStr}
        </span>
      </div>

      <span className="text-xs text-zinc-600">
        {totalPicks} picks made · {180 - totalPicks} remaining
      </span>
    </div>
  )
}

function PickQueue({
  upcomingPicks,
  currentRound,
  currentPick,
  seatNumber,
}: {
  upcomingPicks: { round: number; pick: number; team: number }[]
  currentRound: number
  currentPick: number
  seatNumber: number
}) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">
        On Deck
      </h4>
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs py-1.5 px-2 rounded bg-emerald-500/10 border border-emerald-500/20">
          <span className="text-zinc-400">Now</span>
          <span className="font-medium text-emerald-300">
            R{currentRound} · Pick {currentPick}
          </span>
          <span className={`text-xs font-bold ${currentPick === seatNumber ? 'text-white' : 'text-zinc-500'}`}>
            {currentPick === seatNumber ? 'YOU' : `Team ${currentPick}`}
          </span>
        </div>
        {upcomingPicks.map((up, i) => (
          <div
            key={i}
            className="flex items-center justify-between text-xs py-1.5 px-2 rounded bg-zinc-800/40"
          >
            <span className="text-zinc-600">Next</span>
            <span className="text-zinc-500">
              R{up.round} · Pick {up.pick}
            </span>
            <span className={`text-xs font-bold ${up.team === seatNumber ? 'text-white' : 'text-zinc-500'}`}>
              {up.team === seatNumber ? 'YOU' : `Team ${up.team}`}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function DraftGrid({
  grid,
  teams,
  rounds,
  seatNumber,
}: {
  grid: Record<string, string>
  teams: number
  rounds: number
  seatNumber: number
}) {
  const roundHeaders = Array.from({ length: rounds }, (_, i) => i + 1)
  const teamHeaders = Array.from({ length: teams }, (_, i) => i + 1)

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 overflow-x-auto">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">
        Draft Board
      </h4>
      <table className="w-full text-[10px]">
        <thead>
          <tr>
            <th className="text-left py-1 pr-1 text-zinc-600 font-medium">Tm</th>
            {roundHeaders.map(r => (
              <th key={r} className="text-center px-0.5 py-1 text-zinc-600 font-medium">
                R{r}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {teamHeaders.map(team => (
            <tr key={team} className={team === seatNumber ? 'bg-emerald-500/5' : ''}>
              <td className={`py-0.5 pr-1 font-bold ${
                team === seatNumber ? 'text-emerald-400' : 'text-zinc-500'
              }`}>
                {team === seatNumber ? 'YOU' : `T${team}`}
              </td>
              {roundHeaders.map(r => {
                const key = `${r}-${team}`
                const player = grid[key]
                return (
                  <td
                    key={r}
                    className={`text-center px-0.5 py-0.5 ${
                      player
                        ? team === seatNumber
                          ? 'text-emerald-300 font-medium'
                          : 'text-zinc-400'
                        : team === seatNumber
                          ? 'text-zinc-700'
                          : 'text-zinc-800'
                    }`}
                    title={player || undefined}
                  >
                    {player ? '●' : '·'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PlayerPool({
  players,
  draftedPlayerIds,
  onDraft,
  onDetail,
}: {
  players: PoolPlayer[]
  draftedPlayerIds: Set<number>
  onDraft: (player: PoolPlayer) => void
  onDetail: (playerId: number) => void
}) {
  if (players.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-12 text-center">
        <p className="text-sm text-zinc-500">No players match these filters.</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Best Available
        </h4>
        <span className="text-[11px] text-zinc-600 tabular-nums">
          {players.length} players
        </span>
      </div>
      {/* M7#1: scrollbar visible — no [scrollbar-width:none] */}
      <div className="overflow-y-auto" style={{ maxHeight: 'calc(100vh - 380px)' }}>
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-zinc-900/95 backdrop-blur-sm">
            <tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
              <th className="text-left py-2 pl-4 pr-2 w-8">#</th>
              <th className="text-left py-2 px-2">Player</th>
              <th className="text-center py-2 px-2 w-12">Pos</th>
              <th className="text-center py-2 px-2 w-14">Team</th>
              <th className="text-right py-2 px-2 w-16">ADP</th>
              <th className="text-center py-2 px-2 w-20">Avail</th>
              <th className="text-center py-2 pr-4 pl-2 w-14">Pick</th>
            </tr>
          </thead>
          <tbody>
            {players.map((player, i) => {
              const drafted = draftedPlayerIds.has(player.player_id)
              return (
                <tr
                  key={player.player_id}
                  className={`border-b border-zinc-800/50 transition-colors ${
                    drafted
                      ? 'bg-zinc-800/20 opacity-40'
                      : 'hover:bg-zinc-800/30 cursor-pointer'
                  }`}
                  onClick={() => {
                    if (!drafted) onDetail(player.player_id)
                  }}
                >
                  <td className="py-1.5 pl-4 pr-2 text-zinc-600 text-xs tabular-nums">
                    {i + 1}
                  </td>
                  <td className="py-1.5 px-2">
                    <span className={`font-medium ${drafted ? 'text-zinc-600 line-through' : 'text-zinc-200'}`}>
                      {player.name}
                    </span>
                  </td>
                  <td className="py-1.5 px-2 text-center">
                    <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-zinc-400">
                      {player.position}
                    </span>
                  </td>
                  <td className="py-1.5 px-2 text-center">
                    <span className="text-[11px] text-zinc-500">{player.team}</span>
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono tabular-nums text-xs text-zinc-400">
                    {player.adp != null ? player.adp.toFixed(1) : '—'}
                  </td>
                  <td className="py-1.5 px-2">
                    {/* M7#3: use games_missed from API instead of computing */}
                    <AvailabilityCell
                      gamesPlayed={player.games_played}
                      gamesMissed={player.games_missed}
                      weeksPlayed={player.weeks_played}
                      teamWeeks={player.team_weeks}
                      sample={player.sample}
                    />
                  </td>
                  <td className="py-1.5 pr-4 pl-2 text-center">
                    <button
                      type="button"
                      disabled={drafted}
                      onClick={e => {
                        e.stopPropagation()
                        if (!drafted) onDraft(player)
                      }}
                      className={`rounded-md border px-2.5 py-1 text-[11px] font-semibold transition-colors ${
                        drafted
                          ? 'border-zinc-800 bg-zinc-800/40 text-zinc-700 cursor-not-allowed'
                          : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 hover:text-emerald-300'
                      }`}
                    >
                      Draft
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function AvailabilityCell({
  gamesPlayed,
  gamesMissed,
  weeksPlayed,
  teamWeeks,
  sample,
}: {
  gamesPlayed: number
  gamesMissed: number | null
  weeksPlayed: number[]
  teamWeeks: number[]
  sample: string
}) {
  if (sample === 'none') {
    return <span className="text-[11px] text-zinc-500">No data</span>
  }

  const missed = gamesMissed ?? (teamWeeks.length > 0 ? teamWeeks.length - gamesPlayed : null)

  return (
    <div>
      <div className="flex items-baseline gap-1">
        <span className={`font-mono tabular-nums text-xs font-semibold ${
          missed != null && missed > 0 ? 'text-amber-400' : 'text-zinc-300'
        }`}>
          {gamesPlayed}/{teamWeeks.length || 17}
        </span>
        {missed != null && missed > 0 && (
          <span className="text-[10px] text-zinc-600">missed {missed}</span>
        )}
      </div>
      {/* Availability strip */}
      {teamWeeks.length > 0 && (
        <div className="mt-0.5 flex gap-px" role="img">
          {teamWeeks.map(week => {
            const played = weeksPlayed.includes(week)
            return (
              <span
                key={week}
                title={`Week ${week}: ${played ? 'played' : 'did not play'}`}
                className={`h-2 w-[4px] rounded-[1px] ${
                  played ? 'bg-zinc-700' : 'bg-amber-500'
                }`}
              />
            )
          })}
        </div>
      )}
    </div>
  )
}

function RosterPanel({
  roster,
  seatNumber,
  totalPicks,
}: {
  roster: Record<string, RosterSlot>
  seatNumber: number
  totalPicks: number
}) {
  const starters = ROSTER_SLOTS.map(slot => ({
    label: slot,
    ...roster[slot],
  }))

  const bench = Array.from({ length: BENCH_COUNT }, (_, i) => ({
    label: `BENCH_${i}`,
    ...roster[`BENCH_${i}`],
  }))

  const filledStarters = starters.filter(s => s.playerId !== null).length

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Your Roster
        </h4>
        <span className="text-[11px] text-zinc-600">
          Team {seatNumber} · {filledStarters}/7 · {totalPicks} picks
        </span>
      </div>

      {/* Starter slots */}
      <div className="space-y-1 mb-3">
        {starters.map(slot => (
          <div
            key={slot.label}
            className={`flex items-center justify-between rounded-md border px-3 py-1.5 ${
              slot.playerId
                ? 'border-zinc-700 bg-zinc-800/60'
                : 'border-zinc-800 bg-zinc-800/20'
            }`}
          >
            <span className="text-[10px] font-semibold uppercase text-zinc-500 w-8">
              {slot.label.replace(/\d/g, '')}
            </span>
            <span className={`text-xs font-medium ${
              slot.playerId ? 'text-zinc-200' : 'text-zinc-700'
            }`}>
              {slot.playerName || '—'}
            </span>
            <span className={`text-[10px] uppercase ${
              slot.playerId ? 'text-zinc-500' : 'text-zinc-700'
            }`}>
              {slot.playerPos || slot.label.replace(/[^A-Z]/g, '')}
            </span>
          </div>
        ))}
      </div>

      {/* Bench slots — M7#2: reduced height */}
      <div className="border-t border-zinc-800 pt-2">
        <p className="text-[10px] font-medium text-zinc-600 mb-1.5">BENCH</p>
        <div className="space-y-0.5">
          {bench.map(slot => (
            <div
              key={slot.label}
              className={`flex items-center gap-2 rounded px-2 ${
                slot.playerId
                  ? 'py-1 text-zinc-300'
                  : 'py-0.5 text-zinc-700'
              }`}
            >
              <span className={`text-[10px] ${slot.playerId ? 'text-zinc-300' : 'text-zinc-700'}`}>
                {slot.playerName || '—'}
              </span>
              {slot.playerPos && (
                <span className="text-[9px] uppercase text-zinc-600">{slot.playerPos}</span>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── M5: Player Detail Overlay ──────────────────────────────────────────────

function PlayerDetailOverlay({
  player,
  loading,
  onClose,
}: {
  player: PlayerDetailResponse | null
  loading: boolean
  onClose: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg mx-4 rounded-xl border border-zinc-700 bg-zinc-900 shadow-2xl max-h-[85vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        {loading && (
          <div className="p-8 space-y-3 animate-pulse">
            <div className="h-6 w-48 rounded bg-zinc-800" />
            <div className="h-4 w-32 rounded bg-zinc-800" />
            <div className="h-20 rounded bg-zinc-800" />
          </div>
        )}

        {player && (
          <>
            {/* Header */}
            <div className="flex items-center justify-between p-5 pb-3 border-b border-zinc-800">
              <div>
                <h3 className="text-lg font-bold text-zinc-100">{player.name}</h3>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-xs text-zinc-500">{player.team}</span>
                  <span className="text-zinc-700">·</span>
                  <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-zinc-400">
                    {player.position}
                  </span>
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-md p-1.5 text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 transition-colors"
              >
                ✕
              </button>
            </div>

            <div className="p-5 space-y-4">
              {/* ADP + Ownership */}
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-zinc-800 bg-zinc-800/40 px-3 py-2">
                  <p className="text-[10px] font-medium uppercase text-zinc-600">ADP</p>
                  <p className="text-lg font-bold text-zinc-200 tabular-nums">
                    {player.adp != null ? player.adp.toFixed(1) : '—'}
                  </p>
                </div>
                <div className="rounded-lg border border-zinc-800 bg-zinc-800/40 px-3 py-2">
                  <p className="text-[10px] font-medium uppercase text-zinc-600">% Owned</p>
                  <p className="text-lg font-bold text-zinc-200 tabular-nums">
                    {player.percent_owned != null ? `${player.percent_owned.toFixed(1)}%` : '—'}
                  </p>
                </div>
              </div>

              {/* 2025 Stats */}
              <div>
                <h4 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600 mb-2">
                  {player.games_played > 0 ? '2025 Season' : 'No 2025 Data'}
                </h4>
                <div className="grid grid-cols-3 gap-2">
                  <StatBadge label="Games" value={player.games_played.toString()} />
                  <StatBadge
                    label="PPR/G"
                    value={player.ppr_per_game_played != null ? player.ppr_per_game_played.toFixed(1) : '—'}
                  />
                  <StatBadge
                    label="Snap%"
                    value={player.snap_pct != null ? `${player.snap_pct.toFixed(0)}%` : '—'}
                  />
                </div>
              </div>

              {/* Game Strip */}
              {player.team_weeks.length > 0 && (
                <div>
                  <h4 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600 mb-1.5">
                    Game Strip
                  </h4>
                  <div className="flex gap-px" role="img">
                    {player.team_weeks.map(week => {
                      const played = player.weeks_played.includes(week)
                      return (
                        <span
                          key={week}
                          title={`Week ${week}: ${played ? 'played' : 'did not play'}`}
                          className={`h-4 w-[6px] rounded-[1px] ${
                            played ? 'bg-zinc-700' : 'bg-amber-500'
                          }`}
                        />
                      )
                    })}
                  </div>
                </div>
              )}

              {/* QB info (M5) */}
              {player.qb && (
                <div className="rounded-lg border border-zinc-800 bg-zinc-800/30 px-3 py-2.5">
                  <p className="text-[10px] font-medium uppercase text-zinc-600 mb-1">
                    Quarterback
                  </p>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-zinc-200">
                      {player.qb.name}
                    </span>
                    <span className="text-[10px] text-zinc-600">
                      {player.qb.games_played} games
                    </span>
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function StatBadge({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-800/40 px-3 py-2 text-center">
      <p className="text-[10px] font-medium uppercase text-zinc-600">{label}</p>
      <p className="text-sm font-bold text-zinc-200 tabular-nums mt-0.5">{value}</p>
    </div>
  )
}

// Re-export for backward compat
export { useMockDraftRoom }
