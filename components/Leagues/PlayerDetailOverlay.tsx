import { useEffect, useState } from 'react'
import type { PlayerDetailResponse } from './types'
import { AvailabilityStrip } from './NflDraftRoom'
import StatRankCard from './StatRankCard'
import PlayerGameLog from './PlayerGameLog'
import {
  positionLabel,
  positionRankLabel,
  showsPositionalRank,
} from '../../lib/nfl/positionLabel'

interface Props {
  playerId: number
  onClose: () => void
  /* External ESPN-style rank data — not part of the /api/nfl/draft/player response */
  stat_ranks?: Record<string, { value: number | null; rank: number | null; label: string }> | null

  /* Pool-level name — available immediately so the header + League Rankings
     can render outside the detail-fetch loading gate. */
  poolName?: string

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
  poolName,
  currentPick,
  posRank,
  byeWeek,
  onDraft,
  onQueue,
  canDraft,
  queued,
  stat_ranks,
}: Props) {
  /* stat_ranks: optional ESPN-style rank data — not part of the normal
     player detail endpoint. Passed from parent when overlay is shown in
     the player card or draft room. */
  const [player, setPlayer] = useState<PlayerDetailResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<'overview' | 'log' | 'news'>('overview')
  const [news, setNews] = useState<{ articles: Array<{ id: number; headline: string; notes: string; analysis: string; injury_status: string | null; injury_type: string | null; return_date: string | null; published: string; link: string }> } | null>(null)
  const [newsLoading, setNewsLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setTab('overview')

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

  // Fetch news when news tab is selected
  useEffect(() => {
    if (tab !== 'news') return
    let cancelled = false
    setNewsLoading(true)
    fetch(`/api/player/${playerId}/news?limit=10`)
      .then(res => res.json())
      .then(data => {
        if (!cancelled) {
          setNews(data)
          setNewsLoading(false)
        }
      })
      .catch(() => {
        if (!cancelled) setNewsLoading(false)
      })
    return () => { cancelled = true }
  }, [tab, playerId])

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
      <div className="relative z-10 w-full max-w-[520px] max-h-[90vh] overflow-y-auto rounded-xl border border-zinc-800 bg-zinc-900 shadow-2xl">
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

        {/* Name header — rendering immediately from pool data when available */}
        {poolName && (
          <div className="px-6 pt-5">
            <h2 className="text-lg font-bold text-zinc-100 leading-tight">
              {poolName}
            </h2>
          </div>
        )}

        {/* League Rankings — renders from pool data, NOT from overlay fetch */}
        {stat_ranks && Object.keys(stat_ranks).length > 0 && (
          <div className={poolName ? 'px-6 pb-3' : 'px-6 py-4'}>
            <StatRankCard statRanks={stat_ranks} title="League Rankings" />
          </div>
        )}

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
          <div className={poolName ? 'px-6 pb-6 space-y-5' : 'p-6 space-y-5'}>
            {/* ── Header: name, position, team ───────────────────────────
                 When poolName is set the name is already above; show only
                 position/team/bye metadata here. */}
            <header className="pr-8">
              {!poolName && (
                <h2 className="text-lg font-bold text-zinc-100 leading-tight">
                  {player.name}
                </h2>
              )}
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[11px] font-semibold uppercase text-zinc-400">
                  {showsPositionalRank(player.position)
                    ? positionRankLabel(player.position, posRank)
                    : positionLabel(player.position)}
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
                {player.injury_status && player.injury_status !== 'ACTIVE' && (
                  <>
                    <span className="text-xs text-zinc-600">·</span>
                    <span className="rounded bg-red-900/30 px-1.5 py-0.5 text-[10px] font-semibold text-red-400">
                      {injuryLabel(player.injury_status)}
                    </span>
                  </>
                )}
                {!player.active && (
                  <span className="text-[11px] text-zinc-600">(inactive)</span>
                )}
              </div>
              {posRank != null && showsPositionalRank(player.position) && (
                <p className="mt-1 text-[10px] text-zinc-600">
                  {positionRankLabel(player.position, posRank)} by ADP — not our ranking
                </p>
              )}
            </header>

            {/* ── Tabs ──────────────────────────────────────────────────────
                Two views because they answer different questions. Overview is
                "what is this player worth"; the log is "how did he get there",
                which a season average cannot show — a 12 PPR/g average hides
                whether he was rising or falling all year. */}

                        <div className="flex gap-1 border-b border-zinc-800" role="tablist">
              {([['overview', 'Overview'], ['log', 'Game log'], ['news', 'News']] as const).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={tab === id}
                  onClick={() => setTab(id)}
                  className={`-mb-px border-b-2 px-3 py-1.5 text-xs font-medium transition-colors ${
                    tab === id
                      ? 'border-zinc-400 text-zinc-100'
                      : 'border-transparent text-zinc-500 hover:text-zinc-300'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            {tab === 'log' && <PlayerGameLog playerId={playerId} />}

            {tab === 'news' && (
              <div className="space-y-3 py-2">
                {newsLoading && (
                  <div className="space-y-3 animate-pulse">
                    {[0, 1, 2].map(i => (
                      <div key={i} className="h-16 rounded-lg bg-zinc-800" />
                    ))}
                  </div>
                )}
                {!newsLoading && news && news.articles.length === 0 && (
                  <div className="text-center py-4 text-zinc-500">
                    <p className="text-xs">No recent news for this player</p>
                  </div>
                )}
                {!newsLoading && news && news.articles.length > 0 && (
                  news.articles.map(article => (
                    <div key={article.id} className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 space-y-1.5">
                      {/* Headline + injury badge */}
                      <div className="flex items-start gap-2">
                        <a
                          href={article.link}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex-1 min-w-0"
                        >
                          <h4 className="text-xs font-semibold text-zinc-100 hover:text-emerald-400 transition-colors">
                            {article.headline}
                          </h4>
                        </a>
                        {article.injury_status && (
                          <span className="shrink-0 rounded bg-red-500/10 px-1 py-0.5 text-[9px] font-bold text-red-400 uppercase">
                            {article.injury_status}
                          </span>
                        )}
                      </div>

                      {/* News blurb */}
                      <p className="text-[11px] text-zinc-400 leading-relaxed">
                        {article.notes}
                      </p>

                      {/* Fantasy analysis */}
                      {article.analysis && (
                        <div className="rounded-md bg-zinc-800/50 px-2.5 py-1.5 border-l-2 border-emerald-500/50">
                          <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-400/70 mb-0.5">
                            Fantasy Spin
                          </p>
                          <p className="text-[11px] text-zinc-300 leading-relaxed">
                            {article.analysis}
                          </p>
                        </div>
                      )}

                      {/* Meta */}
                      <div className="flex items-center gap-2 text-[9px] text-zinc-600">
                        <time dateTime={article.published}>
                          {new Date(article.published).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                        </time>
                        {article.return_date && (
                          <span>Return: {new Date(article.return_date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
                        )}
                        {article.injury_type && (
                          <span className="text-red-400/60">{article.injury_type}</span>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {tab === 'overview' && (<>
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
                      label="K pts total"
                      value={player.pk_pts_total}
                      muted={thin}
                    />
                    <StatRow
                      label="K pts / game"
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

            </>)}

            {/* ── Actions ────────────────────────────────────────────────────
                Without these the overlay is a dead end: read it, close it, then
                hunt the row again. */}
            {/* ── Actions ────────────────────────────────────────────────────
                The pool row holds exactly one button, and on the clock that
                button is Draft — ESPN's rule, and ours. The card is where the
                deliberately kept second option lives, and it has to, because our
                draft is not ESPN's:

                ESPN replaces QUEUE with DRAFT on your turn and you queue during
                the eleven turns in between. Here there are no turns in between —
                every bot pick between yours runs in one synchronous loop, so it
                is your turn from the moment the room opens until the draft ends.
                Applying ESPN's rule to every surface would leave nowhere at all
                to queue from, and the queue is the thing the 30-second clock
                drafts out of. So: one button on the row, both on the card.

                "Not your pick" is gone. A disabled control whose label states a
                fact the header already states is noise. */}
            {(onDraft || onQueue) && (
              <section className="flex items-center gap-2">
                {canDraft && onDraft && (
                  <button
                    type="button"
                    aria-label={`Draft ${player.name}`}
                    onClick={() => { onDraft(playerId); onClose() }}
                    className="flex-1 rounded-lg border border-zinc-600 bg-zinc-800 px-4 py-2.5 text-sm font-semibold text-zinc-100 transition-colors hover:border-zinc-500 hover:bg-zinc-700"
                  >
                    Draft
                  </button>
                )}
                {onQueue && (
                  <button
                    type="button"
                    disabled={queued}
                    aria-label={queued ? `${player.name} is queued` : `Queue ${player.name}`}
                    onClick={() => { onQueue(playerId); onClose() }}
                    className={`rounded-lg border px-4 py-2.5 text-sm font-medium transition-colors ${
                      canDraft ? '' : 'flex-1 '
                    }${
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

function injuryLabel(status: string): string {
  switch (status) {
    case 'QUESTIONABLE': return 'Q'
    case 'DOUBTFUL': return 'D'
    case 'OUT': return 'O'
    case 'INJURY_RESERVE': return 'IR'
    default: return status
  }
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
