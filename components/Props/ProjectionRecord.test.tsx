import { render, screen, waitFor } from '@testing-library/react'
import ProjectionRecord from './ProjectionRecord'

function mock(body: unknown, ok = true) {
  ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok, json: () => Promise.resolve(body) }))
}

describe('ProjectionRecord', () => {
  it('says no week is graded yet instead of drawing zeros', async () => {
    mock({ season: 2026, weeks: [], note: '' })
    const { container } = render(<ProjectionRecord />)
    await waitFor(() => expect(container.querySelector('[data-record-empty]')).not.toBeNull())
    expect(container.textContent).not.toContain('0.0')
  })

  it('shows every column, bolds the lowest error, and keeps the loss visible', async () => {
    mock({ season: 2026, note: '', weeks: [{
      week: 6, counts: { v2: { graded: 120, dnp: 9 } },
      stats: { rec_yds: { n: 120, v2: { mae: 18.2 }, 'marcel-lite': { mae: 19.1 }, 'espn-weekly': { mae: 17.9 } } },
    }] })
    const { container } = render(<ProjectionRecord />)
    await waitFor(() => expect(container.querySelector('[data-record-week="6"]')).not.toBeNull())
    expect(container.textContent).toContain('120 scored · 9 did not play')
    const cells = Array.from(container.querySelectorAll('tbody td')).map(td => td.textContent)
    expect(cells).toEqual(['Receiving yards', '18.2', '19.1', '17.9', '120'])
    const bold = Array.from(container.querySelectorAll('td.font-semibold')).map(td => td.textContent)
    expect(bold).toEqual(['17.9'])      // ESPN beat us this week and the page says so
  })

  it('shows a dash for a version that projected nothing', async () => {
    mock({ season: 2026, note: '', weeks: [{
      week: 7, counts: { v2: { graded: 5, dnp: 0 } },
      stats: { rec: { n: 5, v2: { mae: 1.2 }, 'marcel-lite': { mae: 1.3 } } },
    }] })
    const { container } = render(<ProjectionRecord />)
    await waitFor(() => expect(container.querySelector('[data-record-week="7"]')).not.toBeNull())
    expect(Array.from(container.querySelectorAll('tbody td')).map(td => td.textContent))
      .toEqual(['Receptions', '1.20', '1.30', '—', '5'])
  })

  it('reports a load failure', async () => {
    mock({}, false)
    const { container } = render(<ProjectionRecord />)
    await waitFor(() => expect(container.querySelector('[data-record-error]')).not.toBeNull())
  })
})
