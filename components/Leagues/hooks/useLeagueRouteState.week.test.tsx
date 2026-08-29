import { act, renderHook, waitFor } from '@testing-library/react'
import { useLeagueRouteState } from './useLeagueRouteState'

const replace = jest.fn()
const push = jest.fn()
const router = {
  isReady: true,
  pathname: '/leagues/[league]',
  query: { league: 'ncaaf', tab: 'schedule', week: '2:1', date: '2026-08-29' } as Record<string, string>,
  replace,
  push,
}

jest.mock('next/router', () => ({ useRouter: () => router }))
jest.mock('./useCoverage', () => ({
  useCoverage: () => ({ loading: false, statusFor: () => 'in_progress' }),
  isVouched: () => true,
}))

describe('week-based league route state', () => {
  beforeEach(() => {
    replace.mockReset()
    push.mockReset()
    router.query = { league: 'ncaaf', tab: 'schedule', week: '2:1', date: '2026-08-29' }
  })

  it('treats NCAAF as week-based and removes date navigation state', async () => {
    const { result } = renderHook(() => useLeagueRouteState())

    await waitFor(() => expect(result.current.scheduleWeek).toBe('2:1'))
    expect(result.current.isWeeklyFootball).toBe(true)
    await waitFor(() => expect(replace).toHaveBeenCalled())
    const replacement = replace.mock.calls[0][0]
    expect(replacement.query.week).toBe('2:1')
    expect(replacement.query.date).toBeUndefined()

    act(() => result.current.selectScheduleWeek('2:2'))
    expect(push).toHaveBeenCalledWith(
      expect.objectContaining({ query: expect.objectContaining({ league: 'ncaaf', tab: 'schedule', week: '2:2' }) }),
      undefined,
      { shallow: true },
    )
    expect(push.mock.calls[0][0].query.date).toBeUndefined()
  })
})
