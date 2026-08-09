import { render, screen } from '@testing-library/react'

import PlayerGameLog from './PlayerGameLog'


function response(body: unknown, ok = true, status = 200): Response {
  return { ok, status, json: async () => body } as Response
}

describe('PlayerGameLog', () => {
  beforeEach(() => {
    ;(global as typeof globalThis & { fetch: jest.Mock }).fetch = jest
      .fn((url: string) => {
        if (url.endsWith('/game-log')) {
          return Promise.resolve(response({
            contract: 'nfl-player-game-log-v1',
            player_id: 469,
            name: 'Josh Allen',
            position: 'QB',
            reference_season: 2025,
            fields: ['cmp', 'att', 'carries'],
            team_games: 3,
            games_played: 3,
            games: [
              { week: 1, played: true, opponent: 'BAL', team: 'BUF', stats: { cmp: 22, att: 31, carries: 8 } },
              { week: 2, played: true, opponent: 'NYJ', team: 'BUF', stats: { cmp: 24, att: 35, carries: 10 } },
              { week: 3, played: true, opponent: 'NE', team: 'BUF', stats: { cmp: 20, att: 28, carries: 6 } },
            ],
          }))
        }
        return Promise.resolve(response({
          season: 2025,
          nfl_schedule_games: [
            { week: 1, phase: 'regular', opponent: 'BAL', home: true },
            { week: 2, phase: 'regular', opponent: 'NYJ', home: false },
          ],
        }))
      })
  })

  afterEach(() => {
    jest.restoreAllMocks()
    delete (global as Partial<typeof globalThis>).fetch
  })

  it('uses readable count labels and marks only published away games', async () => {
    render(<PlayerGameLog playerId={469} />)

    expect(await screen.findByText('@ NYJ')).toBeTruthy()
    expect(screen.getByText('Comp')).toBeTruthy()
    expect(screen.getByText('Att')).toBeTruthy()
    expect(screen.getByText('Car')).toBeTruthy()
    expect(screen.getByText('BAL')).toBeTruthy()
    expect(screen.queryByText('@ BAL')).toBeNull()
    expect(screen.getByText('NE')).toBeTruthy()
    expect(screen.queryByText('@ NE')).toBeNull()
  })
})

describe('PlayerGameLog — soccer (mls)', () => {
  beforeEach(() => {
    ;(global as typeof globalThis & { fetch: jest.Mock }).fetch = jest.fn(() =>
      Promise.resolve(response({
        season: 2025,
        league: 'mls',
        regular_season_games: 4,
        coverage: { game_logs: true },
        recent_games: [
          { date: '2025-10-04', opponent: 'ATX', home: false, game_no: '1', stats: { goals: 0, assists: 1, shots: 2, sot: 1 } },
          { date: '2025-09-27', opponent: 'MIA', home: true, game_no: '2', stats: { goals: 1, assists: 0, shots: 3, sot: 2 } },
          { date: '2025-09-20', opponent: 'LA', home: false, game_no: '3', stats: { goals: 0, assists: 0, shots: 1, sot: 0 } },
        ],
      })),
    )
  })

  afterEach(() => {
    jest.restoreAllMocks()
    delete (global as Partial<typeof globalThis>).fetch
  })

  it('renders goals/assists/shots/SOT with opponent and date instead of week', async () => {
    render(<PlayerGameLog playerId={7} league="mls" />)

    expect(await screen.findByText('G')).toBeTruthy()
    expect(screen.getByText('A')).toBeTruthy()
    expect(screen.getByText('Sh')).toBeTruthy()
    expect(screen.getByText('SOT')).toBeTruthy()
    expect(screen.getByText('Date')).toBeTruthy()
    expect(screen.queryByText('Wk')).toBeNull()
    // Every row is a played row — a substitute appearance is an appearance.
    expect(screen.queryByText('did not play')).toBeNull()
    expect(screen.getByText('@ ATX')).toBeTruthy()
    expect(screen.getByText('MIA')).toBeTruthy()
  })

  it('shows the sample size on the surface when the page is truncated', async () => {
    render(<PlayerGameLog playerId={7} league="mls" />)

    expect(await screen.findByText((_, element) => (
      element?.textContent === '2025 MLS regular season · last 3 of 4 matches'
    ))).toBeTruthy()
  })
})

describe('PlayerGameLog — ncaaf', () => {
  beforeEach(() => {
    ;(global as typeof globalThis & { fetch: jest.Mock }).fetch = jest.fn(() =>
      Promise.resolve(response({
        season: 2025,
        league: 'ncaaf',
        regular_season_games: 3,
        coverage: { game_logs: true },
        recent_games: [
          { date: '2025-11-22', opponent: 'OSU', home: false, game_no: 'e1', stats: { att: 12, pass_yds: 180, pass_td: 2, intc: 0, rush_yds: 21, rush_td: 0 } },
          { date: '2025-11-08', opponent: 'UM', home: true, game_no: 'e2', stats: { att: 9, pass_yds: 140, rush_yds: 10, rec: 1 } },
          { date: '2025-10-25', opponent: 'PSU', home: false, game_no: 'e3', stats: { att: 15, pass_yds: 210, pass_td: 1, intc: 1, rec_yds: 5 } },
        ],
      })),
    )
  })

  afterEach(() => {
    jest.restoreAllMocks()
    delete (global as Partial<typeof globalThis>).fetch
  })

  it('renders the offensive line with distinct rushing and receiving yardage headers', async () => {
    render(<PlayerGameLog playerId={8} league="ncaaf" />)

    expect(await screen.findByText('PaYd')).toBeTruthy()
    expect(screen.getByText('RuYd')).toBeTruthy()
    expect(screen.getByText('ReYd')).toBeTruthy()
    expect(screen.getByText('RuTD')).toBeTruthy()
    // rec_td is absent from every mocked row, so the column is correctly
    // omitted — columns are declared from the keys the logs carry
    // (NEW-LEAGUE-CHECKLIST §4), and no row has a receiving touchdown.
    expect(screen.queryByText('ReTD')).toBeNull()
    expect(screen.getByText('@ OSU')).toBeTruthy()
  })

  it('does not render the N-of-M rate line when the team game count is unknown', async () => {
    render(<PlayerGameLog playerId={8} league="ncaaf" />)

    await screen.findByText('PaYd')
    expect(screen.queryByText(/team games/)).toBeNull()
    expect(screen.queryByText(/missed/)).toBeNull()
    expect(screen.getByText((_, element) => (
      element?.textContent === '2025 NCAAF regular season · 3 games'
    ))).toBeTruthy()
  })
})
