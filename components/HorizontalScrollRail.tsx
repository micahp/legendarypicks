import { ReactNode, useCallback, useEffect, useRef, useState } from 'react'

export default function HorizontalScrollRail({
  children,
  label,
  previousLabel,
  nextLabel,
  className = '',
  railClassName = '',
  stickyControls = false,
}: {
  children: ReactNode
  label: string
  previousLabel: string
  nextLabel: string
  className?: string
  railClassName?: string
  stickyControls?: boolean
}) {
  const railRef = useRef<HTMLDivElement>(null)
  const [canGoBack, setCanGoBack] = useState(false)
  const [canGoForward, setCanGoForward] = useState(false)

  const measureRail = useCallback(() => {
    const rail = railRef.current
    if (!rail) return
    setCanGoBack(rail.scrollLeft > 1)
    setCanGoForward(rail.scrollLeft + rail.clientWidth < rail.scrollWidth - 1)
  }, [])

  useEffect(() => {
    const frame = requestAnimationFrame(measureRail)
    window.addEventListener('resize', measureRail)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', measureRail)
    }
  }, [children, measureRail])

  const moveRail = (direction: -1 | 1) => {
    const rail = railRef.current
    if (!rail) return
    rail.scrollBy({
      left: direction * Math.max(rail.clientWidth * 0.8, 300),
      behavior: 'smooth',
    })
  }

  const controls = (
    <div className="pointer-events-none flex w-full items-center justify-between px-2">
      <button
        type="button"
        aria-label={previousLabel}
        disabled={!canGoBack}
        onClick={() => moveRail(-1)}
        className="pointer-events-auto flex h-9 w-9 items-center justify-center rounded-full border border-zinc-700 bg-zinc-950/95 text-zinc-300 shadow-lg shadow-black/50 backdrop-blur hover:border-zinc-500 hover:bg-zinc-900 hover:text-white disabled:pointer-events-none disabled:opacity-0"
      >
        <span aria-hidden="true">←</span>
      </button>
      <button
        type="button"
        aria-label={nextLabel}
        disabled={!canGoForward}
        onClick={() => moveRail(1)}
        className="pointer-events-auto flex h-9 w-9 items-center justify-center rounded-full border border-zinc-700 bg-zinc-950/95 text-zinc-300 shadow-lg shadow-black/50 backdrop-blur hover:border-zinc-500 hover:bg-zinc-900 hover:text-white disabled:pointer-events-none disabled:opacity-0"
      >
        <span aria-hidden="true">→</span>
      </button>
    </div>
  )

  return (
    <div className={`relative ${className}`}>
      <div
        ref={railRef}
        onScroll={measureRail}
        aria-label={label}
        className={`overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden ${railClassName}`}
      >
        {children}
      </div>
      <div className="pointer-events-none absolute inset-0 hidden sm:block">
        {stickyControls
          ? <div className="sticky top-[50vh] -translate-y-1/2">{controls}</div>
          : <div className="flex h-full items-center">{controls}</div>}
      </div>
    </div>
  )
}
