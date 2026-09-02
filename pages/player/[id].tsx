import { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import Head from 'next/head'
import PropChart, { PropHistory } from '../../components/Props/PropChart'
import NflUsageTrend from '../../components/Leagues/NflUsageTrend'
import StatRankCard from '../../components/Leagues/StatRankCard'
import InjuryTag from '../../components/Leagues/InjuryTag'
import { trackPlayerViewed, trackUsageTrendViewed } from '../../lib/analytics'
import { leagueLabel, seasonLabel } from '../../components/Leagues/presentation'

// The page was 891 lines and did four jobs: defined what a player is, formatted
// numbers, drew four game-log tables, and rendered the route. Split 2026-08-04 —
// each piece now lives where you would look for it, and `NflGameLog` is no longer
// something a test has to import from a page file.
import type { PlayerProfile, PropRow } from '../../components/Player/types'

type FetchState = 'loading' | 'ready' | 'not_found' | 'error'
import { STAT_ORDER, TREND, MARKET_STAT, statLabel, statCell, projForMarket } from '../../components/Player/format'
import SeasonStatsSection from '../../components/Player/SeasonStatsSection'
import LeagueGameLog from '../../components/Player/LeagueGameLog'
import { NflGameLog } from '../../components/Player/NflGameLog'
import TabStrip, { playerTabs } from '../../components/Player/TabStrip'
import LogContextSelectors from '../../components/Player/LogContextSelectors'
import type { PlayerTab } from '../../components/Player/TabStrip'

export default function PlayerPage() {
  const router = useRouter()
  const { id } = router.query
  const queryLeague = typeof router.query.league === 'string' ? router.query.league : null
  const querySeason = typeof router.query.season === 'string' ? router.query.season : null
  const [p, setP] = useState<PlayerProfile | null>(null)
  const [state, setState] = useState<FetchState>('loading')
  const [retryTick, setRetryTick] = useState(0)
  const [openProp, setOpenProp] = useState<string | null>(null)
  const [chart, setChart] = useState<PropHistory | null>(null)
  const [tab, setTab] = useState<PlayerTab>('overview')
  const [news, setNews] = useState<{ articles: Array<{ id: number; headline: string; description: string; published: string; link: string; images: Array<{ url: string; caption: string | null }> }> } | null>(null)
  const [newsLoading, setNewsLoading] = useState(false)

  useEffect(() => {
    if (!id) return
    let alive = true
    setState('loading')
    setP(null)
    const params = new URLSearchParams()
    if (queryLeague) params.set('league', queryLeague)
    if (querySeason && /^\d+$/.test(querySeason)) params.set('season', querySeason)
    const query = params.toString()
    fetch(`/api/player/${id}${query ? `?${query}` : ''}`)
      .then(r => {
        if (r.status === 404) { if (alive) setState('not_found'); return null }
        if (!r.ok) { if (alive) setState('error'); return null }
        return r.json()
      })
      .then(d => {
        if (!alive || !d) return
        setP(d)
        setState('ready')
        // Fired on a resolved profile, so 404s and errors are not counted as views.
        trackPlayerViewed({ player_id: String(id), league: d.league || 'unknown', surface: 'player-page' })
      })
      .catch(() => { if (alive) setState('error') })
    return () => { alive = false }
  }, [id, queryLeague, querySeason, retryTick])

  // The standalone player profile is a general sports surface, so its News
  // tab keeps ESPN's athlete-tagged reporting. Fantasy analysis belongs only
  // to the mock-draft overlay.
  useEffect(() => {
    if (tab !== 'news' || !id) return
    let cancelled = false
    setNewsLoading(true)
    fetch(`/api/player/${id}/news?limit=10`)
      .then(res => res.json())
      .then(data => {
        if (!cancelled) {
          setNews(data)
          setNewsLoading(false)
        }
      })
      .catch(() => {
        if (!cancelled) setNewsLoading(false)
      })
    return () => { cancelled = true }
  }, [tab, id])

  const openChart = async (pr: PropRow) => {
    const key = `${pr.market}-${pr.side}`
    if (openProp === key) { setOpenProp(null); setChart(null); return }
    setOpenProp(key); setChart(null)
    try {
      const params = new URLSearchParams({ player_id: String(id), market: pr.market, line: String(pr.line), side: pr.side, league: p?.league || 'mlb' })
      const r = await fetch(`/api/props/history?${params}`)
      if (!r.ok) { setChart(null); return }
      const d = await r.json()
      setChart(d.games?.length ? d : null)
    } catch { setChart(null) }
  }

  if (state === 'loading') return <div className="text-zinc-500 text-sm py-16 text-center">Loading…</div>
  if (state === 'not_found') return <div className="text-zinc-500 text-sm py-16 text-center">Player not found.</div>
  if (state === 'error' || !p) return (
    <div className="text-sm py-16 text-center space-y-2">
      <p className="text-red-400">Couldn’t load this player.</p>
      <button onClick={() => setRetryTick(t => t + 1)} className="text-emerald-400/80 hover:text-emerald-300 text-xs font-medium">
        Retry
      </button>
    </div>
  )

  // UFC's game logs store ESPN's full raw stat blob (43 fields — advances,
  // reversals, slamRate, etc.), not a curated prop-market list like other
  // leagues — this generic table has no way to know which of those are
  // meaningful, so it would dump all 43. Recent Fights (below) already shows
  // the headline UFC stats; skip this section for UFC entirely rather than
  // rendering noise.
  const projKeys = p.league === 'ufc' ? [] : Object.keys(p.projections).sort((a, b) => {
    const ia = STAT_ORDER.indexOf(a), ib = STAT_ORDER.indexOf(b)
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || a.localeCompare(b)
  })

  // NFL splits into tabs; every other league renders the same flat stack it
  // always has, so `show` is unconditionally true off NFL.
  const isNfl = p.league === 'nfl'
  const tabs = playerTabs(p.league, p.recent_games.length > 0)
  // One tab is not a tab strip — a player with nothing but a season line keeps the
  // flat stack rather than being handed a single button that does nothing.
  const tabbed = tabs.length > 1
  const show = (t: PlayerTab) => !tabbed || tab === t
  const nflSchedule = p.nfl_schedule_games ?? []
  const selectedLeague = p.selected_league || p.league

  const selectLogContext = (league: string, season: number) => {
    void router.replace(
      { pathname: router.pathname, query: { id: String(id), league, season: String(season) } },
      undefined,
      { shallow: true },
    )
  }

  return (
    <>
      <Head><title>{p.name} — Legendary Picks</title></Head>
      <div className="space-y-6">
        {/* Header */}
        <div>
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-3xl font-extrabold tracking-tight">{p.name}</h1>
            {isNfl && <InjuryTag status={p.injury_status} />}
          </div>
          <div className="text-sm text-zinc-500 mt-1">
            {[p.team, p.position, leagueLabel(selectedLeague), p.season ? `${seasonLabel(selectedLeague, p.season)} · ${p.regular_season_games} games` : null].filter(Boolean).join(' · ')}
          </div>
        </div>

        <LogContextSelectors
          contexts={p.log_contexts || []}
          league={selectedLeague}
          season={p.season}
          onChange={selectLogContext}
        />

        {tabbed && p.data_status !== 'unavailable' && (
          <TabStrip tabs={tabs} tab={tab} setTab={(t) => {
            // Fired on the move into Usage rather than on render, so the event
            // counts deliberate visits and not every re-render of the tab.
            if (t === 'usage' && tab !== 'usage') {
              trackUsageTrendViewed({ player_id: String(p.id), season: p.season ?? undefined })
            }
            setTab(t)
          }} />
        )}

        {/* Honest empty state: no logs, props, season stats, or ranking on file. */}
        {p.data_status === 'unavailable' && (
          <p className="text-sm text-zinc-500 py-6 text-center border border-zinc-800 rounded-xl bg-zinc-900">
            No stats, game logs, props, or ranking on file for this player yet.
          </p>
        )}

        {show('overview') && p.tennis_ranking && (
          <section>
            <h2 className="mb-2 text-sm font-bold uppercase tracking-wider text-zinc-400">World Ranking</h2>
            <div className="flex items-center justify-between gap-4 rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-3">
              <div>
                <div className="text-sm font-semibold text-zinc-100">{p.tennis_ranking.tour.toUpperCase()} singles</div>
                <div className="mt-1 text-xs text-zinc-500">
                  {p.tennis_ranking.points != null ? `${p.tennis_ranking.points.toLocaleString()} points · ` : ''}
                  ESPN world rankings · Updated {new Date(p.tennis_ranking.captured_at).toLocaleDateString()}
                </div>
              </div>
              <div className="font-mono text-2xl font-bold tabular-nums text-zinc-100">#{p.tennis_ranking.rank}</div>
            </div>
          </section>
        )}

        {/* Season stats: the only meaningful content for stats-only profiles
            (no game-log/props coverage — e.g. NHL/NBA/NFL players synced from
            season totals rather than per-game rows). */}
        {show('overview') && p.season_stats && <SeasonStatsSection league={p.league} seasonStats={p.season_stats} />}

        {/* ESPN-style orange stat block — league rank for the player's position-relevant stats */}
        {show('overview') && p.stat_ranks && Object.keys(p.stat_ranks).length > 0 && (
          <StatRankCard
            statRanks={p.stat_ranks}
            season={p.stat_rank_season}
            games={p.stat_rank_games}
          />
        )}

        {show('overview') && p.props.length > 0 && (
          <section>
            <h2 className="text-sm font-bold text-zinc-400 uppercase tracking-wider mb-2">Current Props</h2>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 divide-y divide-zinc-800">
              {p.props.map((pr, i) => {
                const key = `${pr.market}-${pr.side}`
                return (
                  <div key={i}>
                    <button onClick={() => openChart(pr)} className="w-full flex items-center justify-between px-4 py-3 hover:bg-zinc-800/40 text-sm">
                      <span className="font-medium">{pr.market.replace(/_/g, ' ')}</span>
                      <span className="font-mono tabular-nums text-zinc-300">
                        {pr.side} {pr.line}
                        {(() => { const pj = projForMarket(p.projections, pr.market); return pj ? <span className="ml-2 text-xs text-emerald-400">Proj {pj.projection}</span> : null })()}
                      </span>
                    </button>
                    {openProp === key && (
                      <div className="px-4 pb-4">{chart ? <PropChart data={chart} /> : <div className="text-xs text-zinc-600 py-3">Chart not available for this market.</div>}</div>
                    )}
                  </div>
                )
              })}
            </div>
          </section>
        )}

        {/* Projections */}
        {show('overview') && projKeys.length > 0 && (
          <section>
            <h2 className="text-sm font-bold text-zinc-400 uppercase tracking-wider mb-2">Projections</h2>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
              <table className="w-full text-sm">
                <thead><tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
                  <th className="text-left px-4 py-3 font-medium">Stat</th>
                  <th className="text-right px-3 py-3 font-medium">Proj</th>
                  <th className="text-right px-3 py-3 font-medium">Median</th>
                  <th className="text-right px-3 py-3 font-medium">Floor–Ceil</th>
                  <th className="text-right px-3 py-3 font-medium">L5</th>
                  <th className="text-center px-3 py-3 font-medium">Trend</th>
                </tr></thead>
                <tbody>
                  {projKeys.map(k => { const pj = p.projections[k]; return (
                    <tr key={k} className="border-b border-zinc-800/50">
                      <td className="px-4 py-2.5 font-medium">{k.replace(/_/g, ' ')}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums font-bold text-emerald-300">{pj.projection}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-400">{pj.median}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-500">{pj.floor}–{pj.ceiling}</td>
                      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{pj.l5_avg}</td>
                      <td className="px-3 py-2.5 text-center text-lg">{TREND[pj.trend] || '→'}</td>
                    </tr>
                  )})}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Usage trend — NFL specific. Season is left unset so the endpoint
            resolves the player's most recent season with logs (the page is
            reachable in the off-season, when the current season has none). */}
        {isNfl && tab === 'usage' && (
          <section>
            {/* No section heading and no identity line — the tab label names the
                section and the page header names the player. */}
            <NflUsageTrend playerId={p.id} showHeader={false} />
          </section>
        )}

        {/* Recent fights — UFC specific */}
        {p.league === 'ufc' && p.recent_games.length > 0 && (
          <section>
            <h2 className="text-sm font-bold text-zinc-400 uppercase tracking-wider mb-2">Recent Fights</h2>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
                    <th className="text-left py-3 pl-4 pr-2">Opponent</th>
                    <th className="text-left py-3 px-2">Date</th>
                    <th className="text-center py-3 px-2 w-12">Result</th>
                    <th className="text-right py-3 px-2">Sig Str</th>
                    <th className="text-right py-3 pr-4">Takedowns</th>
                  </tr>
                </thead>
                <tbody>
                  {p.recent_games.map((g, i) => {
                    const s = g.stats as Record<string, number | string>
                    const result = (s.result as string) || ''
                    const sigLanded = s.sigStrikesLanded ?? '—'
                    const sigAttempted = s.sigStrikesAttempted ?? '—'
                    const tdkLanded = s.takedownsLanded ?? '—'
                    const tdkAttempted = s.takedownsAttempted ?? '—'
                    const resultColor =
                      result === 'W' ? 'text-emerald-400' :
                      result === 'L' ? 'text-red-400' :
                      result === 'D' ? 'text-amber-400' : 'text-zinc-500'
                    return (
                      <tr key={i} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                        <td className="py-2.5 pl-4 pr-2 text-zinc-200">{g.opponent || '—'}</td>
                        <td className="py-2.5 px-2 text-zinc-500 text-xs">{g.date || '—'}</td>
                        <td className={`py-2.5 px-2 text-center font-bold ${resultColor}`}>
                          {result || '—'}
                        </td>
                        <td className="py-2.5 px-2 text-right font-mono tabular-nums text-xs text-zinc-300">
                          {typeof sigLanded === 'number' && typeof sigAttempted === 'number'
                            ? `${sigLanded}/${sigAttempted}` : '—'}
                        </td>
                        <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-xs text-zinc-300">
                          {typeof tdkLanded === 'number' && typeof tdkAttempted === 'number'
                            ? `${tdkLanded}/${tdkAttempted}` : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Recent games — generic (non-UFC) */}
        {show('gamelog') && p.league !== 'ufc' && p.recent_games.length > 0 && (
          <section>
            {/* The count is not decoration. `recent_games` is the most recent 25,
                not the season — a header that says "Recent Games" over 25 rows of
                an 82-game season lets the table read as the whole thing. */}
            {!isNfl && (
              <h2 className="mb-2 flex items-baseline gap-2 text-sm font-bold uppercase tracking-wider text-zinc-400">
                Recent Games
                <span className="text-xs font-medium normal-case tracking-normal text-zinc-600">
                  last {p.recent_games.length} of {p.regular_season_games} played
                </span>
              </h2>
            )}
            {isNfl ? (
              <div className="space-y-6">
                {p.postseason_recent_games.length > 0 && (
                  <div>
                    <h2 className="text-sm font-bold text-zinc-400 uppercase tracking-wider mb-2">
                      {p.season != null ? `${p.season} ` : ''}Postseason
                    </h2>
                    <NflGameLog
                      games={p.postseason_recent_games}
                      scheduleGames={nflSchedule.filter(game => game.phase === 'postseason')}
                      position={p.position}
                    />
                  </div>
                )}
                <div>
                  <h2 className="text-sm font-bold text-zinc-400 uppercase tracking-wider mb-2">
                    {p.season != null ? `${p.season} ` : ''}Regular Season
                  </h2>
                  <NflGameLog
                    games={p.recent_games}
                    scheduleGames={nflSchedule.filter(game => game.phase === 'regular')}
                    fillMissed
                    position={p.position}
                  />
                </div>
                {p.preseason_recent_games.length > 0 && (
                  <div>
                    <h2 className="text-sm font-bold text-zinc-400 uppercase tracking-wider mb-2">
                      {p.season != null ? `${p.season} ` : ''}Preseason
                    </h2>
                    <NflGameLog
                      games={p.preseason_recent_games}
                      scheduleGames={nflSchedule.filter(game => game.phase === 'preseason')}
                      position={p.position}
                    />
                  </div>
                )}
              </div>
            ) : (
              <LeagueGameLog
                games={p.recent_games}
                league={selectedLeague}
                identityLeague={p.league}
                position={p.position}
                positionGroup={p.position_group}
              />
            )}
          </section>
        )}

        {/* News tab — NFL only, general player news from ESPN */ }
        {show('news') && isNfl && (
          <section>
            {newsLoading && (
              <div className="space-y-3 animate-pulse">
                {[0, 1, 2].map(i => (
                  <div key={i} className="h-16 rounded-lg bg-zinc-800" />
                ))}
              </div>
            )}
            {!newsLoading && news && news.articles.length === 0 && (
              <div className="text-center py-8 text-zinc-500">
                <p className="text-sm">No recent news for this player</p>
              </div>
            )}
            {!newsLoading && news && news.articles.length > 0 && (
              <div className="space-y-4">
                {news.articles.map(article => (
                  <article
                    key={article.id}
                    className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4 space-y-2"
                  >
                    <a
                      href={article.link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block"
                    >
                      <h4 className="text-sm font-semibold text-zinc-100 hover:text-emerald-400 transition-colors line-clamp-2">
                        {article.headline}
                      </h4>
                      <p className="mt-1 text-xs text-zinc-400 line-clamp-2">
                        {article.description}
                      </p>
                      <time className="block mt-2 text-[10px] text-zinc-600" dateTime={article.published}>
                        {new Date(article.published).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}
                      </time>
                      {article.images[0] && (
                        <img
                          src={article.images[0].url}
                          alt={article.images[0].caption || article.headline}
                          className="mt-2 rounded-lg w-full aspect-video object-cover"
                        />
                      )}
                    </a>
                  </article>
                ))}
              </div>
            )}
          </section>
        )}
      </div>
    </>
  )
}
