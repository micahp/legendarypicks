export const UFC_DK_ROSTER_SIZE = 6
export const UFC_DK_SALARY_CAP = 50_000

export interface UfcOptimizerFighter {
  id: string
  name: string
  salary: number
  fppg: number | null
  target: number | null
  gameInfo: string
  opponentId: string | null
  startTime?: string | null
  country?: string | null
  record?: string | null
  age?: number | null
  height?: string | null
  reach?: string | null
  weightClass?: string | null
  moneyline?: string | null
}

export interface UfcOptimizerSlate {
  fighters: UfcOptimizerFighter[]
  fightCount: number
  unresolvedMatchups: number
  source: 'draftkings_csv' | 'rotowire_snapshot' | 'rotowire_live'
  sourceName: string
  sourceUrl: string | null
  slateDate: string | null
  capturedAt: string | null
  metricLabel: 'DK FPPG' | 'RW projection'
}

export interface UfcOptimizerLineup {
  fighters: UfcOptimizerFighter[]
  salary: number
  target: number
  signature: string
}

export interface UfcOptimizerOptions {
  count: number
  lockedIds?: Iterable<string>
  excludedIds?: Iterable<string>
  minUnique?: number
  maxExposurePercent?: number
  salaryCap?: number
  rosterSize?: number
}

export interface UfcOptimizerResult {
  lineups: UfcOptimizerLineup[]
  error: string | null
  candidatesConsidered: number
}

export function draftKingsSlateLockAt(slate: UfcOptimizerSlate): number | null {
  const starts = slate.fighters
    .map(fighter => fighter.startTime ? Date.parse(fighter.startTime) : NaN)
    .filter(value => Number.isFinite(value))
  if (starts.length) return Math.min(...starts)
  if (!slate.slateDate) return null
  const endOfDate = Date.parse(`${slate.slateDate}T23:59:59Z`)
  return Number.isFinite(endOfDate) ? endOfDate : null
}

/** Select the next published DraftKings pool; expired embedded pools never win. */
export function selectNextDraftKingsSlate(
  slates: UfcOptimizerSlate[],
  nowMs: number = Date.now(),
): UfcOptimizerSlate | null {
  return slates
    .map(slate => ({ slate, lockAt: draftKingsSlateLockAt(slate) }))
    .filter((item): item is { slate: UfcOptimizerSlate; lockAt: number } => (
      item.lockAt !== null && item.lockAt > nowMs
    ))
    .sort((left, right) => left.lockAt - right.lockAt)[0]?.slate || null
}

const HEADER_ALIASES: Record<string, string[]> = {
  id: ['id'],
  name: ['name'],
  nameAndId: ['name + id', 'name+id'],
  salary: ['salary'],
  gameInfo: ['game info', 'gameinfo'],
  fppg: ['avgpointspergame', 'avg points per game', 'fppg'],
}

function normalizedHeader(value: string): string {
  return value.replace(/^\uFEFF/, '').trim().toLowerCase()
}

function headerIndex(headers: string[], key: keyof typeof HEADER_ALIASES): number {
  const aliases = HEADER_ALIASES[key]
  return headers.findIndex(header => aliases.includes(normalizedHeader(header)))
}

/** RFC-4180-shaped CSV reader. DraftKings names can contain punctuation and the
 * game field contains spaces, so splitting on commas is not a safe import. */
export function parseCsvRows(csv: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false

  for (let index = 0; index < csv.length; index += 1) {
    const char = csv[index]
    if (quoted) {
      if (char === '"' && csv[index + 1] === '"') {
        field += '"'
        index += 1
      } else if (char === '"') {
        quoted = false
      } else {
        field += char
      }
      continue
    }
    if (char === '"') quoted = true
    else if (char === ',') {
      row.push(field)
      field = ''
    } else if (char === '\n' || char === '\r') {
      if (char === '\r' && csv[index + 1] === '\n') index += 1
      row.push(field)
      if (row.some(value => value.trim() !== '')) rows.push(row)
      row = []
      field = ''
    } else field += char
  }

  if (quoted) throw new Error('The CSV ends inside a quoted field.')
  row.push(field)
  if (row.some(value => value.trim() !== '')) rows.push(row)
  return rows
}

function numberFrom(value: string): number | null {
  const trimmed = value.replace(/[$,]/g, '').trim()
  if (!trimmed) return null
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) ? parsed : null
}

function idFromNameAndId(value: string): string {
  const match = value.trim().match(/\(([^()]+)\)\s*$/)
  return match ? match[1].trim() : ''
}

export function parseDraftKingsMmaCsv(csv: string): UfcOptimizerSlate {
  const rows = parseCsvRows(csv)
  if (rows.length < 2) throw new Error('Choose a DraftKings MMA CSV with at least one fighter.')

  const headers = rows[0]
  const indices = {
    id: headerIndex(headers, 'id'),
    name: headerIndex(headers, 'name'),
    nameAndId: headerIndex(headers, 'nameAndId'),
    salary: headerIndex(headers, 'salary'),
    gameInfo: headerIndex(headers, 'gameInfo'),
    fppg: headerIndex(headers, 'fppg'),
  }
  if (indices.name < 0 || indices.salary < 0 || (indices.id < 0 && indices.nameAndId < 0)) {
    throw new Error('The CSV must include Name, Salary, and a DraftKings ID column.')
  }
  if (indices.gameInfo < 0) {
    throw new Error('The CSV must include Game Info so opposing fighters can never share a lineup.')
  }

  const fighters: UfcOptimizerFighter[] = []
  const seen = new Set<string>()
  rows.slice(1).forEach((values, rowOffset) => {
    const name = (values[indices.name] || '').trim()
    const id = indices.id >= 0
      ? (values[indices.id] || '').trim()
      : idFromNameAndId(values[indices.nameAndId] || '')
    const salary = numberFrom(values[indices.salary] || '')
    const gameInfo = (values[indices.gameInfo] || '').trim()
    const fppg = indices.fppg >= 0 ? numberFrom(values[indices.fppg] || '') : null
    if (!name && !id && salary === null) return
    const rowNumber = rowOffset + 2
    if (!name || !id || salary === null || salary <= 0) {
      throw new Error(`Row ${rowNumber} is missing a valid fighter name, DraftKings ID, or salary.`)
    }
    if (!gameInfo) throw new Error(`Row ${rowNumber} has no Game Info matchup.`)
    if (seen.has(id)) throw new Error(`DraftKings fighter ID ${id} appears more than once.`)
    if (fppg !== null && fppg < 0) throw new Error(`Row ${rowNumber} has a negative AvgPointsPerGame value.`)
    seen.add(id)
    fighters.push({ id, name, salary, fppg, target: fppg, gameInfo, opponentId: null })
  })

  if (fighters.length < UFC_DK_ROSTER_SIZE) {
    throw new Error(`The slate needs at least ${UFC_DK_ROSTER_SIZE} fighters.`)
  }
  if (fighters.length > 36) {
    throw new Error('This optimizer supports DraftKings MMA slates of up to 36 fighters.')
  }

  const byGame = new Map<string, UfcOptimizerFighter[]>()
  fighters.forEach(fighter => {
    const group = byGame.get(fighter.gameInfo) || []
    group.push(fighter)
    byGame.set(fighter.gameInfo, group)
  })
  let unresolvedMatchups = 0
  byGame.forEach(group => {
    if (group.length !== 2) {
      unresolvedMatchups += group.length
      return
    }
    group[0].opponentId = group[1].id
    group[1].opponentId = group[0].id
  })

  return {
    fighters,
    fightCount: byGame.size,
    unresolvedMatchups,
    source: 'draftkings_csv',
    sourceName: 'DraftKings CSV',
    sourceUrl: null,
    slateDate: null,
    capturedAt: null,
    metricLabel: 'DK FPPG',
  }
}

function validTarget(fighter: UfcOptimizerFighter): fighter is UfcOptimizerFighter & { target: number } {
  return fighter.target !== null && Number.isFinite(fighter.target) && fighter.target >= 0
}

function lineupRank(left: UfcOptimizerLineup, right: UfcOptimizerLineup): number {
  return right.target - left.target || right.salary - left.salary || left.signature.localeCompare(right.signature)
}

function minHeapPush(heap: UfcOptimizerLineup[], value: UfcOptimizerLineup, limit: number) {
  // The root is the worst retained lineup. This keeps memory bounded without
  // changing the exact best-lineup answer for the ordinary no-exposure case.
  const worseThan = (left: UfcOptimizerLineup, right: UfcOptimizerLineup) => lineupRank(left, right) > 0
  if (heap.length === limit && !worseThan(heap[0], value)) return
  if (heap.length === limit) heap[0] = value
  else heap.push(value)
  let index = heap.length === limit ? 0 : heap.length - 1
  if (heap.length < limit) {
    while (index > 0) {
      const parent = Math.floor((index - 1) / 2)
      if (!worseThan(heap[index], heap[parent])) break
      ;[heap[index], heap[parent]] = [heap[parent], heap[index]]
      index = parent
    }
    return
  }
  while (true) {
    const left = index * 2 + 1
    const right = left + 1
    let worst = index
    if (left < heap.length && worseThan(heap[left], heap[worst])) worst = left
    if (right < heap.length && worseThan(heap[right], heap[worst])) worst = right
    if (worst === index) break
    ;[heap[index], heap[worst]] = [heap[worst], heap[index]]
    index = worst
  }
}

function sharesEnoughFighters(
  lineup: UfcOptimizerLineup,
  selected: UfcOptimizerLineup[],
  rosterSize: number,
  minUnique: number,
): boolean {
  const ids = new Set(lineup.fighters.map(fighter => fighter.id))
  return selected.every(existing => {
    const overlap = existing.fighters.filter(fighter => ids.has(fighter.id)).length
    return rosterSize - overlap >= minUnique
  })
}

export function optimizeUfcLineups(
  fighters: UfcOptimizerFighter[],
  options: UfcOptimizerOptions,
): UfcOptimizerResult {
  const count = Math.max(1, Math.min(150, Math.floor(options.count || 1)))
  const rosterSize = options.rosterSize || UFC_DK_ROSTER_SIZE
  const salaryCap = options.salaryCap || UFC_DK_SALARY_CAP
  const minUnique = Math.max(1, Math.min(rosterSize, Math.floor(options.minUnique || 1)))
  const maxExposurePercent = Math.max(1, Math.min(100, options.maxExposurePercent || 100))
  const lockedIds = new Set(options.lockedIds || [])
  const excludedIds = new Set(options.excludedIds || [])
  const fighterById = new Map(fighters.map(fighter => [fighter.id, fighter]))
  const locked = Array.from(lockedIds).map(id => fighterById.get(id)).filter(Boolean) as UfcOptimizerFighter[]

  if (locked.some(fighter => excludedIds.has(fighter.id))) {
    return { lineups: [], error: 'A fighter cannot be both locked and excluded.', candidatesConsidered: 0 }
  }
  if (locked.length !== lockedIds.size) {
    return { lineups: [], error: 'One or more locked fighter IDs are not in this slate.', candidatesConsidered: 0 }
  }
  if (locked.length > rosterSize) {
    return { lineups: [], error: `You can lock at most ${rosterSize} fighters.`, candidatesConsidered: 0 }
  }
  if (locked.some(fighter => !validTarget(fighter))) {
    return { lineups: [], error: 'Every locked fighter needs a non-negative target score.', candidatesConsidered: 0 }
  }
  const lockedSet = new Set(locked.map(fighter => fighter.id))
  if (locked.some(fighter => fighter.opponentId && lockedSet.has(fighter.opponentId))) {
    return { lineups: [], error: 'Opposing fighters cannot both be locked.', candidatesConsidered: 0 }
  }
  const lockedSalary = locked.reduce((sum, fighter) => sum + fighter.salary, 0)
  if (lockedSalary > salaryCap) {
    return { lineups: [], error: 'Locked fighters exceed the salary cap.', candidatesConsidered: 0 }
  }

  const pool = fighters
    .filter(fighter => !lockedIds.has(fighter.id) && !excludedIds.has(fighter.id) && validTarget(fighter))
    .filter(fighter => !fighter.opponentId || !lockedSet.has(fighter.opponentId))
    .sort((left, right) => (right.target as number) - (left.target as number) || right.salary - left.salary)
  const remaining = rosterSize - locked.length
  if (pool.length < remaining) {
    return { lineups: [], error: 'Not enough eligible fighters have target scores.', candidatesConsidered: 0 }
  }

  const candidateLimit = Math.min(60_000, Math.max(8_000, count * 300))
  const heap: UfcOptimizerLineup[] = []
  let candidatesConsidered = 0
  const chosen: UfcOptimizerFighter[] = []
  const chosenIds = new Set(lockedSet)

  const visit = (start: number, salary: number, target: number) => {
    if (chosen.length === remaining) {
      candidatesConsidered += 1
      const all = [...locked, ...chosen].sort((left, right) => left.name.localeCompare(right.name))
      const signature = all.map(fighter => fighter.id).sort().join('|')
      minHeapPush(heap, { fighters: all, salary, target, signature }, candidateLimit)
      return
    }
    const needed = remaining - chosen.length
    for (let index = start; index <= pool.length - needed; index += 1) {
      const fighter = pool[index]
      if (salary + fighter.salary > salaryCap) continue
      if (fighter.opponentId && chosenIds.has(fighter.opponentId)) continue
      chosen.push(fighter)
      chosenIds.add(fighter.id)
      visit(index + 1, salary + fighter.salary, target + (fighter.target as number))
      chosenIds.delete(fighter.id)
      chosen.pop()
    }
  }
  visit(
    0,
    lockedSalary,
    locked.reduce((sum, fighter) => sum + (fighter.target as number), 0),
  )

  const candidates = heap.sort(lineupRank)
  if (!candidates.length) {
    return { lineups: [], error: `No valid ${rosterSize}-fighter lineup fits under $${salaryCap.toLocaleString()}.`, candidatesConsidered }
  }

  const selected: UfcOptimizerLineup[] = []
  const appearances = new Map<string, number>()
  const maxAppearances = Math.max(1, Math.floor(count * maxExposurePercent / 100))
  for (const lineup of candidates) {
    if (!sharesEnoughFighters(lineup, selected, rosterSize, minUnique)) continue
    if (lineup.fighters.some(fighter => (
      !lockedIds.has(fighter.id) && (appearances.get(fighter.id) || 0) >= maxAppearances
    ))) continue
    selected.push(lineup)
    lineup.fighters.forEach(fighter => appearances.set(fighter.id, (appearances.get(fighter.id) || 0) + 1))
    if (selected.length === count) break
  }

  const error = selected.length < count
    ? `Built ${selected.length} of ${count} requested lineups. Relax uniqueness, exposure, locks, or exclusions for more.`
    : null
  return { lineups: selected, error, candidatesConsidered }
}

function csvCell(value: string | number): string {
  const text = String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

export function lineupsToCsv(lineups: UfcOptimizerLineup[]): string {
  const header = ['Lineup', ...Array.from({ length: UFC_DK_ROSTER_SIZE }, (_, index) => `F${index + 1}`), 'Salary', 'Target']
  return [header, ...lineups.map((lineup, index) => [
    index + 1,
    ...lineup.fighters.map(fighter => `${fighter.name} (${fighter.id})`),
    lineup.salary,
    lineup.target.toFixed(2),
  ])].map(row => row.map(csvCell).join(',')).join('\n')
}
