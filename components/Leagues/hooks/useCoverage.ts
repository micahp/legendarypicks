import { useEffect, useState } from 'react'

// The enablement registry, client side. See docs/DATA-COVERAGE-CONTRACT.md §4.
//
// ESPN's season dropdown is a published whitelist — `filters.season.options` holds
// exactly the seasons `statisticslog` can fill, so there is no greyed-out season and no
// empty state to design. This is our version of that: a league/season is offered only
// where something checked it against the publisher and said so.
//
// The default when we know nothing is `unverified`, never `complete`. A fetch that
// fails, a route that 404s, a league with no row — all land on "we cannot vouch for
// this", because the alternative is that an outage silently unlocks every season.

// `in_progress` is a season that passes every check but has not ended yet — every
// published game up to the row's `checked_through` is present and paired. It is kept
// distinct from `complete` (season over AND fully checked) and from `partial` (we are
// missing something we should have), because collapsing it into either one loses the
// signal this registry exists to carry.
export type CoverageStatus = 'complete' | 'in_progress' | 'partial' | 'unverified'

export type CoverageRow = {
  league: string
  season: number
  status: CoverageStatus
  expected_games?: number | null
  fetched_games?: number | null
  failure_count?: number | null
  season_start?: string | null
  season_end?: string | null
}

// Relative, like every other hook here — next.config.js rewrites /api/* to the backend.
let cache: CoverageRow[] | null = null
let inflight: Promise<CoverageRow[]> | null = null

function normalize(raw: any): CoverageRow[] {
  const rows = Array.isArray(raw) ? raw : raw?.coverage
  if (!Array.isArray(rows)) return []
  return rows
    .filter((r) => r && typeof r.league === 'string')
    .map((r) => ({
      ...r,
      league: String(r.league).toLowerCase(),
      season: Number(r.season),
      // An unrecognised status is not permission. Anything outside the three-value
      // vocabulary reads as unverified rather than being passed through to a caller
      // that only tests `=== 'complete'`.
      status: (['complete', 'in_progress', 'partial', 'unverified'].includes(r.status)
        ? r.status
        : 'unverified') as CoverageStatus,
    }))
}

export function fetchCoverage(): Promise<CoverageRow[]> {
  if (cache) return Promise.resolve(cache)
  if (!inflight) {
    inflight = fetch('/api/coverage')
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => {
        cache = normalize(d)
        return cache
      })
      .catch(() => [])
      .finally(() => {
        inflight = null
      })
  }
  return inflight
}

/** A status we are willing to put in front of a user. */
export function isVouched(status: CoverageStatus): boolean {
  return status === 'complete' || status === 'in_progress'
}

export function useCoverage() {
  const [rows, setRows] = useState<CoverageRow[] | null>(cache)

  useEffect(() => {
    let live = true
    fetchCoverage().then((r) => {
      if (live) setRows(r)
    })
    return () => {
      live = false
    }
  }, [])

  const loading = rows === null
  const all = rows || []

  const statusFor = (league: string, season?: number): CoverageStatus => {
    const l = league.toLowerCase()
    const matches = all.filter(
      (r) => r.league === l && (season == null || r.season === season),
    )
    if (!matches.length) return 'unverified'
    // With no season named, a league is offerable if any season is vouched for —
    // finished-and-checked, or in progress and current to its own horizon.
    const vouched = matches.find((r) => r.status === 'complete') ||
      matches.find((r) => r.status === 'in_progress')
    return vouched ? vouched.status : matches[0].status
  }

  // Seasons a picker may offer, newest first. Never includes a season we cannot vouch
  // for, so nothing downstream has to remember to check — the option is not there.
  const offerableSeasons = (league: string): number[] =>
    all
      .filter((r) => r.league === league.toLowerCase() && isVouched(r.status))
      .map((r) => r.season)
      .sort((a, b) => b - a)

  const offeredLeagues = all
    .filter((r) => isVouched(r.status))
    .map((r) => r.league)
    .filter((l, i, xs) => xs.indexOf(l) === i)

  return { loading, rows: all, statusFor, offerableSeasons, offeredLeagues }
}
