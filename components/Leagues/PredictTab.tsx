import { useState } from 'react'
import type {
  UfcCrowd,
  UfcFight,
  UfcPick,
  UfcPickMethod,
  UfcPickRecord,
  UfcPickSide,
} from './hooks/useUfcPredictData'

const METHODS: UfcPickMethod[] = ['KO/TKO', 'SUB', 'DEC']

interface PredictTabProps {
  fights: UfcFight[]
  myPicks: UfcPick[]
  record: UfcPickRecord
  crowd: Record<string, UfcCrowd>
  loading: boolean
  error: string | null
  actionError: string | null
  submittingKey: string | null
  onSubmitPick: (
    fightKey: string,
    side: UfcPickSide,
    method: UfcPickMethod | null,
  ) => Promise<boolean>
}

export default function PredictTab({
  fights,
  myPicks,
  record,
  crowd,
  loading,
  error,
  actionError,
  submittingKey,
  onSubmitPick,
}: PredictTabProps) {
  const [draftMethods, setDraftMethods] = useState<Record<string, UfcPickMethod | null>>({})
  const picksByFight = new Map(myPicks.map(pick => [pick.fightKey, pick]))
  const currentFightKeys = new Set(fights.map(fight => fight.fightKey))
  const historyPicks = myPicks
    .filter(pick => !currentFightKeys.has(pick.fightKey))
    .sort((left, right) => (right.settledAt || right.createdAt) - (left.settledAt || left.createdAt))
  const groupedFights = fights.reduce((groups, fight) => {
    const segment = fight.cardSegment || 'Fight Card'
    if (!groups[segment]) groups[segment] = []
    groups[segment].push(fight)
    return groups
  }, {} as Record<string, UfcFight[]>)

  const chooseMethod = (fight: UfcFight, pick: UfcPick | undefined, method: UfcPickMethod) => {
    const selectedMethod = pick ? pick.method : draftMethods[fight.fightKey] ?? null
    const nextMethod = selectedMethod === method ? null : method
    if (!pick) {
      setDraftMethods(current => ({ ...current, [fight.fightKey]: nextMethod }))
      return
    }
    void onSubmitPick(fight.fightKey, pick.side, nextMethod)
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="flex flex-col gap-3 rounded-xl border border-zinc-800 bg-zinc-900 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-bold text-zinc-100">UFC Pick&apos;em</h2>
          <p className="mt-1 text-sm text-zinc-500">
            Pick each winner. Method calls are an optional bonus.
          </p>
        </div>
        <PickRecord record={record} />
      </div>

      {(error || actionError) && (
        <div
          role="alert"
          className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400"
        >
          {error || actionError}
        </div>
      )}

      {loading ? (
        <div className="space-y-3" role="status" aria-label="Loading upcoming UFC card">
          {[0, 1, 2, 3].map(index => (
            <div key={index} className="animate-pulse rounded-xl border border-zinc-800 bg-zinc-900 p-4">
              <div className="mb-4 h-3 w-28 rounded bg-zinc-800" />
              <div className="grid grid-cols-2 gap-3">
                <div className="h-16 rounded-lg bg-zinc-800" />
                <div className="h-16 rounded-lg bg-zinc-800" />
              </div>
            </div>
          ))}
        </div>
      ) : error ? null : fights.length === 0 ? (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-12 text-center">
          <p className="text-sm text-zinc-500">No upcoming UFC card</p>
        </div>
      ) : (
        <div className="space-y-6">
          <CardHeading fight={fights[0]} />
          {Object.entries(groupedFights).map(([segment, segmentFights]) => (
            <section key={segment} className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500">
                {segment}
              </h3>
              {segmentFights.map(fight => {
                const pick = picksByFight.get(fight.fightKey)
                const selectedMethod = pick ? pick.method : draftMethods[fight.fightKey] ?? null
                const locked = fight.state !== 'pre'
                  || fight.lockAt === null
                  || fight.lockAt <= Date.now()
                const submitting = submittingKey === fight.fightKey
                return (
                  <article
                    key={fight.fightKey}
                    data-fight-key={fight.fightKey}
                    className="rounded-xl border border-zinc-800 bg-zinc-900 p-4"
                  >
                    <div className="mb-3 flex items-center justify-between gap-3 text-xs text-zinc-500">
                      <span>{formatFightTime(fight.date)}</span>
                      <span className={locked ? 'font-medium text-amber-400' : 'text-zinc-500'}>
                        {locked ? 'Locked' : 'Pick winner'}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-2 sm:gap-3">
                      <FighterButton
                        fighter={fight.home}
                        selected={pick?.side === 'home'}
                        disabled={locked || submitting}
                        onClick={() => {
                          void onSubmitPick(fight.fightKey, 'home', selectedMethod)
                        }}
                      />
                      <FighterButton
                        fighter={fight.away}
                        selected={pick?.side === 'away'}
                        disabled={locked || submitting}
                        onClick={() => {
                          void onSubmitPick(fight.fightKey, 'away', selectedMethod)
                        }}
                      />
                    </div>

                    <div className="mt-4 flex flex-wrap items-center gap-2">
                      <span className="mr-1 text-[11px] font-medium uppercase tracking-wider text-zinc-500">
                        Method <span className="normal-case tracking-normal text-zinc-600">(optional)</span>
                      </span>
                      {METHODS.map(method => (
                        <button
                          key={method}
                          type="button"
                          aria-pressed={selectedMethod === method}
                          disabled={locked || submitting}
                          onClick={() => chooseMethod(fight, pick, method)}
                          className={`rounded-md border px-2.5 py-1 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                            selectedMethod === method
                              ? 'border-emerald-500/60 bg-emerald-500/10 text-emerald-300'
                              : 'border-zinc-700 bg-zinc-800/60 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200'
                          }`}
                        >
                          {method}
                        </button>
                      ))}
                    </div>

                    {pick && (
                      <CrowdSplit
                        fight={fight}
                        crowd={crowd[fight.fightKey]}
                      />
                    )}
                  </article>
                )
              })}
            </section>
          ))}
        </div>
      )}

      {!loading && historyPicks.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500">
            Pick history
          </h2>
          <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900">
            {historyPicks.map(pick => (
              <div
                key={pick.fightKey}
                className="flex items-center justify-between gap-3 border-b border-zinc-800/70 px-4 py-3 text-sm last:border-b-0"
              >
                <div className="min-w-0">
                  <div className="truncate font-semibold text-zinc-300">{pick.fighterName}</div>
                  <div className="truncate text-xs text-zinc-600">
                    vs {pick.opponentName}
                    {pick.method && ` · ${pick.method}`}
                    {pick.methodResult === 'win' && ' ✓'}
                    {pick.methodResult === 'loss' && ' ✕'}
                  </div>
                </div>
                <PickResult pick={pick} />
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function PickResult({ pick }: { pick: UfcPick }) {
  if (pick.result === 'win') {
    return (
      <span className="shrink-0 font-semibold tabular-nums text-emerald-400">
        Won +{(pick.points ?? 0).toFixed(1)}
      </span>
    )
  }
  if (pick.result === 'loss') {
    return <span className="shrink-0 font-semibold text-red-400">Lost</span>
  }
  if (pick.result === 'void') {
    return <span className="shrink-0 font-semibold text-zinc-500">Void</span>
  }
  return <span className="shrink-0 text-xs text-zinc-600">Pending</span>
}

function PickRecord({ record }: { record: UfcPickRecord }) {
  return (
    <div className="shrink-0 text-left sm:text-right" aria-label="UFC pick record">
      <div className="flex items-center gap-2 sm:justify-end">
        <span className="text-lg font-bold tabular-nums text-zinc-100">
          {record.wins}–{record.losses}
        </span>
        {record.streak > 0 && (
          <span className="text-sm font-bold tabular-nums text-emerald-400">W{record.streak}</span>
        )}
        {record.streak < 0 && (
          <span className="text-sm font-bold tabular-nums text-red-400">L{-record.streak}</span>
        )}
      </div>
      <div className="text-xs tabular-nums text-zinc-500">
        {record.voids > 0 ? `${record.voids} void${record.voids === 1 ? '' : 's'}` : 'Winner record'}
      </div>
    </div>
  )
}

function CardHeading({ fight }: { fight: UfcFight }) {
  return (
    <div className="space-y-1">
      <h2 className="text-xl font-bold text-zinc-100">{fight.event}</h2>
      <p className="text-sm text-zinc-500">{formatCardDate(fight.date)}</p>
    </div>
  )
}

function FighterButton({
  fighter,
  selected,
  disabled,
  onClick,
}: {
  fighter: UfcFight['home']
  selected: boolean
  disabled: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      disabled={disabled}
      onClick={onClick}
      className={`min-w-0 rounded-lg border px-3 py-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        selected
          ? 'border-emerald-500 bg-emerald-500/10 text-emerald-50'
          : 'border-zinc-700 bg-zinc-800/60 text-zinc-200 hover:border-zinc-500 hover:bg-zinc-800'
      }`}
    >
      <span className="block break-words text-sm font-bold leading-snug">{fighter.name}</span>
      <span className="mt-1 block text-xs tabular-nums text-zinc-500">
        {fighter.record || 'Record unavailable'}
      </span>
    </button>
  )
}

function CrowdSplit({ fight, crowd }: { fight: UfcFight; crowd?: UfcCrowd }) {
  if (!crowd) {
    return <p className="mt-4 text-xs text-zinc-600">Loading crowd split…</p>
  }
  if (crowd.total === 0 || crowd.shareHome === null) {
    return <p className="mt-4 text-xs text-zinc-600">Waiting for the first crowd pick.</p>
  }
  const homePercent = Math.round(crowd.shareHome * 100)
  const awayPercent = 100 - homePercent
  return (
    <div className="mt-4 border-t border-zinc-800 pt-3">
      <div className="mb-2 flex items-center justify-between gap-3 text-[11px] text-zinc-500">
        <span>Crowd · <span className="tabular-nums">{crowd.total}</span></span>
        <span>{crowd.total === 1 ? '1 pick' : `${crowd.total} picks`}</span>
      </div>
      <div className="mb-1.5 flex items-center justify-between gap-3 text-xs">
        <span className="min-w-0 truncate text-zinc-300">
          {fight.home.name} <span className="tabular-nums text-zinc-500">{homePercent}%</span>
        </span>
        <span className="min-w-0 truncate text-right text-zinc-300">
          <span className="tabular-nums text-zinc-500">{awayPercent}%</span> {fight.away.name}
        </span>
      </div>
      <div className="flex h-1.5 overflow-hidden rounded-full bg-zinc-800" aria-label={`Crowd split: ${homePercent}% ${fight.home.name}, ${awayPercent}% ${fight.away.name}`}>
        <div className="bg-emerald-500" style={{ width: `${homePercent}%` }} />
        <div className="bg-zinc-500" style={{ width: `${awayPercent}%` }} />
      </div>
    </div>
  )
}

function formatFightTime(value: string | null) {
  if (!value) return 'Time TBD'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Time TBD'
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function formatCardDate(value: string | null) {
  if (!value) return 'Date to be announced'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Date to be announced'
  return date.toLocaleDateString([], {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  })
}
