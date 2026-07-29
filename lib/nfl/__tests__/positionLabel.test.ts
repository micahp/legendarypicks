import {
  positionLabel,
  positionRankLabel,
  showsPositionalRank,
  orderPositions,
  POSITION_ORDER,
} from '../positionLabel'

describe('positionLabel', () => {
  it('shows a kicker as K, never the stored PK', () => {
    expect(positionLabel('PK')).toBe('K')
  })

  it('shows a defense as D/ST, never the stored DEF', () => {
    expect(positionLabel('DEF')).toBe('D/ST')
  })

  it('leaves every other position exactly as stored', () => {
    for (const pos of ['QB', 'RB', 'WR', 'TE', 'FB', 'FLEX']) {
      expect(positionLabel(pos)).toBe(pos)
    }
  })

  it('renders nothing for a missing position rather than "undefined"', () => {
    expect(positionLabel(null)).toBe('')
    expect(positionLabel(undefined)).toBe('')
    expect(positionLabel('')).toBe('')
  })
})

describe('positionRankLabel', () => {
  it('translates the position inside a positional rank', () => {
    expect(positionRankLabel('PK', 3)).toBe('K3')
    expect(positionRankLabel('WR', 12)).toBe('WR12')
  })

  it('drops the rank when there is none', () => {
    expect(positionRankLabel('PK', null)).toBe('K')
  })

  it('renders nothing without a position', () => {
    expect(positionRankLabel(null, 4)).toBe('')
  })
})

describe('showsPositionalRank', () => {
  it('suppresses the rank for the two positions nobody ranks out loud', () => {
    expect(showsPositionalRank('PK')).toBe(false)
    expect(showsPositionalRank('DEF')).toBe(false)
  })

  it('keeps it everywhere a drafter compares within a position', () => {
    for (const pos of ['QB', 'RB', 'WR', 'TE']) {
      expect(showsPositionalRank(pos)).toBe(true)
    }
  })

  it('is false for a missing position', () => {
    expect(showsPositionalRank(null)).toBe(false)
    expect(showsPositionalRank('')).toBe(false)
  })
})

describe('orderPositions', () => {
  // The bug this replaces: `.sort()` on the stored codes put D/ST and K ahead of
  // the quarterback, and the display map hid why.
  it('returns draft order, not alphabetical order', () => {
    expect(orderPositions(['DEF', 'PK', 'QB', 'RB', 'TE', 'WR'])).toEqual([
      'QB', 'RB', 'WR', 'TE', 'PK', 'DEF',
    ])
  })

  it('omits positions the caller does not have, keeping the rest in order', () => {
    expect(orderPositions(['WR', 'QB'])).toEqual(['QB', 'WR'])
  })

  it('appends an unrecognised position rather than dropping it', () => {
    // Silently losing an option is how a whole position leaves a board with
    // nothing raising, so an unknown code has to remain visible.
    expect(orderPositions(['WR', 'LS', 'QB'])).toEqual(['QB', 'WR', 'LS'])
  })

  it('de-duplicates', () => {
    expect(orderPositions(['RB', 'RB', 'QB'])).toEqual(['QB', 'RB'])
  })

  it('orders every canonical position with the two last-rounds positions last', () => {
    expect(orderPositions(POSITION_ORDER)).toEqual([...POSITION_ORDER])
    expect(POSITION_ORDER[POSITION_ORDER.length - 2]).toBe('PK')
    expect(POSITION_ORDER[POSITION_ORDER.length - 1]).toBe('DEF')
  })
})
