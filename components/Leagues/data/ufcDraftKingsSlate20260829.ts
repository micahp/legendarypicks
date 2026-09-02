import type { UfcOptimizerSlate } from '../ufcOptimizer'

/**
 * Pinned Saturday DraftKings Classic slate, captured 2026-08-25.
 *
 * RotoWire slate 533 publishes the DraftKings salary pool as 12 events and 24
 * unique fighter rows. Its public projection response independently reports
 * `source: RotoWire`; those values are labeled as such in the UI. Nuzzi and
 * Xiao publish 0.00, but the reference optimizer omits both from its projected
 * table, so we preserve that absence as null instead of claiming a zero.
 *
 * Source contracts:
 * - https://www.rotowire.com/daily/mma/api/slate-list.php?siteID=1
 * - https://www.rotowire.com/daily/mma/api/players.php?slateID=533
 * - https://www.rotowire.com/daily/mma/api/projections.php?slateID=533&projSource=RotoWire
 */
export const UFC_DK_SLATE_2026_08_29: UfcOptimizerSlate = {
  source: 'rotowire_snapshot',
  sourceName: 'August 29 DraftKings Classic · UFC Shanghai',
  sourceUrl: 'https://www.rotowire.com/daily/mma/optimizer.php',
  slateDate: '2026-08-29',
  capturedAt: '2026-08-25T22:17:00Z',
  metricLabel: 'RW projection',
  fightCount: 12,
  unresolvedMatchups: 0,
  fighters: [
    { id: 'rw:2454', name: 'Kevin Borjas', salary: 6500, fppg: 17.54, target: 17.54, gameInfo: 'rw-event:5432', opponentId: 'rw:2566', startTime: '2026-08-29T06:00:00Z', country: 'Peru', record: '11-5-0', age: 28, height: "5'5", reach: '68"', weightClass: 'Flyweight', moneyline: '+470' },
    { id: 'rw:2566', name: 'Rei Tsuruya', salary: 9700, fppg: 86.67, target: 86.67, gameInfo: 'rw-event:5432', opponentId: 'rw:2454', startTime: '2026-08-29T06:00:00Z', country: 'Japan', record: '11-1-0', age: 24, height: "5'6", reach: '68"', weightClass: 'Flyweight', moneyline: '-650' },
    { id: 'rw:1931', name: 'Sean Woodson', salary: 8400, fppg: 59.68, target: 59.68, gameInfo: 'rw-event:5476', opponentId: 'rw:2368', startTime: '2026-08-29T06:00:00Z', country: 'USA', record: '13-2-1', age: 34, height: "6'2", reach: '79"', weightClass: null, moneyline: '-148' },
    { id: 'rw:2368', name: 'Jack Jenkins', salary: 7800, fppg: 44.64, target: 44.64, gameInfo: 'rw-event:5476', opponentId: 'rw:1931', startTime: '2026-08-29T06:00:00Z', country: 'Australia', record: '14-4-0', age: 32, height: "5'7", reach: '68"', weightClass: null, moneyline: '+124' },
    { id: 'rw:2513', name: 'Andre Lima', salary: 9000, fppg: 73.54, target: 73.54, gameInfo: 'rw-event:5522', opponentId: 'rw:2751', startTime: '2026-08-29T06:00:00Z', country: 'Brazil', record: '11-1-0', age: 27, height: "5'7", reach: '68"', weightClass: 'Flyweight', moneyline: '-278' },
    { id: 'rw:2751', name: 'Namsrai Batbayar', salary: 7200, fppg: 30.77, target: 30.77, gameInfo: 'rw-event:5522', opponentId: 'rw:2513', startTime: '2026-08-29T06:00:00Z', country: 'Mongolia', record: '9-1-0', age: 25, height: "5'4", reach: '68"', weightClass: 'Flyweight', moneyline: '+225' },
    { id: 'rw:2497', name: 'Julia Polastri', salary: 8900, fppg: 72.07, target: 72.07, gameInfo: 'rw-event:5523', opponentId: 'rw:1890', startTime: '2026-08-29T06:00:00Z', country: 'Brazil', record: '14-6-0', age: 28, height: "5'2", reach: '64"', weightClass: 'W Strawweight', moneyline: '-258' },
    { id: 'rw:1890', name: 'Jingnan Xiong', salary: 7300, fppg: 32.26, target: 32.26, gameInfo: 'rw-event:5523', opponentId: 'rw:2497', startTime: '2026-08-29T06:00:00Z', country: 'China', record: '14-2-0', age: 38, height: "5'5", reach: null, weightClass: 'W Strawweight', moneyline: '+210' },
    { id: 'rw:2822', name: 'Francesco Nuzzi', salary: 7600, fppg: null, target: null, gameInfo: 'rw-event:5593', opponentId: 'rw:2548', startTime: '2026-08-29T06:00:00Z', country: 'Italy', record: null, age: 19, height: null, reach: null, weightClass: 'Bantamweight', moneyline: null },
    { id: 'rw:2548', name: 'Long Xiao', salary: 8600, fppg: null, target: null, gameInfo: 'rw-event:5593', opponentId: 'rw:2822', startTime: '2026-08-29T06:00:00Z', country: 'China', record: '27-11-0', age: 28, height: "5'8", reach: '70"', weightClass: 'Bantamweight', moneyline: null },
    { id: 'rw:2820', name: 'Hector Santiago', salary: 7100, fppg: 30.30, target: 30.30, gameInfo: 'rw-event:5594', opponentId: 'rw:2750', startTime: '2026-08-29T06:00:00Z', country: 'Brazil', record: '6-1-0', age: 33, height: "5'6", reach: null, weightClass: 'Bantamweight', moneyline: '+230' },
    { id: 'rw:2750', name: 'Lawrence Lui', salary: 9100, fppg: 74.03, target: 74.03, gameInfo: 'rw-event:5594', opponentId: 'rw:2820', startTime: '2026-08-29T06:00:00Z', country: 'New Zealand', record: '8-1-0', age: 30, height: "5'7", reach: '72"', weightClass: 'Bantamweight', moneyline: '-285' },
    { id: 'rw:2810', name: 'Cameron Nelson', salary: 7900, fppg: 43.48, target: 43.48, gameInfo: 'rw-event:5595', opponentId: 'rw:2777', startTime: '2026-08-29T06:00:00Z', country: 'Canada', record: '7-1-0', age: 28, height: null, reach: null, weightClass: 'Welterweight', moneyline: '+130' },
    { id: 'rw:2777', name: 'Ding Meng', salary: 8300, fppg: 60.78, target: 60.78, gameInfo: 'rw-event:5595', opponentId: 'rw:2810', startTime: '2026-08-29T06:00:00Z', country: 'China', record: '35-10-0', age: 19, height: "6'2", reach: '75"', weightClass: 'Welterweight', moneyline: '-155' },
    { id: 'rw:1457', name: 'Yadong Song', salary: 6700, fppg: 20.83, target: 20.83, gameInfo: 'rw-event:5429', opponentId: 'rw:1415', startTime: '2026-08-29T09:00:00Z', country: 'China', record: '22-10-1 (1 NC)', age: 28, height: "5'8", reach: '67"', weightClass: 'Bantamweight', moneyline: '+380' },
    { id: 'rw:1415', name: 'Umar Nurmagomedov', salary: 9500, fppg: 83.33, target: 83.33, gameInfo: 'rw-event:5429', opponentId: 'rw:1457', startTime: '2026-08-29T09:00:00Z', country: 'Russia', record: '20-1-0', age: 30, height: "5'8", reach: '69"', weightClass: 'Bantamweight', moneyline: '-500' },
    { id: 'rw:2335', name: 'Denise Gomes', salary: 7700, fppg: 44.64, target: 44.64, gameInfo: 'rw-event:5430', opponentId: 'rw:1456', startTime: '2026-08-29T09:00:00Z', country: 'Brazil', record: '12-3-0', age: 26, height: "5'2", reach: '63"', weightClass: 'W Strawweight', moneyline: '+124' },
    { id: 'rw:1456', name: 'Yan Xiaonan', salary: 8500, fppg: 59.68, target: 59.68, gameInfo: 'rw-event:5430', opponentId: 'rw:2335', startTime: '2026-08-29T09:00:00Z', country: 'China', record: '16-5-0 (1 NC)', age: 37, height: "5'5", reach: '63"', weightClass: 'W Strawweight', moneyline: '-148' },
    { id: 'rw:1754', name: 'Su Mudaerji', salary: 8800, fppg: 68.55, target: 68.55, gameInfo: 'rw-event:5431', opponentId: 'rw:1291', startTime: '2026-08-29T09:00:00Z', country: 'China', record: '19-7-0 (1 NC)', age: 30, height: "5'8", reach: '72"', weightClass: 'Flyweight', moneyline: '-218' },
    { id: 'rw:1291', name: 'Alex Perez', salary: 7400, fppg: 35.71, target: 35.71, gameInfo: 'rw-event:5431', opponentId: 'rw:1754', startTime: '2026-08-29T09:00:00Z', country: 'USA', record: '26-10-0 (1 NC)', age: 34, height: "5'6", reach: '65"', weightClass: 'Flyweight', moneyline: '+180' },
    { id: 'rw:2553', name: 'Kai Asakura', salary: 9400, fppg: 81.98, target: 81.98, gameInfo: 'rw-event:5438', opponentId: 'rw:2153', startTime: '2026-08-29T09:00:00Z', country: 'Japan', record: '22-6-0', age: 32, height: "5'8", reach: null, weightClass: 'Bantamweight', moneyline: '-455' },
    { id: 'rw:2153', name: 'Aori Qileng', salary: 6800, fppg: 22.22, target: 22.22, gameInfo: 'rw-event:5438', opponentId: 'rw:2553', startTime: '2026-08-29T09:00:00Z', country: 'China', record: '26-12-0 (1 NC)', age: 33, height: "5'7", reach: '69"', weightClass: 'Bantamweight', moneyline: '+350' },
    { id: 'rw:2815', name: 'Nilson Rojas', salary: 6600, fppg: 16.95, target: 16.95, gameInfo: 'rw-event:5591', opponentId: 'rw:2814', startTime: '2026-08-29T09:00:00Z', country: 'Peru', record: '9-0-0', age: 27, height: "5'5", reach: null, weightClass: 'Flyweight', moneyline: '+490' },
    { id: 'rw:2814', name: 'Bilal Hasan', salary: 9600, fppg: 87.10, target: 87.10, gameInfo: 'rw-event:5591', opponentId: 'rw:2815', startTime: '2026-08-29T09:00:00Z', country: 'USA', record: '9-0-0', age: 25, height: "5'7", reach: null, weightClass: 'Flyweight', moneyline: '-675' },
  ],
}
