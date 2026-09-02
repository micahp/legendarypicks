import {
  lineupsToCsv,
  optimizeUfcLineups,
  parseDraftKingsMmaCsv,
  type UfcOptimizerFighter,
} from './ufcOptimizer'
import { UFC_DK_SLATE_2026_08_29 } from './data/ufcDraftKingsSlate20260829'

const HEADER = 'Position,Name + ID,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame'

function csvRow(name: string, id: string, salary: number, game: string, fppg: number): string {
  return `F,"${name} (${id})","${name}",${id},F,${salary},"${game}",MMA,${fppg}`
}

function slateCsv(): string {
  const rows = [HEADER]
  for (let fight = 1; fight <= 6; fight += 1) {
    rows.push(csvRow(`Favorite ${fight}`, `f${fight}`, 8000, `A${fight}@B${fight} 08/29/2026`, 100 - fight))
    rows.push(csvRow(`Underdog ${fight}`, `u${fight}`, 7000, `A${fight}@B${fight} 08/29/2026`, 50 - fight))
  }
  return rows.join('\n')
}

describe('DraftKings MMA CSV import', () => {
  it('uses native IDs and maps opponents only through the shared Game Info key', () => {
    const slate = parseDraftKingsMmaCsv(slateCsv())

    expect(slate.fighters).toHaveLength(12)
    expect(slate.fightCount).toBe(6)
    expect(slate.unresolvedMatchups).toBe(0)
    expect(slate.fighters.find(fighter => fighter.id === 'f1')?.opponentId).toBe('u1')
    expect(slate.fighters.find(fighter => fighter.id === 'u1')?.opponentId).toBe('f1')
    expect(slate.fighters.find(fighter => fighter.id === 'f1')?.target).toBe(99)
  })

  it('fails closed when Game Info cannot establish opponent identity', () => {
    const withoutGameInfo = slateCsv().replace(',Game Info,', ',Contest,')
    expect(() => parseDraftKingsMmaCsv(withoutGameInfo)).toThrow(/Game Info/)
  })

  it('rejects duplicate DraftKings fighter IDs instead of joining by name', () => {
    const duplicate = `${slateCsv()}\n${csvRow('Different Name', 'f1', 7600, 'X@Y 08/29/2026', 60)}`
    expect(() => parseDraftKingsMmaCsv(duplicate)).toThrow(/appears more than once/)
  })
})

describe('the pinned August 29 slate', () => {
  it('reconciles all 24 source-native fighters into 12 reciprocal matchups', () => {
    const slate = UFC_DK_SLATE_2026_08_29
    const ids = new Set(slate.fighters.map(fighter => fighter.id))
    const games = new Map<string, typeof slate.fighters>()
    slate.fighters.forEach(fighter => {
      games.set(fighter.gameInfo, [...(games.get(fighter.gameInfo) || []), fighter])
    })

    expect(slate.source).toBe('rotowire_snapshot')
    expect(slate.slateDate).toBe('2026-08-29')
    expect(slate.fighters).toHaveLength(24)
    expect(ids.size).toBe(24)
    expect(games.size).toBe(12)
    expect(slate.fighters.every(fighter => !Number.isNaN(new Date(fighter.startTime || '').getTime()))).toBe(true)
    games.forEach(fighters => {
      expect(fighters).toHaveLength(2)
      expect(fighters[0].opponentId).toBe(fighters[1].id)
      expect(fighters[1].opponentId).toBe(fighters[0].id)
      expect(fighters[0].salary + fighters[1].salary).toBe(16_200)
    })
  })

  it('preserves the two unpublished projections as null rather than zero', () => {
    const unavailable = UFC_DK_SLATE_2026_08_29.fighters
      .filter(fighter => fighter.fppg === null)
      .map(fighter => fighter.name)
      .sort()

    expect(unavailable).toEqual(['Francesco Nuzzi', 'Long Xiao'])
    expect(UFC_DK_SLATE_2026_08_29.fighters.filter(fighter => fighter.fppg !== null)).toHaveLength(22)
  })
})

describe('UFC lineup optimization', () => {
  it('builds the highest-target valid six-fighter lineup under the salary cap', () => {
    const slate = parseDraftKingsMmaCsv(slateCsv())
    const result = optimizeUfcLineups(slate.fighters, { count: 1 })

    expect(result.error).toBeNull()
    expect(result.lineups).toHaveLength(1)
    expect(result.lineups[0].salary).toBe(48_000)
    expect(result.lineups[0].fighters.map(fighter => fighter.id).sort()).toEqual([
      'f1', 'f2', 'f3', 'f4', 'f5', 'f6',
    ])
  })

  it('honors locks and exclusions while still preventing opponent pairs', () => {
    const slate = parseDraftKingsMmaCsv(slateCsv())
    const result = optimizeUfcLineups(slate.fighters, {
      count: 1,
      lockedIds: ['u1'],
      excludedIds: ['f2'],
    })
    const ids = new Set(result.lineups[0].fighters.map(fighter => fighter.id))

    expect(ids.has('u1')).toBe(true)
    expect(ids.has('f1')).toBe(false)
    expect(ids.has('f2')).toBe(false)
    result.lineups[0].fighters.forEach(fighter => {
      expect(fighter.opponentId ? ids.has(fighter.opponentId) : false).toBe(false)
    })
  })

  it('rejects two locked opponents with a specific validation error', () => {
    const slate = parseDraftKingsMmaCsv(slateCsv())
    const result = optimizeUfcLineups(slate.fighters, {
      count: 1,
      lockedIds: ['f1', 'u1'],
    })

    expect(result.lineups).toEqual([])
    expect(result.error).toMatch(/Opposing fighters/)
  })

  it('returns distinct lineups and applies non-locked exposure limits', () => {
    const slate = parseDraftKingsMmaCsv(slateCsv())
    const result = optimizeUfcLineups(slate.fighters, {
      count: 2,
      minUnique: 1,
      maxExposurePercent: 50,
    })

    expect(result.lineups).toHaveLength(2)
    expect(result.lineups[0].signature).not.toBe(result.lineups[1].signature)
    const counts = new Map<string, number>()
    result.lineups.flatMap(lineup => lineup.fighters).forEach(fighter => {
      counts.set(fighter.id, (counts.get(fighter.id) || 0) + 1)
    })
    expect(Math.max(...Array.from(counts.values()))).toBe(1)
  })

  it('reports an impossible salary cap without returning a partial lineup', () => {
    const slate = parseDraftKingsMmaCsv(slateCsv())
    const expensive: UfcOptimizerFighter[] = slate.fighters.map(fighter => ({ ...fighter, salary: 10_000 }))
    const result = optimizeUfcLineups(expensive, { count: 1 })

    expect(result.lineups).toEqual([])
    expect(result.error).toMatch(/No valid 6-fighter lineup/)
  })

  it('exports DraftKings IDs alongside display names', () => {
    const slate = parseDraftKingsMmaCsv(slateCsv())
    const lineup = optimizeUfcLineups(slate.fighters, { count: 1 }).lineups[0]
    const csv = lineupsToCsv([lineup])

    expect(csv).toContain('Favorite 1 (f1)')
    expect(csv.split('\n')[0]).toBe('Lineup,F1,F2,F3,F4,F5,F6,Salary,Target')
  })
})
