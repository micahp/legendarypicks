import { useMemo, useState } from 'react'

export interface SlateOfferProp {
  market: string
  line: number
  side: string
  source: string
}

interface SlateOffer {
  key: string
  line: number
  source: string
  over?: SlateOfferProp
  under?: SlateOfferProp
}

interface SlateMarketOffers {
  market: string
  offers: SlateOffer[]
}

function baseMarket(market: string): string {
  return (market || '').split('___')[0].trim().toLowerCase()
}

function label(market: string): string {
  return market.replace(/_/g, ' ')
}

function sourceLabel(source: string): string {
  return source.replace(/^rotowire:/i, '')
}

function formatLine(line: number): string {
  return Number.isInteger(line) ? String(line) : line.toFixed(1)
}

export function groupSlateOffers(props: SlateOfferProp[]): SlateMarketOffers[] {
  const markets = new Map<string, Map<string, SlateOffer>>()
  for (const prop of props) {
    const market = baseMarket(prop.market)
    const offers = markets.get(market) || new Map<string, SlateOffer>()
    const key = `${String(prop.line)}|${prop.source}`
    const offer = offers.get(key) || { key, line: prop.line, source: prop.source }
    const side = prop.side.toLowerCase()
    if (side === 'under' || side === 'no') {
      if (!offer.under) offer.under = prop
    } else if (!offer.over) {
      offer.over = prop
    }
    offers.set(key, offer)
    markets.set(market, offers)
  }
  return Array.from(markets, ([market, offers]) => ({
    market,
    offers: Array.from(offers.values()).sort((a, b) =>
      a.line - b.line || sourceLabel(a.source).localeCompare(sourceLabel(b.source))),
  })).sort((a, b) => a.market.localeCompare(b.market))
}

export default function SlatePlayerOffers({
  playerId,
  playerName,
  props,
  onOpen,
}: {
  playerId: number
  playerName: string
  props: SlateOfferProp[]
  onOpen: (prop: SlateOfferProp) => void
}) {
  const rows = useMemo(() => groupSlateOffers(props), [props])
  const [selectedByMarket, setSelectedByMarket] = useState<Record<string, string>>({})

  return (
    <div data-slate-player-offers className="space-y-2">
      {rows.map(row => {
        const selected = row.offers.find(offer => offer.key === selectedByMarket[row.market])
          || row.offers[0]
        return (
          <div
            key={row.market}
            data-slate-market-row={row.market}
            className="flex min-w-0 flex-wrap items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-950/40 px-2.5 py-2"
          >
            <span className="min-w-[8rem] flex-1 text-[11px] font-medium capitalize text-zinc-300">
              {label(row.market)}
            </span>
            {row.offers.length > 1 ? (
              <details data-slate-line-selector className="relative inline-block">
                <summary
                  aria-label={`Line and provider for ${playerName} ${label(row.market)}`}
                  aria-haspopup="listbox"
                  className="inline-flex cursor-pointer list-none items-center gap-1 rounded px-1.5 py-1 text-xs font-bold text-white tabular-nums marker:content-none"
                >
                  <span data-selected-slate-line>{formatLine(selected.line)}</span>
                  <span aria-hidden="true">▾</span>
                </summary>
                <div
                  role="listbox"
                  aria-label={`Alternate lines for ${playerName} ${label(row.market)}`}
                  className="absolute right-0 z-30 mt-1 min-w-max overflow-hidden rounded-lg border border-zinc-700 bg-zinc-950 py-1 shadow-xl"
                >
                  {row.offers.map(offer => (
                    <button
                      key={offer.key}
                      type="button"
                      role="option"
                      aria-selected={offer.key === selected.key}
                      onClick={event => {
                        setSelectedByMarket(current => ({ ...current, [row.market]: offer.key }))
                        event.currentTarget.closest('details')?.removeAttribute('open')
                      }}
                      className={`block w-full px-3 py-2 text-left text-xs font-medium tabular-nums hover:bg-zinc-800 ${
                        offer.key === selected.key ? 'bg-zinc-800 text-emerald-300' : 'text-zinc-100'
                      }`}
                    >
                      {formatLine(offer.line)} · {sourceLabel(offer.source)}
                    </button>
                  ))}
                </div>
              </details>
            ) : (
              <span className="px-1.5 py-1 text-xs font-bold text-white tabular-nums">
                {formatLine(selected.line)}
              </span>
            )}
            <span className="text-[9px] uppercase tracking-wide text-zinc-600">
              {sourceLabel(selected.source)}
            </span>
            {(['over', 'under'] as const).map(side => {
              const prop = selected[side]
              const tone = side === 'over'
                ? 'bg-emerald-900/30 text-emerald-300 hover:bg-emerald-900/50'
                : 'bg-red-900/30 text-red-300 hover:bg-red-900/50'
              return prop && playerId ? (
                <button
                  key={side}
                  type="button"
                  onClick={() => onOpen(prop)}
                  className={`rounded px-2 py-1 text-[11px] font-mono font-semibold ${tone}`}
                >
                  {side === 'over' ? 'OVER' : 'UNDER'}
                </button>
              ) : prop ? (
                <span key={side} className={`rounded px-2 py-1 text-[11px] font-mono font-semibold ${tone}`}>
                  {side === 'over' ? 'OVER' : 'UNDER'}
                </span>
              ) : null
            })}
          </div>
        )
      })}
    </div>
  )
}
