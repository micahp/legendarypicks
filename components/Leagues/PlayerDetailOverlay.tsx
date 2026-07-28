import { useEffect, useState } from 'react'
import type { PlayerDetailResponse } from './types'
import { AvailabilityStrip } from './NflDraftRoom'

interface Props {
  playerId: number
  onClose: () => void

  /* Draft-room context. All optional: the camp-tab research board renders this
     same overlay with none of it, and a research board has no pick to be on. */
  currentPick?: number
  posRank?: number
  byeWeek?: number | null
  onDraft?: (playerId: number) => void
  onQueue?: (playerId: number) => void
  canDraft?: boolean
  queued?: boolean
}

export default function PlayerDetailOverlay({
  playerId,
  onClose,
  currentPick,
  posRank,
  byeWeek,
  onDraft,
  onQueue,
  canDraft,
  queued,
}: Props) {
  const [player, setPlayer] = useState<PlayerDetailResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    fetch(`/api/nfl/draft/player/${playerId}`)
      .then(res => {
        if (!res.ok) throw new Error(`Failed to load player (${res.status})`)
        return res.json()
      })
      .then((data: PlayerDetailResponse) => {
        if (!cancelled) {
          setPlayer(data)
          setLoading(false)
        }
      })
      .catch(err => {
        if (!cancelled) {
          setError(err.message || 'Failed to load player details')
          setLoading(false)
        }
      })

    return () => { cancelled = true }
  }, [playerId])

  const isDef = player?.position === 'DEF'
  const isPk = player?.position === 'PK'
  const isSkill = player && !isDef && !isPk
  const isPassCatcher = player && (player.position === 'WR' || player.position === 'RB' || player.position === 'TE')
  const noSample = player?.sample === 'none'
  const thin = player?.sample === 'thin'
  const missed = player?.games_missed ?? null

  // The two PPR figures diverge only when availability dropped. Compare at the
  // precision we render (1dp) so a rounding tie does not print twice.
  const pprDiverges =
    player != null &&
    player.ppr_per_game_played != null &&
    player.ppr_per_team_game != null &&
    player.ppr_per_game_played.toFixed(1) !== player.ppr_per_team_game.toFixed(1)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={player ? `${player.name} details` : 'Player details'}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Card */}
      <div className="relative z-10 w-full max-w-[420px] max-h-[90vh] overflow-y-auto rounded-xl border border-zinc-800 bg-zinc-900 shadow-2xl">
        {/* Close button */}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute right-3 top-3 rounded-md p-1.5 text-zinc-500 hover:text-zinc-200 transition-colors"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>

        {/* Loading */}
        {loading && (
          <div className="p-6 space-y-3 animate-pulse">
            <div className="h-6 w-1/2 rounded bg-zinc-800" />
            <div className="h-4 w-1/3 rounded bg-zinc-800" />
            <div className="h-3 w-full rounded bg-zinc-800" />
            <div className="h-10 w-full rounded bg-zinc-800" />
            <div className="h-10 w-full rounded bg-zinc-800" />
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <div className="p-6 text-center">
            <p className="text-sm text-red-400">{error}</p>
            <button
              type="button"
              onClick={onClose}
              className="mt-3 rounded-md border border-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:border-zinc-600 hover:text-zinc-100"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Content */}
        {!loading && !error && player && (
          <div className="p-6 space-y-5">
            {/* ── Header: name, position, team ─────────────────────────── */}
            <header className="pr-8">
              <h2 className="text-lg font-bold text-zinc-100 leading-tight">
                {player.name}
              </h2>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[11px] font-semibold uppercase text-zinc-400">
                  {posRank != null ? `${player.position}${posRank}` : player.position}
                </span>
                <span className="text-sm text-zinc-400">{player.team}</span>
                {byeWeek != null && (
                  <>
                    <span className="text-xs text-zinc-600">·</span>
                    <span className="text-xs text-zinc-500">
                      Bye <span className="tabular-nums">{byeWeek}</span>
                    </span>
                  </>
                )}
                {!player.active && (
                  <span className="text-[11px] text-zinc-600">(inactive)</span>
                )}
              </div>
              {posRank != null && (
                <p className="mt-1 text-[10px] text-zinc-600">
                  {player.position}{posRank} by ADP — not our ranking
                </p>
              )}
            </header>

            {/* ── Availability strip ────────────────────────────────────── */}
            {!noSample && player.team_weeks.length > 0 && (
              <section>
                <AvailabilityStrip
                  weeksPlayed={player.weeks_played}
                  teamWeeks={player.team_weeks}
                  name={player.name}
                />
                {/* games_played / games_missed / team_games summary */}
                <div className="mt-1.5 flex items-baseline gap-2">
                  <span
                    className={`font-mono tabular-nums text-sm font-semibold ${
                      missed != null && missed > 0 ? 'text-amber-400' : 'text-zinc-300'
                    }`}
                  >
                    {player.games_played}/{player.team_games} games played
                  </span>
                  {missed != null && missed > 0 && (
                    <span className="text-xs text-zinc-500">
                      missed {missed}
                    </span>
                  )}
                </div>
              </section>
            )}

            {noSample && (
              <section>
                <p className="text-sm text-zinc-500">No NFL sample</p>
              </section>
            )}

            {/* ── Stat rows ─────────────────────────────────────────────── */}
            <section className="space-y-3">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                {isDef ? 'D/ST' : isPk ? 'Kicking' : 'PPR'} Scoring
              </h3>

              <div className="rounded-lg border border-zinc-800 bg-zinc-800/40">
                {/* Position-aware stat rows */}
                {isDef ? (
                  <>
                    <StatRow
                      label="D/ST pts total"
                      value={player.dst_pts_total}
                      muted={thin}
                    />
                    <StatRow
                      label="D/ST pts / game"
                      value={player.dst_pts_per_game}
                      strong
                    />
                  </>
                ) : isPk ? (
                  <>
                    <StatRow
                      label="PK pts total"
                      value={player.pk_pts_total}
                      muted={thin}
                    />
                    <StatRow
                      label="PK pts / game"
                      value={player.pk_pts_per_game}
                      strong
                    />
                  </>
                ) : pprDiverges ? (
                  /* The two PPR figures only carry information when they disagree,
                     and they disagree exactly when a player missed time: per game
                     played is what he did on the field, per team game is what the
                     roster spot actually returned. Burrow 2025 is 16.8 and 7.9. */
                  <>
                    <StatRow
                      label="PPR / game played"
                      value={player.ppr_per_game_played}
                      muted={thin}
                    />
                    <StatRow
                      label="PPR / team game"
                      value={player.ppr_per_team_game}
                      strong
                    />
                  </>
                ) : (
                  /* Identical figures mean he played every game his team did.
                     Printing the same number twice reads as a rendering bug, so
                     say it once and say why it is only one number. */
                  <StatRow
                    label="PPR / game"
                    value={player.ppr_per_game_played ?? player.ppr_per_team_game}
                    muted={thin}
                    strong
                    note="played every team game"
                  />
                )}

                {/* Conditional averages — labeled */}
                {/* xfp_per_game: expected PPR (non PK/DEF) */}
                {isSkill && (
                  <StatRow
                    label="Expected PPR / game"
                    value={player.xfp_per_game}
                  />
                )}

                {/* snap_pct, target_share (non PK/DEF) */}
                {isSkill && (
                  <>
                    <StatRow
                      label="Snap %"
                      value={player.snap_pct}
                      format="pct0"
                    />
                    <StatRow
                      label="Target share"
                      value={player.target_share}
                      format="pct1"
                    />
                  </>
                )}
              </div>
            </section>

            {/* ── QB info (WR/RB/TE only) ───────────────────────────────── */}
            {isPassCatcher && player.qb && (
              <section className="space-y-2">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                  Quarterback
                </h3>
                <div className="rounded-lg border border-zinc-800 bg-zinc-800/40 px-3 py-2.5">
                  <div className="flex items-baseline justify-between">
                    <span className="text-sm font-medium text-zinc-200">
                      {player.qb.name}
                    </span>
                    <span className="text-xs text-zinc-400">{player.qb.team}</span>
                  </div>
                  <div className="mt-0.5 flex items-baseline gap-1.5">
                    <span className="font-mono tabular-nums text-xs text-zinc-500">
                      {player.qb.games_played} games played
                    </span>
                  </div>
                </div>
              </section>
            )}

            {/* ── ADP and ownership ──────────────────────────────────────── */}
            <section className="space-y-2">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                Draft
              </h3>
              <div className="rounded-lg border border-zinc-800 bg-zinc-800/40 px-3 py-2.5 space-y-1.5">
                <div className="flex items-baseline justify-between">
                  <span className="text-xs text-zinc-400">ADP</span>
                  <span className="font-mono tabular-nums text-sm font-semibold text-zinc-200">
                    {player.adp != null ? player.adp.toFixed(1) : '\u2014'}
                  </span>
                </div>
                <div className="flex items-baseline justify-between">
                  <span className="text-xs text-zinc-400">Owned</span>
                  <span className="font-mono tabular-nums text-sm text-zinc-300">
                    {player.percent_owned != null
                      ? `${player.percent_owned.toFixed(1)}%`
                      : '\u2014'}
                  </span>
                </div>

                {/* Reach vs value \u2014 the only question a mock draft exists to
                    answer. ADP alone cannot answer it without the pick you are
                    sitting on, which this overlay never used to know. */}
                {currentPick != null && player.adp != null && (
                  <div className="flex items-baseline justify-between border-t border-zinc-800/60 pt-1.5">
                    <span className="text-xs text-zinc-400">
                      At pick <span className="tabular-nums">{currentPick}</span>
                    </span>
                    <span className="text-xs text-zinc-300">
                      {describeAdpDelta(currentPick, player.adp)}
                    </span>
                  </div>
                )}
              </div>
            </section>

            {/* \u2500\u2500 Actions \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
                Without these the overlay is a dead end: read it, close it, then
                hunt the row again. */}
            {(onDraft || onQueue) && (
              <section className="flex items-center gap-2">
                {onDraft && (
                  <button
                    type="button"
                    disabled={!canDraft}
                    onClick={() => { onDraft(playerId); onClose() }}
                    className={`flex-1 rounded-lg border px-4 py-2.5 text-sm font-semibold transition-colors ${
                      canDraft
                        ? 'border-zinc-600 bg-zinc-800 text-zinc-100 hover:border-zinc-500 hover:bg-zinc-700'
                        : 'cursor-not-allowed border-zinc-800 bg-zinc-900 text-zinc-700'
                    }`}
                  >
                    {canDraft ? 'Draft' : 'Not your pick'}
                  </button>
                )}
                {onQueue && (
                  <button
                    type="button"
                    disabled={queued}
                    onClick={() => { onQueue(playerId); onClose() }}
                    className={`rounded-lg border px-4 py-2.5 text-sm font-medium transition-colors ${
                      queued
                        ? 'cursor-default border-zinc-800 bg-zinc-900 text-zinc-600'
                        : 'border-zinc-700 bg-zinc-900 text-zinc-300 hover:border-zinc-600 hover:text-zinc-100'
                    }`}
                  >
                    {queued ? 'Queued' : 'Queue'}
                  </button>
                )}
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/* Reach vs value, in the unit drafters actually speak: picks, and rounds when the
   gap is big enough that picks stop being intuitive. 12-team league, so a round is
   12 picks. Deliberately plain language and no colour — honest-data-ui §6.2 keeps
   accent for absence, and "reaching" is a judgement, not a missing value. */
const PICKS_PER_ROUND = 12

function describeAdpDelta(currentPick: number, adp: number): string {
  const delta = adp - currentPick // positive = he is going later than this pick
  const picks = Math.round(Math.abs(delta))

  if (picks <= 2) return 'about even with ADP'

  const rounds = Math.abs(delta) / PICKS_PER_ROUND
  const size =
    rounds >= 1
      ? `${rounds.toFixed(1)} rounds`
      : `${picks} pick${picks === 1 ? '' : 's'}`

  return delta > 0 ? `reaching ${size} early` : `value — ${size} past ADP`
}

/** A single stat row: label left, monospace value right. Dash for null. */
function StatRow({
  label,
  value,
  strong,
  muted,
  format,
  note,
}: {
  label: string
  value: number | null
  strong?: boolean
  muted?: boolean
  format?: 'pct0' | 'pct1'
  note?: string
}) {
  const display = value != null
    ? format === 'pct0'
      ? `${value.toFixed(0)}%`
      : format === 'pct1'
        ? `${value.toFixed(1)}%`
        : value.toFixed(1)
    : '\u2014'

  return (
    <div className="flex items-baseline justify-between px-3 py-2 border-b border-zinc-800/50 last:border-b-0">
      <span className="text-xs text-zinc-400">
        {label}
        {note && (
          <span className="ml-1.5 text-[10px] text-zinc-600">{note}</span>
        )}
      </span>
      {value == null ? (
        <span className="font-mono tabular-nums text-sm text-zinc-700">{display}</span>
      ) : (
        <span
          className={`font-mono tabular-nums text-sm ${
            muted
              ? 'text-zinc-500'
              : strong
                ? 'text-zinc-200 font-semibold'
                : 'text-zinc-400'
          }`}
        >
          {display}
        </span>
      )}
    </div>
  )
}
