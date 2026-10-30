import type { HubTab } from './types'

const STORAGE_KEY = 'lp.league-tab-preferences.v1'
export const LEAGUE_TAB_PREFERENCES_CHANGED = 'lp:league-tab-preferences-changed'

const knownTabs = new Set<HubTab>([
  'camp',
  'standings',
  'stats',
  'schedule',
  'model',
  'playoff-odds',
  'playoff-tracker',
  'news',
  'rankings',
  'predict',
  'optimizer',
])

export function readLeagueTabPreferences(): Partial<Record<string, HubTab>> {
  if (typeof window === 'undefined') return {}

  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (!stored) return {}

    const parsed: unknown = JSON.parse(stored)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}

    return Object.fromEntries(
      Object.entries(parsed).filter((entry): entry is [string, HubTab] =>
        typeof entry[0] === 'string' && typeof entry[1] === 'string' && knownTabs.has(entry[1] as HubTab),
      ),
    )
  } catch {
    return {}
  }
}

export function rememberLeagueTab(league: string, tab: HubTab) {
  if (typeof window === 'undefined' || !league || !knownTabs.has(tab)) return

  const preferences = readLeagueTabPreferences()
  preferences[league] = tab

  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences))
  } catch {
    // Keep tab navigation working when browser storage is unavailable.
  }

  window.dispatchEvent(new Event(LEAGUE_TAB_PREFERENCES_CHANGED))
}
