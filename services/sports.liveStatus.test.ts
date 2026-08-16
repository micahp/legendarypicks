import { normalizeGame } from './sports'

describe('scoreboard live-status normalization', () => {
  it('keeps MLB inning detail separate from ESPN\'s 0:00 display clock', () => {
    const game = normalizeGame({
      game_id: '401816542', state: 'in', period: 6, clock: '0:00', status_detail: 'Top 6th',
      home: { abbrev: 'CHC', name: 'Chicago Cubs', score: 3 },
      away: { abbrev: 'STL', name: 'St. Louis Cardinals', score: 7 },
    }, 'mlb')

    expect(game.livePeriod).toEqual({ type: 'inning', number: 6, display: 'Top 6th', clock: '0:00' })
  })

  it('retains both football quarter and running clock for the card', () => {
    const game = normalizeGame({
      game_id: '401874393', state: 'in', period: 4, clock: '1:51', status_detail: '1:51 - 4th',
      home: { abbrev: 'CHI', name: 'Chicago Bears', score: 34 },
      away: { abbrev: 'CLE', name: 'Cleveland Browns', score: 10 },
    }, 'nfl')

    expect(game.livePeriod).toEqual({ type: 'quarter', number: 4, display: undefined, clock: '1:51' })
  })
})
