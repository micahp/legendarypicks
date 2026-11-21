import React from 'react'
import { render, screen, within } from '@testing-library/react'
import { NFLBoxScore, columnTotal } from './BoxScore'
import { BoxScoreData } from './types'

// The columns ESPN publishes for an NFL game (IND at HOU, 2026-11-19, game 401873066), the page in Micah's screenshot.
const PASSING = ['C/ATT', 'YDS', 'AVG', 'TD', 'INT', 'SACKS', 'QBR', 'RTG']
const RUSHING = ['CAR', 'YDS', 'AVG', 'TD', 'LONG']

const DATA: BoxScoreData = {
  available: true,
  teams: [{ name: 'Indianapolis Colts', abbrev: 'IND', stats: [] }, { name: 'Houston Texans', abbrev: 'HOU', stats: [] }],
  players: [
    { team: 'IND', group: 'Passing', columns: PASSING, rows: [
      { name: 'Daniel Jones', position: 'QB', stats: ['12/27', '144', '5.3', '0', '1', '2-15', '14.0', '45.9'] },
      { name: 'Anthony Richardson', position: 'QB', stats: ['0/2', '0', '0.0', '0', '0', '0-0', '4.3', '39.6'] }] },
    { team: 'HOU', group: 'Passing', columns: PASSING, rows: [
      { name: 'C.J. Stroud', position: 'QB', stats: ['21/27', '194', '7.2', '3', '1', '1-7', '79.8', '118.2'] }] },
    { team: 'IND', group: 'Rushing', columns: RUSHING, rows: [
      { name: 'Jonathan Taylor', position: 'RB', stats: ['11', '21', '1.9', '0', '6'] },
      { name: 'Daniel Jones', position: 'QB', stats: ['1', '3', '3.0', '0', '3'] }] },
    { team: 'HOU', group: 'Rushing', columns: RUSHING, rows: [
      { name: 'David Montgomery', position: 'RB', stats: ['26', '107', '4.1', '0', '15'] },
      { name: 'Emari Demercado', position: 'RB', stats: ['5', '33', '6.6', '0', '10'] }] },
  ],
}

describe('columnTotal', () => {
  it('adds counts', () => expect(columnTotal('YDS', ['144', '0'])).toBe('144'))
  it('takes the longest for LONG, never the sum', () => expect(columnTotal('LONG', ['15', '10'])).toBe('15'))
  it('adds both parts of C/ATT and SACKS', () => {
    expect(columnTotal('C/ATT', ['12/27', '0/2'])).toBe('12/29')
    expect(columnTotal('SACKS', ['2-15', '0-0'])).toBe('2-15')
  })
  it('leaves averages and ratings blank', () => {
    for (const column of ['AVG', 'QBR', 'RTG']) expect(columnTotal(column, ['5.3', '4.3'])).toBe('')
  })
  it('leaves a column with text in it blank', () => expect(columnTotal('YDS', ['12', 'n/a'])).toBe(''))
})

describe('NFLBoxScore', () => {
  it('shows one table per group, in reading order, each with every column', () => {
    const { container } = render(<NFLBoxScore data={DATA} />)
    const tables = container.querySelectorAll('table')
    expect(tables).toHaveLength(2)
    expect(container.querySelectorAll('h3')[0].textContent).toBe('Passing')
    expect(container.querySelectorAll('h3')[1].textContent).toBe('Rushing')
    const header = within(tables[0]).getAllByRole('columnheader').map(cell => cell.textContent)
    expect(header).toEqual(['', ...PASSING])
  })

  it('gives each team its own total, from that team only', () => {
    render(<NFLBoxScore data={DATA} />)
    const totals = screen.getAllByText(/total$/).map(cell => (cell.closest('tr') as HTMLElement).textContent)
    // name, then one cell per column; blank cells add nothing to textContent
    expect(totals).toEqual([
      'IND total' + '12/29' + '144' + '' + '0' + '1' + '2-15' + '' + '',
      'HOU total' + '21/27' + '194' + '' + '3' + '1' + '1-7' + '' + '',
      'IND total' + '12' + '24' + '' + '0' + '6',
      'HOU total' + '31' + '140' + '' + '0' + '15',
    ])
  })

  it('never files an unnamed interceptions group under Passing', () => {
    const unnamed: BoxScoreData = { ...DATA, players: [
      { ...DATA.players![0], group: '' },
      { team: 'IND', group: '', columns: ['INT', 'YDS', 'TD'], rows: [{ name: 'A.J. Haulcy', position: 'S', stats: ['1', '2', '0'] }] },
    ] }
    const { container } = render(<NFLBoxScore data={unnamed} />)
    expect(Array.from(container.querySelectorAll('h3')).map(h => h.textContent)).toEqual(['Passing', 'Interceptions'])
    const passing = container.querySelectorAll('table')[0]
    expect(within(passing as HTMLElement).queryByText('A.J. Haulcy')).toBeNull()
  })

  it('shows a group when only the second team has rows, and hides one with none', () => {
    const data: BoxScoreData = { ...DATA, players: [
      { team: 'IND', group: 'Punt Returns', columns: ['NO', 'YDS'], rows: [] },
      { team: 'HOU', group: 'Punt Returns', columns: ['NO', 'YDS'], rows: [{ name: 'Nikko Remigio', position: 'WR', stats: ['1', '9'] }] },
      { team: 'IND', group: 'Fumbles', columns: ['FUM', 'LOST', 'REC'], rows: [] },
      { team: 'HOU', group: 'Fumbles', columns: ['FUM', 'LOST', 'REC'], rows: [] },
    ] }
    const { container } = render(<NFLBoxScore data={data} />)
    expect(Array.from(container.querySelectorAll('h3')).map(h => h.textContent)).toEqual(['Punt Returns'])
    expect(screen.getByText('Nikko Remigio')).toBeTruthy()
  })

  it('puts every player row under its own team', () => {
    const { container } = render(<NFLBoxScore data={DATA} />)
    const rushing = container.querySelectorAll('table')[1]
    const bodies = rushing.querySelectorAll('tbody')
    expect(within(bodies[0] as HTMLElement).getByText('IND')).toBeTruthy()
    expect(within(bodies[0] as HTMLElement).getByText('Jonathan Taylor')).toBeTruthy()
    expect(within(bodies[1] as HTMLElement).getByText('David Montgomery')).toBeTruthy()
  })
})
