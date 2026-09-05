import { fireEvent, render, screen } from '@testing-library/react'
import UfcOptimizerTab from './UfcOptimizerTab'

const HEADER = 'Position,Name + ID,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame'
const CSV = [
  HEADER,
  ...Array.from({ length: 6 }, (_, index) => {
    const fight = index + 1
    return [
      `F,"Favorite ${fight} (f${fight})",Favorite ${fight},f${fight},F,8000,A${fight}@B${fight} 08/29/2026,MMA,${100 - fight}`,
      `F,"Underdog ${fight} (u${fight})",Underdog ${fight},u${fight},F,7000,A${fight}@B${fight} 08/29/2026,MMA,${50 - fight}`,
    ]
  }).flat(),
].join('\n')

describe('UFC optimizer tab', () => {
  beforeEach(() => {
    jest.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-08-28T12:00:00Z'))
  })

  afterEach(() => {
    jest.restoreAllMocks()
  })

  it('opens with Saturday loaded and keeps missing projections honest', () => {
    render(<UfcOptimizerTab />)
    const localTwoEastern = new Date('2026-08-29T06:00:00Z').toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })

    expect(screen.getByText('UFC Lineup Optimizer')).toBeTruthy()
    expect(screen.getByText('August 29 DraftKings Classic · UFC Shanghai')).toBeTruthy()
    expect(screen.getByText(/24 fighters · 12 fights/)).toBeTruthy()
    expect(screen.getByText(/2 fighters have no published projection/)).toBeTruthy()
    expect((screen.getByLabelText('Target for Francesco Nuzzi') as HTMLInputElement).value).toBe('')
    expect((screen.getByRole('combobox', { name: 'Sort fighter pool' }) as HTMLSelectElement).value).toBe('game_time')
    expect(screen.getByText('Sort by')).toBeTruthy()
    expect(screen.getByText('12 fights')).toBeTruthy()
    expect(screen.getByRole('option', { name: 'Game Time' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Previous fights' }).closest('[aria-label="Fight rail navigation"]')?.className).toContain('sm:flex')
    expect(screen.getByRole('button', { name: 'Next fights' })).toBeTruthy()
    expect(screen.getAllByRole('button', { name: /^Filter .* versus / }).map(button => button.getAttribute('aria-label'))).toEqual([
      'Filter Kevin Borjas versus Rei Tsuruya',
      'Filter Sean Woodson versus Jack Jenkins',
      'Filter Andre Lima versus Namsrai Batbayar',
      'Filter Julia Polastri versus Jingnan Xiong',
      'Filter Francesco Nuzzi versus Long Xiao',
      'Filter Hector Santiago versus Lawrence Lui',
      'Filter Cameron Nelson versus Ding Meng',
      'Filter Yadong Song versus Umar Nurmagomedov',
      'Filter Denise Gomes versus Yan Xiaonan',
      'Filter Su Mudaerji versus Alex Perez',
      'Filter Kai Asakura versus Aori Qileng',
      'Filter Nilson Rojas versus Bilal Hasan',
    ])
    expect(document.querySelector('[data-slate-fight-rail]')?.className).toContain('[scrollbar-width:none]')
    expect(screen.getAllByText(localTwoEastern)).toHaveLength(7)
    expect(document.querySelector('[data-slate-fight-rail]')?.textContent).not.toContain(' ET')
    expect(screen.queryByText('Optimized lineups')).toBeNull()
  })

  it('filters the fighter pool from the fight rail and clears the filter', () => {
    render(<UfcOptimizerTab />)
    fireEvent.click(screen.getByRole('button', { name: 'Filter Kevin Borjas versus Rei Tsuruya' }))

    expect(document.querySelectorAll('[data-fighter-id]')).toHaveLength(2)
    expect(screen.getByText('Fighter pool · 2')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Clear fight filter ×' }))
    expect(document.querySelectorAll('[data-fighter-id]')).toHaveLength(24)
  })

  it('opens a sourced UFC fighter overlay with optimizer actions', () => {
    render(<UfcOptimizerTab />)
    fireEvent.click(screen.getByRole('button', { name: 'Bilal Hasan' }))

    const dialog = screen.getByRole('dialog', { name: 'Bilal Hasan optimizer details' })
    const localFiveEastern = new Date('2026-08-29T09:00:00Z').toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    expect(dialog.textContent).toContain(`vs Nilson Rojas · ${localFiveEastern}`)
    expect(dialog.textContent).toContain('$9,600')
    expect(dialog.textContent).toContain('87.10')
    expect(dialog.textContent).toContain('-675')
    expect(dialog.textContent).toContain('9-0-0')
    expect(dialog.textContent).toContain('August 25 RotoWire snapshot')
    fireEvent.click(screen.getByRole('button', { name: 'Lock fighter' }))
    expect(screen.getByRole('button', { name: 'Locked' }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Bilal Hasan optimizer details' })).toBeNull()
    expect((screen.getByLabelText('Lock Bilal Hasan') as HTMLInputElement).checked).toBe(true)
  })

  it('builds Saturday lineups without asking the user for a CSV', () => {
    render(<UfcOptimizerTab />)
    fireEvent.click(screen.getByRole('button', { name: 'Build 2' }))

    expect(screen.getByText('Optimized lineups')).toBeTruthy()
    expect(document.querySelectorAll('[data-lineup-index]')).toHaveLength(2)
    const results = screen.getByRole('region', { name: 'Optimized lineups' })
    const pool = screen.getByText('Fighter pool').closest('section')
    expect(results.compareDocumentPosition(pool as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('loads pasted DraftKings data, supports exclusions, and builds lineups', () => {
    render(<UfcOptimizerTab />)
    fireEvent.click(screen.getByRole('button', { name: 'Paste CSV' }))
    fireEvent.change(screen.getByLabelText('DraftKings CSV contents'), { target: { value: CSV } })
    fireEvent.click(screen.getByRole('button', { name: 'Load pasted slate' }))

    expect(screen.getByText('12 fighters · 6 fights · Salary and DK FPPG came from this file.')).toBeTruthy()
    expect(screen.getByText(/is not labeled or treated as a projection/)).toBeTruthy()
    fireEvent.click(screen.getByLabelText('Exclude Favorite 1'))
    fireEvent.click(screen.getByRole('button', { name: 'Build 2' }))

    expect(screen.getByText('Optimized lineups')).toBeTruthy()
    expect(document.querySelectorAll('[data-lineup-index]')).toHaveLength(2)
    document.querySelectorAll('[data-lineup-index]').forEach(lineup => {
      expect(lineup.textContent).not.toContain('Favorite 1')
    })
  })

  it('surfaces opposing locks as a validation error', () => {
    render(<UfcOptimizerTab />)
    fireEvent.click(screen.getByRole('button', { name: 'Paste CSV' }))
    fireEvent.change(screen.getByLabelText('DraftKings CSV contents'), { target: { value: CSV } })
    fireEvent.click(screen.getByRole('button', { name: 'Load pasted slate' }))
    fireEvent.click(screen.getByLabelText('Lock Favorite 1'))
    fireEvent.click(screen.getByLabelText('Lock Underdog 1'))
    fireEvent.click(screen.getByRole('button', { name: 'Build 2' }))

    expect(screen.getByText(/Opposing fighters cannot both be locked/)).toBeTruthy()
    expect(screen.queryByText('Optimized lineups')).toBeNull()
  })

  it('never presents an embedded DraftKings pool after its lock time', () => {
    jest.mocked(Date.now).mockReturnValue(Date.parse('2026-09-05T12:00:00Z'))
    render(<UfcOptimizerTab />)

    expect(screen.getByText('DraftKings MMA pool not available yet')).toBeTruthy()
    expect(screen.getByText(/No current DraftKings MMA pool is available yet/)).toBeTruthy()
    expect(screen.queryByText('August 29 DraftKings Classic · UFC Shanghai')).toBeNull()
    expect(screen.getByRole('button', { name: 'Import DraftKings CSV' })).toBeTruthy()
  })
})
