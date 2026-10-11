import { radioDirectoryForMatchup } from '../lib/radio'

const LANGUAGE_LABELS: Record<string, string> = {
  en: 'English',
  es: 'Spanish',
  pa: 'Punjabi',
}

function sourceAvailability(source: { blackout_risk: string; coverage?: string }): string[] {
  const notes: string[] = []
  if (source.coverage === 'home_matches_only') notes.push('home matches only')
  if (source.blackout_risk === 'geofenced') notes.push('may be geofenced')
  if (source.blackout_risk === 'paid_out_of_market') notes.push('paid out of market')
  if (source.blackout_risk === 'unknown') notes.push('availability unconfirmed')
  return notes
}

export default function RadioSources({ home, away }: {
  home?: string | null
  away?: string | null
}) {
  const entries = radioDirectoryForMatchup(home, away)
  if (!entries.length) return null

  return (
    <div role="group" aria-label="Official radio sources" className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t border-zinc-800 pt-2">
      {entries.map(({ code, team, source }) => {
        const notes = sourceAvailability(source)
        const language = LANGUAGE_LABELS[source.language] || source.language.toUpperCase()
        return (
          <div key={`${code}-${source.language}-${source.label}`} className="flex flex-wrap items-baseline gap-x-1.5 text-[11px]">
            <span className="text-zinc-600">{team}:</span>
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={event => event.stopPropagation()}
              className="text-zinc-400 underline decoration-zinc-700 underline-offset-2 transition-colors hover:text-emerald-400"
            >
              {source.label} · {language} ↗
            </a>
            {notes.map(note => <span key={note} className="text-zinc-600">{note}</span>)}
          </div>
        )
      })}
    </div>
  )
}
