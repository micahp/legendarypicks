// CFB Playoff Tracker — Week 9 snapshot from @4thQuarterCFB00
// 12 playoff spots, 53 teams in contention, 0 clinched.

interface CfbPlayoffTrackerProps {
  week: number;
  header: string;
  safe: string;
  thin_margin: { count: number; teams: string[] };
  run_the_table: { count: number; teams: string[] };
  must_win_conference: string;
  life_support: { count: number; teams: string[] };
  g6_race: string;
  eliminated: number;
}

export default function CfbPlayoffTrackerTab({
  week = 9,
  header = 'CFB Playoff Tracker — Week 9',
  safe = 'none',
  thin_margin = { count: 8, teams: ['Georgia', 'Indiana', 'Kentucky', 'Miami', 'Nebraska', 'Ohio State', 'UCLA', 'Utah'] },
  run_the_table = { count: 18, teams: ['Alabama', 'BYU', 'Florida', 'Iowa', 'LSU', 'Notre Dame', 'Tennessee', 'Texas', 'USC'] },
  must_win_conference = '0',
  life_support = { count: 17, teams: ['Auburn', 'Cincinnati', 'Clemson', 'Michigan', 'Oregon', 'Washington'] },
  g6_race = 'one spot for the highest-ranked Group of 6 team',
  eliminated = 85,
}) {
  return (
    <div className="p-6 bg-zinc-900 rounded-lg">
      <div className="flex justify-between items-start mb-4">
        <h2 className="text-xl font-medium text-zinc-100">Playoff Tracker</h2>
        <span className="text-sm text-zinc-400">Week {week}</span>
      </div>

      <div className="grid grid-cols-2 gap-4 mb-6">
        <div className="bg-zinc-800 rounded p-4">
          <p className="text-zinc-400 text-sm mb-2">Header</p>
          <p className="font-medium text-zinc-100">{header}</p>
        </div>
        <div className="bg-zinc-800 rounded p-4">
          <p className="text-zinc-400 text-sm mb-2">Playoff spots</p>
          <p className="font-medium text-zinc-100">12</p>
        </div>
        <div className="bg-zinc-800 rounded p-4">
          <p className="text-zinc-400 text-sm mb-2">Teams in contention</p>
          <p className="font-medium text-zinc-100">{eliminated > 0 ? '53' : '—'}</p>
        </div>
        <div className="bg-zinc-800 rounded p-4">
          <p className="text-zinc-400 text-sm mb-2">Clinched</p>
          <p className="font-medium text-zinc-100">{safe}</p>
        </div>
      </div>

      <details className="bg-zinc-800 rounded p-4 mb-4">
        <summary className="cursor-pointer text-zinc-300 font-medium">
          Safe — none
        </summary>
        <p className="text-zinc-300 text-sm mt-1">
          The section says no teams are safe yet.
        </p>
      </details>

      <details className="bg-zinc-800 rounded p-4 mb-4">
        <summary className="cursor-pointer text-zinc-300 font-medium">
          Thin margin — can lose one more game and still be in
        </summary>
        <p className="text-zinc-300 text-sm mt-1">
          <strong>{thin_margin.count}</strong>: {thin_margin.teams.join(', ')}
        </p>
      </details>

      <details className="bg-zinc-800 rounded p-4 mb-4">
        <summary className="cursor-pointer text-zinc-300 font-medium">
          Run the table — must win out to get in
        </summary>
        <p className="text-zinc-300 text-sm mt-1">
          <strong>{run_the_table.count}</strong>: {run_the_table.teams.join(', ')}
        </p>
      </details>

      <details className="bg-zinc-800 rounded p-4 mb-4">
        <summary className="cursor-pointer text-zinc-300 font-medium">
          Must-win conference
        </summary>
        <p className="text-zinc-300 text-sm mt-1">{must_win_conference}</p>
      </details>

      <details className="bg-zinc-800 rounded p-4 mb-4">
        <summary className="cursor-pointer text-zinc-300 font-medium">
          Life support — needs a win plus help
        </summary>
        <p className="text-zinc-300 text-sm mt-1">
          <strong>{life_support.count}</strong>: {life_support.teams.join(', ')}
        </p>
      </details>

      <details className="bg-zinc-800 rounded p-4">
        <summary className="cursor-pointer text-zinc-300 font-medium">
          Group of 6 race
        </summary>
        <p className="text-zinc-300 text-sm mt-1">{g6_race}</p>
      </details>

      <details className="bg-zinc-800 rounded p-4">
        <summary className="cursor-pointer text-zinc-300 font-medium">
          Eliminated
        </summary>
        <p className="text-zinc-300 text-sm mt-1">{eliminated} teams</p>
      </details>
    </div>
  )
}