// Free live audio anchor for leagues we can't show on video. World Cup defaults to
// the iHeart FIFA World Cup 2026 station (FOX English); Leagues Cup defaults to
// Unánimo Deportes 990 AM (Miami, Spanish — Inter Miami's radio home). preload=none
// so nothing loads until tapped.
export const WC_STREAM = 'https://stream.revma.ihrhls.com/zc11554'        // iHeart FIFA World Cup 2026 (FOX, AAC)
export const WC_PAGE = 'https://www.iheart.com/live/fifa-world-cup-2026-11554/'
export const LCUP_STREAM = '/api/stream/lcup'   // same-origin ffmpeg relay (STW raw AAC won't play in Chrome)
export const LCUP_PAGE = 'https://www.iheart.com/live/unanimo-deportes-radio-8493/'

export default function ListenLive({
  streamUrl = WC_STREAM,
  streamPageUrl = WC_PAGE,
  pageLabel = 'iHeart ↗',
  label = 'FIFA World Cup · FOX Sports commentary (free)',
}: {
  streamUrl?: string
  streamPageUrl?: string
  pageLabel?: string
  label?: string
}) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm font-semibold text-zinc-100">
          <span aria-hidden>🎧</span> Listen live <span className="font-normal text-zinc-500">· {label}</span>
        </span>
        <a href={streamPageUrl} target="_blank" rel="noreferrer" className="font-mono text-[11px] text-zinc-500 hover:text-emerald-400">{pageLabel}</a>
      </div>
      <audio controls preload="none" src={streamUrl} className="h-9 w-full">
        Your browser can’t play this stream — <a href={streamPageUrl}>open on {pageLabel.replace(' ↗', '')} ↗</a>
      </audio>
    </div>
  )
}
