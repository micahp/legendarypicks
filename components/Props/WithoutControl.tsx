// The "Without" control on a prop chart: chips for the teammates who missed games this season, and the
// sample behind the selected one. Presentation only; PropChart owns the fetching.

export interface TeammateOut {
  player_id: number
  name: string
  position: string | null
  games_out: number
}

export interface WithoutSample {
  n_games: number
  n_excluded_unknown: number
  n_excluded_not_teammate: number
}

// Under this many games a hit rate is one or two games; say so in words, not only in the count.
export const SMALL_SAMPLE = 5

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

export default function WithoutControl({
  teammates, selected, selectedName, sample, loading, failed, onSelect,
}: {
  teammates: TeammateOut[]
  selected: number | null
  selectedName: string
  sample: WithoutSample | null
  loading: boolean
  failed: boolean
  onSelect: (id: number | null) => void
}) {
  if (!teammates.length && selected === null) return null
  const chip = (on: boolean) =>
    `px-2.5 py-0.5 rounded text-[11px] font-medium transition-colors ${on ? 'bg-zinc-700 text-zinc-200' : 'text-zinc-500 hover:text-zinc-300'}`
  return (
    <div data-without-control className="space-y-1">
      <div className="flex gap-1.5 flex-wrap items-center">
        <span className="text-[11px] text-zinc-500">Without</span>
        {teammates.map(t => (
          <button key={t.player_id} aria-pressed={selected === t.player_id}
            onClick={() => onSelect(selected === t.player_id ? null : t.player_id)}
            className={chip(selected === t.player_id)}
            title={`${t.name}${t.position ? ` (${t.position})` : ''} missed ${plural(t.games_out, 'game')} this player played`}>
            {t.name} <span className="tabular-nums text-zinc-600">{t.games_out}</span>
          </button>
        ))}
      </div>
      {selected !== null && (
        <p data-without-sample className="text-[11px] text-zinc-500 tabular-nums">
          {failed ? (
            <span className="text-amber-400">Could not load the filtered games.</span>
          ) : loading || !sample ? (
            <span>Loading…</span>
          ) : (
            <>
              <span className="text-zinc-300">Without {selectedName}: {plural(sample.n_games, 'game')}</span>
              {sample.n_games < SMALL_SAMPLE && <span> · small sample</span>}
              {sample.n_excluded_unknown > 0 && (
                <span> · {plural(sample.n_excluded_unknown, 'game')} not counted, availability unknown</span>
              )}
            </>
          )}
        </p>
      )}
    </div>
  )
}
