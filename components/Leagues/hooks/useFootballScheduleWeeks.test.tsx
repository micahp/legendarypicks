import { renderHook, waitFor } from '@testing-library/react'
import { useFootballScheduleWeeks } from './useNflScheduleWeeks'
import { SportsService } from '../../../services/sports'

jest.mock('../../../services/sports', () => ({
  SportsService: {
    getFootballScheduleWeeks: jest.fn(),
    getFootballScheduleWeek: jest.fn(),
  },
  normalizeGame: (game: any, league: string) => ({
    gameId: game.game_id,
    league: league.toUpperCase(),
    homeTeam: { teamId: '', name: '' },
    awayTeam: { teamId: '', name: '' },
    startTime: game.date,
    status: 'SCHEDULED',
  }),
}))

const getWeeks = SportsService.getFootballScheduleWeeks as jest.Mock
const getWeek = SportsService.getFootballScheduleWeek as jest.Mock

describe('week-based football schedule hook', () => {
  beforeEach(() => {
    getWeeks.mockReset()
    getWeek.mockReset()
    getWeeks.mockResolvedValue({
      contract: 'ncaaf-schedule-weeks-v1',
      league: 'ncaaf',
      season: 2026,
      phases: [{ season_type: 2, label: 'Regular Season' }],
      weeks: [{
        key: '2:1', season_type: 2, week: 1, label: 'Week 1',
        alternate_label: 'Week 1', detail: 'Aug 22-Sep 7',
        start_time: '2026-08-22T07:00Z', end_time: '2026-09-08T06:59Z',
      }],
      default_week_key: '2:1',
      default_reason: 'current',
    })
    getWeek.mockResolvedValue({
      games: [{ game_id: '401856766', date: '2026-08-29T16:00Z' }],
    })
  })

  it('loads NCAAF by published week and labels normalized games as NCAAF', async () => {
    const { result } = renderHook(() => useFootballScheduleWeeks('ncaaf', true, null))

    await waitFor(() => expect(result.current.games).toHaveLength(1))
    expect(getWeeks).toHaveBeenCalledWith('ncaaf', expect.any(String))
    expect(getWeek).toHaveBeenCalledWith('ncaaf', 2026, 2, 1)
    expect(result.current.selectedKey).toBe('2:1')
    expect(result.current.games[0].league).toBe('NCAAF')
  })
})
