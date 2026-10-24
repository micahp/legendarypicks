import { unreadNote } from '../components/Leagues/NflScheduleTab'

function unreadDays(count: number, start = '2026-12-18'): string[] {
  const first = Date.parse(`${start}T00:00:00Z`)
  return Array.from({ length: count }, (_, i) =>
    new Date(first + i * 86_400_000).toISOString().slice(0, 10),
  )
}

describe('unreadNote', () => {
  it('names a single unread day as not loaded yet', () => {
    const text = unreadNote('Week 8', ['2026-10-26'])

    expect(text).toContain('Oct 26')
    expect(text).toContain("aren't loaded yet")
  })

  it('names up to seven unread days as not loaded yet', () => {
    const text = unreadNote('CFP', unreadDays(7))

    expect(text).toContain('Dec 18')
    expect(text).toContain('Dec 24')
    expect(text).toContain("aren't loaded yet")
  })

  it('names the week by its label once more than seven days are unread', () => {
    expect(unreadNote('CFP', unreadDays(42))).toBe("Schedule for CFP isn't loaded yet.")
  })

  it('never says a day was not posted, because we may simply not have read it', () => {
    for (const text of [
      unreadNote('Week 8', ['2026-10-26']),
      unreadNote('CFP', unreadDays(7)),
      unreadNote('CFP', unreadDays(42)),
    ]) {
      expect(text.toLowerCase()).not.toContain('posted')
    }
  })
})
