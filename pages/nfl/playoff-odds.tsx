import Head from 'next/head'
import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'

type OddsTeam = {
  team: string
  team_name: string | null
  conference: string
  division: string
  p_playoffs: number
  p_division: number
  p_bye: number
  p_seed_1: number
  p_seed_2: number
  p_seed_3: number
  p_seed_4: number
  p_seed_5: number
  p_seed_6: number
  p_seed_7: number
  wins_mean: number
  wins_p10: number
  wins_p90: number
  d_playoffs: number | null
}

type OddsData = {
  season: number
  week: number
  model_version: string
  run_id: string
  as_of: string
  teams: OddsTeam[]
}

type LoadResult<T> = { data: T | null; error: string | null }
type PageData = { odds: OddsData | null; errors: string[] }

async function loadJson<T>(url: string, label: string, signal: AbortSignal): Promise<LoadResult<T>> {
  try {
    const response = await fetch(url, { cache: 'no-store', signal })
    if (response.status === 404) return { data: null, error: null }
    if (!response.ok) return { data: null, error: `${label} unavailable (${response.status}).` }
    return { data: await response.json() as T, error: null }
  } catch {
    return { data: null, error: `${label} could not be loaded.` }
  }
}

function pct(value: number | null | undefined, digits = 1) {
  return value == null || !Number.isFinite(value) ? '-' : `${(value * 100).toFixed(digits)}%`
}

function points(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? '-' : value.toFixed(1)
}

function signed(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '-'
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}`
}

function dateTime(value: string | null | undefined) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export default function NflPlayoffOddsPage() {
  const [page, setPage] = useState<PageData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    let ignore = false
    const load = async () => {
      setLoading(true)
      const oddsResult = await loadJson<OddsData>('/api/nfl/playoff-odds', 'Playoff odds', controller.signal)
      if (!ignore) {
        setPage({ odds: oddsResult.data, errors: oddsResult.error ? [oddsResult.error] : [] })
        setLoading(false)
      }
    }
    void load()
    return () => { ignore = true; controller.abort() }
  }, [])

  const conferences = useMemo(() => {
    if (!page?.odds) return []
    return ['AFC', 'NFC'].map(conference => {
      const conferenceTeams = page.odds!.teams.filter(team => team.conference === conference)
      const divisions = Array.from(new Set(conferenceTeams.map(team => team.division))).sort()
      return {
        conference,
        divisions: divisions.map(division => ({
          division,
          teams: conferenceTeams.filter(team => team.division === division)
            .sort((a, b) => b.p_playoffs - a.p_playoffs || a.team.localeCompare(b.team)),
        })),
      }
    })
  }, [page?.odds])

  return (
    <>
      <Head><title>NFL Playoff Odds, Legendary Picks</title></Head>
      <div className="space-y-6">
        <div className="space-y-2">
          <Link href="/leagues/nfl" className="text-sm text-zinc-500 hover:text-zinc-300">
            NFL
          </Link>
          <h1 className="text-3xl font-extrabold tracking-tight">Playoff odds</h1>
          {page?.odds && (
            <p className="text-sm text-zinc-500 tabular-nums">
              {`${page.odds.season} · Week ${page.odds.week} · ${page.odds.model_version} · as of ${dateTime(page.odds.as_of)}`}
            </p>
          )}
        </div>

        <p className="max-w-4xl text-sm leading-6 text-zinc-400">
          Scores-only version 1. Played games keep their results. Each remaining game draws a margin
          from the team ratings, and the two scores are a placeholder split of a fixed total, so the
          points are not a forecast. Game win probabilities and the season record are on the NFL Model tab.
          The team ratings behind this page trail the betting market: in backtests over the 2010 to 2025
          seasons their game probabilities scored worse than the market's in 15 of 16 seasons.
        </p>

        {loading && <div className="h-28 animate-pulse rounded-xl bg-zinc-800" aria-label="Loading NFL playoff odds" />}
        {!loading && page?.errors.map(error => (
          <p key={error} className="text-sm text-zinc-400">{error}</p>
        ))}
        {!loading && page && !page.odds && page.errors.length === 0 && (
          <p className="text-sm text-zinc-500">No complete playoff-odds run has been published yet.</p>
        )}

        {!loading && page?.odds && (
          <>
            <section aria-labelledby="odds-heading" className="space-y-3">
              <div>
                <h2 id="odds-heading" className="text-xl font-bold">Playoff odds by division</h2>
                <p className="mt-1 text-sm text-zinc-500">Projected wins show the mean and 10th–90th percentile.</p>
              </div>
              {conferences.map(({ conference, divisions }) => (
                <div key={conference} className="overflow-hidden rounded-xl bg-zinc-900">
                  <div className="px-4 pt-4 text-sm font-semibold uppercase tracking-wide text-zinc-300">
                    {conference}
                  </div>
                  {divisions.map(({ division, teams }) => (
                    <div key={division} className="px-4 pt-4 last:pb-4">
                      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
                        {division}
                      </h3>
                      <div className="overflow-x-auto">
                        <table className="w-full min-w-[980px] border-collapse text-sm tabular-nums">
                          <thead className="text-xs text-zinc-500">
                            <tr>
                              <th className="pb-2 pr-4 text-left font-medium">Team</th>
                              <th className="pb-2 px-2 text-right font-medium">Playoffs</th>
                              <th className="pb-2 px-2 text-right font-medium">Division</th>
                              <th className="pb-2 px-2 text-right font-medium">Bye</th>
                              {[1, 2, 3, 4, 5, 6, 7].map(seed => (
                                <th key={seed} className="pb-2 px-2 text-right font-medium">Seed {seed}</th>
                              ))}
                              <th className="pb-2 px-2 text-right font-medium">Wins · mean (p10–p90)</th>
                              <th className="pb-2 pl-2 text-right font-medium">Δ playoffs</th>
                            </tr>
                          </thead>
                          <tbody>
                            {teams.map(team => (
                              <tr key={team.team} className="border-t border-zinc-800">
                                <th scope="row" className="py-2.5 pr-4 text-left font-medium text-zinc-100">
                                  <span>{team.team_name || team.team}</span>
                                  {team.team_name && <span className="ml-2 text-xs text-zinc-500">{team.team}</span>}
                                </th>
                                <td className="px-2 py-2.5 text-right">{pct(team.p_playoffs)}</td>
                                <td className="px-2 py-2.5 text-right">{pct(team.p_division)}</td>
                                <td className="px-2 py-2.5 text-right">{pct(team.p_bye)}</td>
                                {[1, 2, 3, 4, 5, 6, 7].map(seed => (
                                  <td key={seed} className="px-2 py-2.5 text-right">
                                    {pct(team[`p_seed_${seed}` as keyof OddsTeam] as number)}
                                  </td>
                                ))}
                                <td className="px-2 py-2.5 text-right">
                                  {points(team.wins_mean)} ({team.wins_p10}–{team.wins_p90})
                                </td>
                                <td className="py-2.5 pl-2 text-right">
                                  {team.d_playoffs == null ? '-' : `${team.d_playoffs > 0 ? '↑ ' : team.d_playoffs < 0 ? '↓ ' : ''}${signed(team.d_playoffs * 100)} pp`}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </section>
          </>
        )}
      </div>
    </>
  )
}
