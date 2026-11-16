import { useEffect, useState } from 'react'
import type { HubTab } from './types'

const STORAGE_KEY = 'lp.league-tab-preferences.v1'
export const LEAGUE_TAB_PREFERENCES_CHANGED = 'lp:league-tab-preferences-changed'

export type LeagueDestinationTab = HubTab | 'scores' | 'live'

const ACTIVE_MODEL_LEAGUES = new Set(['nba', 'ncaaf', 'nfl', 'nhl', 'tennis'])

export function defaultLeagueTab(league: string): LeagueDestinationTab {
  if (ACTIVE_MODEL_LEAGUES.has(league)) return 'model'
  if (league === 'soccer') return 'scores'
  if (league === 'esports') return 'live'
  return 'schedule'
}

const knownTabs = new Set<HubTab>([
  'camp',
  'standings',
  'stats',
  'schedule',
  'model',
  'playoff-odds',
  'playoff-tracker',
  'cfb-playoff',
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

export function useLeagueTabPreferences() {
  const [tabPreferences, setTabPreferences] = useState<Partial<Record<string, HubTab>>>({})

  useEffect(() => {
    const syncPreferences = () => setTabPreferences(readLeagueTabPreferences())
    syncPreferences()
    window.addEventListener(LEAGUE_TAB_PREFERENCES_CHANGED, syncPreferences)
    window.addEventListener('storage', syncPreferences)
    return () => {
      window.removeEventListener(LEAGUE_TAB_PREFERENCES_CHANGED, syncPreferences)
      window.removeEventListener('storage', syncPreferences)
    }
  }, [])

  return tabPreferences
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
