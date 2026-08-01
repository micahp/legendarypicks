import { useEffect, useMemo, useState, useRef, useCallback } from 'react'
import type { PoolPlayer } from '../Leagues/types'
import { AvailabilityStrip } from '../Leagues/NflDraftRoom'
import PlayerDetailOverlay from '../Leagues/PlayerDetailOverlay'
import InjuryTag from '../Leagues/InjuryTag'
import { poolToDraftRow } from '../../lib/mockDraft/api'
import {
  positionLabel,
  positionRankLabel,
  showsPositionalRank,
} from '../../lib/nfl/positionLabel'
import { LEAGUE_SIZES, ROUNDS, nextTeam } from '../../lib/mockDraft/engine'
import type { LeagueSize } from '../../lib/mockDraft/engine'
import {
  noSampleLabel,
  ProjectedPoints,
} from './columns'

/** 'random' is a real choice, not the absence of one — a drafter who wants to
 *  practise from an unknown slot has to be able to say so. */
export type SeatChoice = number | 'random'

interface Props {
  players: PoolPlayer[]
  /** The season being drafted, used for the published bye/projection labels. */
  draftSeason: number
  /** The season these statistics describe, from the pool payload. */
  referenceSeason?: number | null
  teams: LeagueSize
  onSetTeams: (teams: LeagueSize) => void
  seat: SeatChoice
  onSetSeat: (seat: SeatChoice) => void
  onStartDraft: () => void
}

/** The first few pick numbers a seat owns, so the slot choice is concrete
 *  before the draft starts rather than a number with no consequence. */
function firstPicksForSeat(seat: number, teams: number, howMany = 4): number[] {
  const picks: number[] = []
  for (let p = 1; p <= teams * ROUNDS && picks.length < howMany; p++) {
    if (nextTeam(p, teams) === seat) picks.push(p)
  }
  return picks
}

// Virtualization constants — keep DOM footprint ~25 rows regardless of pool size.
const ROW_HEIGHT = 48       // px: py-2.5 (20px) + text content (~28px)
const OVERSCAN = 10         // rows to render above/below visible window
const CONTAINER_MAX_H = 600 // px: scrollable container height

/**
 * The mock-draft pool list. ~300 players, each row reuses DraftPlayerRow
 * for the availability strip — the differentiator. No note columns (rank,
 * watch, fade) — those live on the research board, not here.
 *
 * sample='none' rendering: per honest-data-ui §6.3:
 *   - PK → "Kicker games not tracked" (our gap, not theirs)
 *   - all else → "Rookie — no NFL sample" (grey, not accent, not zero)
 */
export default function PoolList({
  players,
  draftSeason,
  referenceSeason,
  teams,
  onSetTeams,
  seat,
  onSetSeat,
  onStartDraft,
}: Props) {
  // The pool screen is where someone researches *before* committing to a draft.
  // Until now the only interactive element here was "Start Draft", so the
  // research card was reachable only from inside a draft -- a research surface
  // with no way into the research. Same overlay, same row click as the draft
  // room; the draft/queue actions stay absent because there is no pick to be on.
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null)
  const [schedule, setSchedule] = useState<Array<{ team: string; bye_week: number | null }> | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch(`/api/nfl/schedule/${draftSeason}`)
      .then(response => {
        if (!response.ok) throw new Error(`schedule fetch failed: ${response.status}`)
        return response.json()
      })
      .then(data => { if (!cancelled) setSchedule(data.teams ?? []) })
      .catch(() => { if (!cancelled) setSchedule([]) })
    return () => { cancelled = true }
  }, [draftSeason])

  const byeMap = useMemo(() => {
    const map = new Map<string, number | null>()
    for (const team of schedule ?? []) map.set(team.team, team.bye_week)
    return map
  }, [schedule])
  const rows = useMemo(
    () => players.map((p, i) => poolToDraftRow(p, i + 1)),
    [players],
  )

  const playerMap = useMemo(() => {
    const m = new Map<number, PoolPlayer>()
    for (const p of players) m.set(p.player_id, p)
    return m
  }, [players])

  // Positional rank by ADP — same derivation as the draft room, so "RB4" means
  // the same thing on both screens.
  const posRank = useMemo(() => {
    const byPos = new Map<string, PoolPlayer[]>()
    for (const p of players) {
      const list = byPos.get(p.position)
      if (list) list.push(p)
      else byPos.set(p.position, [p])
    }
    const m = new Map<number, number>()
    for (const list of Array.from(byPos.values())) {
      list
        .filter(p => p.adp != null)
        .sort((a, b) => (a.adp as number) - (b.adp as number))
        .forEach((p, i) => m.set(p.player_id, i + 1))
    }
    return m
  }, [players])

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-xl font-bold text-zinc-100">
            Mock Draft Pool
          </h3>
          <p className="text-sm text-zinc-500 mt-0.5">
            {players.length} players · {teams} teams · {ROUNDS} rounds · PPR
          </p>
        </div>
      </div>

      {/* ── Draft setup ──
          League size and slot were both decided for the drafter: teams was a
          literal 12 in the INSERT and the seat was Math.random(). Neither is a
          detail — a 10-team draft is a different board from a 14-team one, and
          practising from the turn is a different exercise from practising from
          pick 1. */}
      <div
        className="rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-3.5"
        data-testid="draft-setup"
      >
        <div className="flex flex-wrap items-end gap-x-8 gap-y-4">
          <div>
            <label
              className="block text-[11px] font-semibold uppercase tracking-wider text-zinc-500"
              id="league-size-label"
            >
              League size
            </label>
            <div
              className="mt-1.5 flex items-center gap-1.5"
              role="radiogroup"
              aria-labelledby="league-size-label"
            >
              {LEAGUE_SIZES.map(size => (
                <button
                  key={size}
                  type="button"
                  role="radio"
                  aria-checked={teams === size}
                  onClick={() => onSetTeams(size)}
                  className={`rounded-md border px-3 py-1 text-sm font-semibold tabular-nums transition-colors ${
                    teams === size
                      ? 'border-zinc-500 bg-zinc-700 text-zinc-100'
                      : 'border-zinc-800 bg-zinc-900 text-zinc-500 hover:border-zinc-700 hover:text-zinc-300'
                  }`}
                >
                  {size}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label
              htmlFor="draft-slot"
              className="block text-[11px] font-semibold uppercase tracking-wider text-zinc-500"
            >
              Your draft slot
            </label>
            <select
              id="draft-slot"
              value={seat === 'random' ? 'random' : String(seat)}
              onChange={e =>
                onSetSeat(e.target.value === 'random' ? 'random' : Number(e.target.value))
              }
              className="mt-1.5 rounded-md border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-sm font-medium tabular-nums text-zinc-300 focus:border-zinc-600 focus:outline-none"
            >
              <option value="random">Random</option>
              {Array.from({ length: teams }, (_, i) => i + 1).map(n => (
                <option key={n} value={n}>
                  Pick {n}
                </option>
              ))}
            </select>
          </div>

          {/* What the slot actually buys you. Grey, because it is a consequence
              of the choice, not a rating of it. */}
          <p className="text-xs text-zinc-600 tabular-nums pb-1.5">
            {seat === 'random'
              ? `A slot from 1 to ${teams}, drawn when the draft starts.`
              : `Your first picks: ${firstPicksForSeat(seat, teams).join(', ')}…`}
          </p>

          <button
            type="button"
            onClick={onStartDraft}
            className="ml-auto rounded-lg border border-zinc-700 bg-zinc-800 px-5 py-2.5 text-sm font-semibold text-zinc-200 transition-colors hover:border-zinc-600 hover:bg-zinc-700"
          >
            Start Draft
          </button>
        </div>
      </div>

      {/* The pre-draft and in-draft lists share the same decision contract:
          published rank, 2026 bye/ADP/projection, then availability. */}
      <VirtualPoolTable
        rows={rows}
        playerMap={playerMap}
        posRank={posRank}
        draftSeason={draftSeason}
        byeMap={byeMap}
        referenceSeason={referenceSeason}
        onSelect={setSelectedPlayerId}
      />

      {selectedPlayerId != null && (
        <PlayerDetailOverlay
          playerId={selectedPlayerId}
          onClose={() => setSelectedPlayerId(null)}
          poolName={playerMap.get(selectedPlayerId)?.name}
          posRank={posRank.get(selectedPlayerId)}
        />
      )}
    </section>
  )
}

/** A single pool row — reuses DraftPlayerRow with no note callbacks,
 *  then overlays just the columns we need (ADP, percent_owned). */
function PoolRow({
  row,
  player,
  posRank,
  bye,
  draftSeason,
  referenceSeason,
  onSelect,
}: {
  row: ReturnType<typeof poolToDraftRow>
  player?: PoolPlayer
  posRank?: number
  bye: number | null
  draftSeason: number
  referenceSeason?: number | null
  onSelect: () => void
}) {
  const noSample = row.sample === 'none'
  const hasAvailability =
    !noSample && row.team_games != null && row.games_missed != null

  return (
    <tr
      onClick={onSelect}
      className="border-b border-zinc-800/50 cursor-pointer transition-colors hover:bg-zinc-800/30"
    >
      <td className="py-2.5 pl-4 pr-2 text-zinc-500 text-xs tabular-nums">
        {row.rank}
      </td>
      <td className="py-2.5 px-2">
        <div className="flex items-center gap-1.5">
          <span className="font-medium text-zinc-200">
            {row.name}
          </span>
          <InjuryTag status={player?.injury_status} compact />
        </div>
        <div className="text-[10px] text-zinc-600">
          {row.current_team}
          {' · '}
          <span className="font-semibold text-zinc-500">{positionLabel(row.position)}</span>
          {posRank != null && showsPositionalRank(row.position) && (
            <>
              {' · '}
              <span className="tabular-nums">{positionRankLabel(row.position, posRank)}</span>
            </>
          )}
        </div>
      </td>
      <td className="py-2.5 px-2 text-right font-mono tabular-nums text-xs text-zinc-500">
        {bye ?? <span className="text-zinc-700">—</span>}
      </td>
      <td className="py-2.5 px-2 text-right font-mono tabular-nums text-zinc-300 font-semibold">
        {row.adp != null ? row.adp.toFixed(1) : '—'}
      </td>
      <td className="py-2.5 px-2 text-right font-mono tabular-nums text-xs" title={`${draftSeason} projected PPR points`}>
        {player ? <ProjectedPoints player={player} /> : <span className="text-zinc-700">—</span>}
      </td>

      {/* Availability — the differentiator. Accent marks missed games. */}
      <td className="py-2.5 pr-4 pl-2">
        {noSample ? (
          <span className="text-[11px] text-zinc-500">
            {noSampleLabel(row.position, player?.has_prior_nfl_sample, referenceSeason)}
          </span>
        ) : !hasAvailability ? (
          <span className="text-[11px] text-zinc-500">
            Availability unavailable
          </span>
        ) : (
          <>
            <div className="flex items-baseline gap-1.5">
              <span
                className={`font-mono tabular-nums text-sm font-semibold ${
                  row.games_missed > 0 ? 'text-amber-400' : 'text-zinc-300'
                }`}
              >
                {row.games_played}/{row.team_games}
              </span>
              {row.games_missed > 0 && (
                <span className="text-[10px] text-zinc-600">
                  missed {row.games_missed}
                </span>
              )}
            </div>
            <AvailabilityStrip
              weeksPlayed={row.weeks_played}
              teamWeeks={row.team_weeks}
              name={row.name}
            />
          </>
        )}
      </td>

    </tr>
  )
}

/** Virtualized table — renders only visible rows + overscan (~25 DOM nodes)
 *  instead of all 11,515. Spacer divs maintain native scrollbar behaviour. */
function VirtualPoolTable({
  rows,
  playerMap,
  posRank,
  draftSeason,
  byeMap,
  referenceSeason,
  onSelect,
}: {
  rows: ReturnType<typeof poolToDraftRow>[]
  playerMap: Map<number, PoolPlayer>
  posRank: Map<number, number>
  draftSeason: number
  byeMap: Map<string, number | null>
  referenceSeason?: number | null
  onSelect: (id: number) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [containerHeight, setContainerHeight] = useState(CONTAINER_MAX_H)

  // Measure container on mount so we know how many rows can fit.
  const measuredRef = useCallback((node: HTMLDivElement | null) => {
    ;(containerRef as React.MutableRefObject<HTMLDivElement | null>).current = node
    if (node) setContainerHeight(node.clientHeight)
  }, [])

  const totalHeight = rows.length * ROW_HEIGHT
  const startIdx = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN)
  const visibleCount = Math.ceil(containerHeight / ROW_HEIGHT) + OVERSCAN * 2
  const endIdx = Math.min(rows.length, startIdx + visibleCount)
  const visibleRows = rows.slice(startIdx, endIdx)
  const topSpacer = startIdx * ROW_HEIGHT
  const bottomSpacer = Math.max(0, totalHeight - endIdx * ROW_HEIGHT)

  return (
    <div
      ref={measuredRef}
      className="overflow-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      style={{ maxHeight: CONTAINER_MAX_H }}
      onScroll={e => setScrollTop((e.target as HTMLDivElement).scrollTop)}
    >
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider sticky top-0 bg-zinc-900 z-10">
            <th className="text-left py-3 pl-4 pr-2 w-10">#</th>
            <th className="text-left py-3 px-2">Player</th>
            <th className="text-right py-3 px-2 w-12">Bye</th>
            <th className="text-right py-3 px-2">ADP</th>
            <th className="text-right py-3 px-2 w-20">
              Proj <span className="block font-normal normal-case tracking-normal text-zinc-600">{draftSeason} PPR</span>
            </th>
            <th className="text-left py-3 pr-4 pl-2 min-w-[9.5rem]">
              Available
              <span className="ml-1 font-normal normal-case tracking-normal text-zinc-600">
                by team schedule
              </span>
            </th>
          </tr>
        </thead>
        <tbody>
          {topSpacer > 0 && <tr style={{ height: topSpacer }} />}
          {visibleRows.map(row => (
            <PoolRow
              key={row.player_id}
              row={row}
              player={playerMap.get(row.player_id)}
              posRank={posRank.get(row.player_id)}
              bye={byeMap.get(row.current_team) ?? null}
              draftSeason={draftSeason}
              referenceSeason={referenceSeason}
              onSelect={() => onSelect(row.player_id)}
            />
          ))}
          {bottomSpacer > 0 && <tr style={{ height: bottomSpacer }} />}
        </tbody>
      </table>
    </div>
  )
}
