import { ChangeEvent, ReactNode, useMemo, useRef, useState } from 'react'
import {
  lineupsToCsv,
  optimizeUfcLineups,
  parseDraftKingsMmaCsv,
  selectNextDraftKingsSlate,
  UFC_DK_SALARY_CAP,
  type UfcOptimizerFighter,
  type UfcOptimizerLineup,
  type UfcOptimizerSlate,
} from './ufcOptimizer'
import { UFC_DK_SLATE_2026_08_29 } from './data/ufcDraftKingsSlate20260829'
import UfcSlateRail, { buildUfcSlateFights, type UfcPoolSort } from './UfcSlateRail'
import UfcFighterOverlay from './UfcFighterOverlay'

const LINEUP_COUNTS = [1, 2, 3, 5, 10, 20, 50, 100, 150]
const PUBLISHED_DRAFTKINGS_POOLS = [UFC_DK_SLATE_2026_08_29]

function money(value: number): string {
  return `$${value.toLocaleString()}`
}

function score(value: number | null): string {
  return value === null ? '—' : value.toFixed(2)
}

function replaceInSet(current: Set<string>, id: string, enabled: boolean): Set<string> {
  const next = new Set(current)
  if (enabled) next.add(id)
  else next.delete(id)
  return next
}

export default function UfcOptimizerTab() {
  const [slate, setSlate] = useState<UfcOptimizerSlate | null>(() => {
    const selected = selectNextDraftKingsSlate(PUBLISHED_DRAFTKINGS_POOLS)
    return selected ? {
      ...selected,
      fighters: selected.fighters.map(fighter => ({ ...fighter })),
    } : null
  })
  const [sourceName, setSourceName] = useState(
    () => selectNextDraftKingsSlate(PUBLISHED_DRAFTKINGS_POOLS)?.sourceName || '',
  )
  const [csvText, setCsvText] = useState('')
  const [showPaste, setShowPaste] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [lockedIds, setLockedIds] = useState<Set<string>>(new Set())
  const [excludedIds, setExcludedIds] = useState<Set<string>>(new Set())
  const [lineupCount, setLineupCount] = useState(2)
  const [minUnique, setMinUnique] = useState(1)
  const [maxExposure, setMaxExposure] = useState(100)
  const [search, setSearch] = useState('')
  const [selectedFight, setSelectedFight] = useState<string | null>(null)
  const [sortMode, setSortMode] = useState<UfcPoolSort>('game_time')
  const [overlayFighterId, setOverlayFighterId] = useState<string | null>(null)
  const [lineups, setLineups] = useState<UfcOptimizerLineup[]>([])
  const [buildMessage, setBuildMessage] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const clearBuild = () => {
    setLineups([])
    setBuildMessage(null)
  }

  const loadCsv = (contents: string, name: string) => {
    try {
      const parsed = parseDraftKingsMmaCsv(contents)
      parsed.sourceName = name
      setSlate(parsed)
      setSourceName(name)
      setLockedIds(new Set())
      setExcludedIds(new Set())
      setLineups([])
      setBuildMessage(null)
      setImportError(null)
      setShowPaste(false)
      setSelectedFight(null)
      setSortMode('game_time')
      setOverlayFighterId(null)
    } catch (error: any) {
      setImportError(error.message || 'Unable to read that DraftKings CSV.')
    }
  }

  const importFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    loadCsv(await file.text(), file.name)
    event.target.value = ''
  }

  const updateTarget = (fighterId: string, rawValue: string) => {
    if (!slate) return
    const value = rawValue.trim() === '' ? null : Number(rawValue)
    setSlate({
      ...slate,
      fighters: slate.fighters.map(fighter => (
        fighter.id === fighterId
          ? { ...fighter, target: value !== null && Number.isFinite(value) && value >= 0 ? value : null }
          : fighter
      )),
    })
    setLineups([])
    setBuildMessage(null)
  }

  const opponentNames = useMemo(() => {
    return new Map((slate?.fighters || []).map(fighter => [fighter.id, fighter.name]))
  }, [slate])

  const visibleFighters = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const gameOrder = new Map<string, number>()
    buildUfcSlateFights(slate?.fighters || []).forEach((fight, fightIndex) => {
      fight.fighters.forEach((fighter, fighterIndex) => gameOrder.set(fighter.id, fightIndex * 2 + fighterIndex))
    })
    return (slate?.fighters || [])
      .filter(fighter => !selectedFight || fighter.gameInfo === selectedFight)
      .filter(fighter => !needle || fighter.name.toLowerCase().includes(needle))
      .sort((left, right) => {
        const leftTarget = left.target ?? -Infinity
        const rightTarget = right.target ?? -Infinity
        if (sortMode === 'game_time') return (gameOrder.get(left.id) ?? Infinity) - (gameOrder.get(right.id) ?? Infinity)
        if (sortMode === 'salary') return right.salary - left.salary || rightTarget - leftTarget
        if (sortMode === 'value') {
          const leftValue = left.target === null ? -Infinity : left.target / (left.salary / 1000)
          const rightValue = right.target === null ? -Infinity : right.target / (right.salary / 1000)
          return rightValue - leftValue || rightTarget - leftTarget
        }
        return rightTarget - leftTarget || right.salary - left.salary || left.name.localeCompare(right.name)
      })
  }, [slate, search, selectedFight, sortMode])

  const overlayFighter = slate?.fighters.find(fighter => fighter.id === overlayFighterId) || null
  const overlayOpponent = overlayFighter?.opponentId
    ? slate?.fighters.find(fighter => fighter.id === overlayFighter.opponentId) || null
    : null

  const build = () => {
    if (!slate) return
    if (slate.unresolvedMatchups > 0) {
      setLineups([])
      setBuildMessage(
        `${slate.unresolvedMatchups} fighters do not resolve to a two-fighter matchup. Re-export the DraftKings MMA slate before building.`,
      )
      return
    }
    const result = optimizeUfcLineups(slate.fighters, {
      count: lineupCount,
      lockedIds,
      excludedIds,
      minUnique,
      maxExposurePercent: maxExposure,
    })
    setLineups(result.lineups)
    setBuildMessage(result.error)
  }

  const downloadLineups = () => {
    if (!lineups.length) return
    const blob = new Blob([lineupsToCsv(lineups)], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'ufc-draftkings-lineups.csv'
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-2xl">
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-zinc-100">UFC Lineup Optimizer</h2>
              <span className="rounded border border-zinc-700 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
                DraftKings
              </span>
            </div>
            <p className="mt-1 text-sm text-zinc-500">
              {slate
                ? 'The next available DraftKings pool is loaded. Build six-fighter lineups under the $50,000 salary cap; opponents are never paired.'
                : 'No current DraftKings MMA pool is available yet. Import a pool when DraftKings publishes it.'}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              aria-label="DraftKings MMA CSV"
              onChange={importFile}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="rounded-lg bg-emerald-600 px-3.5 py-2 text-sm font-semibold text-white transition-colors hover:bg-emerald-500"
            >
              {slate ? 'Change Slate' : 'Import DraftKings CSV'}
            </button>
            <button
              type="button"
              onClick={() => setShowPaste(current => !current)}
              className="rounded-lg border border-zinc-700 px-3.5 py-2 text-sm font-medium text-zinc-300 transition-colors hover:border-zinc-600 hover:text-white"
            >
              Paste CSV
            </button>
          </div>
        </div>

        {showPaste && (
          <div className="mt-4 space-y-2 border-t border-zinc-800 pt-4">
            <label htmlFor="ufc-optimizer-csv" className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
              DraftKings CSV contents
            </label>
            <textarea
              id="ufc-optimizer-csv"
              value={csvText}
              onChange={event => setCsvText(event.target.value)}
              rows={5}
              spellCheck={false}
              placeholder="Position,Name + ID,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame"
              className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 font-mono text-xs text-zinc-300 outline-none focus:border-emerald-500"
            />
            <button
              type="button"
              onClick={() => loadCsv(csvText, 'Pasted DraftKings CSV')}
              className="rounded-lg border border-emerald-500/40 px-3 py-2 text-sm font-semibold text-emerald-400 hover:border-emerald-500"
            >
              Load pasted slate
            </button>
          </div>
        )}

        {importError && (
          <p role="alert" className="mt-4 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-400">
            {importError}
          </p>
        )}
      </section>

      {!slate ? (
        <EmptyOptimizer />
      ) : (
        <>
          <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
              <div>
                <p className="text-sm font-semibold text-zinc-200">
                  {slate.sourceUrl ? (
                    <a href={slate.sourceUrl} target="_blank" rel="noreferrer" className="hover:text-emerald-400">
                      {sourceName}
                    </a>
                  ) : sourceName}
                </p>
                <p className="mt-1 text-xs text-zinc-500">
                  {slate.fighters.length} fighters · {slate.fightCount} fights
                  {slate.source === 'rotowire_snapshot'
                    ? ' · DraftKings salaries and RotoWire projections captured August 25.'
                    : ' · Salary and DK FPPG came from this file.'}
                </p>
                <p className="mt-1 text-xs text-zinc-600">
                  {slate.source === 'rotowire_snapshot'
                    ? `${slate.fighters.filter(fighter => fighter.fppg === null).length} fighters have no published projection and stay out until you enter a target.`
                    : 'Target starts as DraftKings FPPG. It is editable and is not labeled or treated as a projection.'}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Control label="Lineups">
                  <select
                    aria-label="Lineup count"
                    value={lineupCount}
                    onChange={event => {
                      setLineupCount(Number(event.target.value))
                      clearBuild()
                    }}
                    className="control-select"
                  >
                    {LINEUP_COUNTS.map(value => <option key={value} value={value}>{value}</option>)}
                  </select>
                </Control>
                <Control label="Min unique">
                  <select
                    aria-label="Minimum unique fighters"
                    value={minUnique}
                    onChange={event => {
                      setMinUnique(Number(event.target.value))
                      clearBuild()
                    }}
                    className="control-select"
                  >
                    {[1, 2, 3, 4].map(value => <option key={value} value={value}>{value}</option>)}
                  </select>
                </Control>
                <Control label="Max exposure">
                  <select
                    aria-label="Maximum fighter exposure"
                    value={maxExposure}
                    onChange={event => {
                      setMaxExposure(Number(event.target.value))
                      clearBuild()
                    }}
                    className="control-select"
                  >
                    {[25, 50, 75, 100].map(value => <option key={value} value={value}>{value}%</option>)}
                  </select>
                </Control>
                <button
                  type="button"
                  onClick={build}
                  className="self-end rounded-lg bg-emerald-600 px-4 py-2 text-sm font-bold text-white transition-colors hover:bg-emerald-500"
                >
                  Build {lineupCount}
                </button>
              </div>
            </div>
            <p className="mt-3 text-[11px] text-zinc-600">
              Locked fighters can exceed the exposure limit. Exposure applies to every other fighter across this build.
            </p>
            {buildMessage && (
              <p role="status" className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-sm text-amber-300">
                {buildMessage}
              </p>
            )}
          </section>

          <UfcSlateRail
            fighters={slate.fighters}
            slateDate={slate.slateDate}
            selectedFight={selectedFight}
            sort={sortMode}
            onSelectFight={setSelectedFight}
            onSort={setSortMode}
            onChangeSlate={() => fileRef.current?.click()}
          />

          {lineups.length > 0 && (
            <LineupResults lineups={lineups} onDownload={downloadLineups} />
          )}

          <section className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900">
            <div className="flex flex-col gap-3 border-b border-zinc-800 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-sm font-semibold text-zinc-200">
                  Fighter pool{selectedFight ? ` · ${visibleFighters.length}` : ''}
                </h3>
                <p className="mt-0.5 text-xs text-zinc-600">Lock, exclude, or edit the score the optimizer maximizes.</p>
              </div>
              <input
                type="search"
                value={search}
                onChange={event => setSearch(event.target.value)}
                placeholder="Find fighter"
                aria-label="Find fighter"
                className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-300 outline-none focus:border-emerald-500 sm:w-56"
              />
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead className="bg-zinc-950/50 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
                  <tr>
                    <th className="px-4 py-2 text-left">Fighter</th>
                    <th className="px-3 py-2 text-left">Opponent</th>
                    <th className="px-3 py-2 text-right">Salary</th>
                    <th className="px-3 py-2 text-right">{slate.metricLabel}</th>
                    <th className="px-3 py-2 text-right">Value</th>
                    <th className="px-3 py-2 text-right">Target</th>
                    <th className="px-3 py-2 text-center">Lock</th>
                    <th className="px-4 py-2 text-center">Exclude</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/70">
                  {visibleFighters.map(fighter => (
                    <FighterRow
                      key={fighter.id}
                      fighter={fighter}
                      opponentName={fighter.opponentId ? opponentNames.get(fighter.opponentId) || 'Unresolved' : 'Unresolved'}
                      locked={lockedIds.has(fighter.id)}
                      excluded={excludedIds.has(fighter.id)}
                      onTarget={value => updateTarget(fighter.id, value)}
                      onOpen={() => setOverlayFighterId(fighter.id)}
                      onLock={enabled => {
                        setLockedIds(current => replaceInSet(current, fighter.id, enabled))
                        if (enabled) setExcludedIds(current => replaceInSet(current, fighter.id, false))
                        clearBuild()
                      }}
                      onExclude={enabled => {
                        setExcludedIds(current => replaceInSet(current, fighter.id, enabled))
                        if (enabled) setLockedIds(current => replaceInSet(current, fighter.id, false))
                        clearBuild()
                      }}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      {slate && overlayFighter && (
        <UfcFighterOverlay
          fighter={overlayFighter}
          opponent={overlayOpponent}
          metricLabel={slate.metricLabel}
          sourceUrl={slate.sourceUrl}
          sourceDescription={slate.source === 'rotowire_snapshot'
            ? 'Salary, projection, odds, record, and measurements are the August 25 RotoWire snapshot. '
            : 'Salary and DK FPPG came from the imported DraftKings CSV; other details may be unavailable. '}
          locked={lockedIds.has(overlayFighter.id)}
          excluded={excludedIds.has(overlayFighter.id)}
          onTarget={value => updateTarget(overlayFighter.id, value)}
          onLock={enabled => {
            setLockedIds(current => replaceInSet(current, overlayFighter.id, enabled))
            if (enabled) setExcludedIds(current => replaceInSet(current, overlayFighter.id, false))
            clearBuild()
          }}
          onExclude={enabled => {
            setExcludedIds(current => replaceInSet(current, overlayFighter.id, enabled))
            if (enabled) setLockedIds(current => replaceInSet(current, overlayFighter.id, false))
            clearBuild()
          }}
          onClose={() => setOverlayFighterId(null)}
        />
      )}

      <style jsx>{`
        .control-select {
          width: 100%;
          border: 1px solid rgb(63 63 70);
          border-radius: 0.5rem;
          background: rgb(9 9 11);
          padding: 0.5rem 2rem 0.5rem 0.625rem;
          color: rgb(212 212 216);
          font-size: 0.875rem;
          outline: none;
        }
      `}</style>
    </div>
  )
}

function EmptyOptimizer() {
  return (
    <section className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/50 px-5 py-12 text-center">
      <p className="text-sm font-semibold text-zinc-300">DraftKings MMA pool not available yet</p>
      <p className="mx-auto mt-2 max-w-xl text-sm text-zinc-500">
        Download the contest CSV from DraftKings, then import it here. The file stays in this browser and is not written to the database.
      </p>
      <p className="mt-3 text-xs text-zinc-600">
        Required columns: Name, ID, Salary, and Game Info. AvgPointsPerGame is optional.
      </p>
    </section>
  )
}

function Control({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-zinc-600">{label}</span>
      {children}
    </label>
  )
}

function FighterRow({
  fighter,
  opponentName,
  locked,
  excluded,
  onTarget,
  onOpen,
  onLock,
  onExclude,
}: {
  fighter: UfcOptimizerFighter
  opponentName: string
  locked: boolean
  excluded: boolean
  onTarget: (value: string) => void
  onOpen: () => void
  onLock: (enabled: boolean) => void
  onExclude: (enabled: boolean) => void
}) {
  const value = fighter.target === null ? null : fighter.target / (fighter.salary / 1000)
  return (
    <tr className={excluded ? 'opacity-40' : ''} data-fighter-id={fighter.id}>
      <td className="px-4 py-2.5 font-medium text-zinc-200">
        <button type="button" onClick={onOpen} className="text-left hover:text-emerald-400 hover:underline">
          {fighter.name}
        </button>
      </td>
      <td className="px-3 py-2.5 text-zinc-500">{opponentName}</td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-300">{money(fighter.salary)}</td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-500">{score(fighter.fppg)}</td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-500">{score(value)}</td>
      <td className="px-3 py-2">
        <input
          type="number"
          min="0"
          step="0.01"
          value={fighter.target ?? ''}
          aria-label={`Target for ${fighter.name}`}
          onChange={event => onTarget(event.target.value)}
          className="ml-auto block w-20 rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-right font-mono text-sm tabular-nums text-zinc-200 outline-none focus:border-emerald-500"
        />
      </td>
      <td className="px-3 py-2.5 text-center">
        <input
          type="checkbox"
          checked={locked}
          aria-label={`Lock ${fighter.name}`}
          onChange={event => onLock(event.target.checked)}
          className="h-4 w-4 accent-emerald-500"
        />
      </td>
      <td className="px-4 py-2.5 text-center">
        <input
          type="checkbox"
          checked={excluded}
          aria-label={`Exclude ${fighter.name}`}
          onChange={event => onExclude(event.target.checked)}
          className="h-4 w-4 accent-red-500"
        />
      </td>
    </tr>
  )
}

function LineupResults({ lineups, onDownload }: { lineups: UfcOptimizerLineup[]; onDownload: () => void }) {
  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-900" aria-label="Optimized lineups">
      <div className="flex items-center justify-between gap-3 border-b border-zinc-800 px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold text-zinc-200">Optimized lineups</h3>
          <p className="mt-0.5 text-xs text-zinc-600">Ranked by your target score.</p>
        </div>
        <button
          type="button"
          onClick={onDownload}
          className="rounded-lg border border-zinc-700 px-3 py-2 text-xs font-semibold text-zinc-300 hover:border-zinc-600 hover:text-white"
        >
          Export CSV
        </button>
      </div>
      <div className="divide-y divide-zinc-800/70">
        {lineups.map((lineup, index) => (
          <article key={lineup.signature} className="px-4 py-4" data-lineup-index={index + 1}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h4 className="text-sm font-bold text-zinc-200">Lineup {index + 1}</h4>
              <div className="flex gap-4 text-xs tabular-nums text-zinc-500">
                <span>{money(lineup.salary)} salary</span>
                <span>{money(UFC_DK_SALARY_CAP - lineup.salary)} left</span>
                <span className="font-semibold text-emerald-400">{lineup.target.toFixed(2)} target</span>
              </div>
            </div>
            <ol className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
              {lineup.fighters.map(fighter => (
                <li key={fighter.id} className="rounded-lg border border-zinc-800 bg-zinc-950/40 px-3 py-2">
                  <p className="truncate text-xs font-semibold text-zinc-300">{fighter.name}</p>
                  <p className="mt-1 text-[11px] tabular-nums text-zinc-600">{money(fighter.salary)} · {score(fighter.target)}</p>
                </li>
              ))}
            </ol>
          </article>
        ))}
      </div>
    </section>
  )
}
