import React, { useEffect, useState } from 'react'

export type HeroSlide = { label: string; node: React.ReactNode }

const INTERVAL_MS = 8000

// Every slide stays in the page. Only the active one is shown, through the `hidden` attribute on its wrapper.
// The wrapper is a plain div: a grid class on the slide itself would override `hidden`.
// Autoplay pauses while the pointer or keyboard focus is inside, and it does not run when the viewer asks for
// reduced motion.
export default function HeroCarousel({ slides }: { slides: HeroSlide[] }) {
  const [index, setIndex] = useState(0)
  const [paused, setPaused] = useState(false)

  useEffect(() => {
    if (paused || slides.length < 2) return
    const reduce = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduce) return
    const timer = setInterval(() => setIndex((i) => (i + 1) % slides.length), INTERVAL_MS)
    return () => clearInterval(timer)
  }, [paused, slides.length])

  return (
    <div
      role="region"
      aria-roledescription="carousel"
      aria-label="Homepage highlights"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      {slides.map((s, i) => (
        <div
          key={s.label}
          role="group"
          aria-roledescription="slide"
          aria-label={`${i + 1} of ${slides.length}: ${s.label}`}
          hidden={i !== index}
        >
          {s.node}
        </div>
      ))}
      <div className="mt-4 flex items-center justify-center gap-2">
        {slides.map((s, i) => (
          <button
            key={s.label}
            type="button"
            aria-label={`Show ${s.label}`}
            aria-current={i === index ? 'true' : undefined}
            onClick={() => setIndex(i)}
            className={`h-2 rounded-full transition-all ${i === index ? 'w-6 bg-emerald-500' : 'w-2 bg-zinc-600 hover:bg-zinc-500'}`}
          />
        ))}
      </div>
    </div>
  )
}
