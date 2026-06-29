import { useState, useEffect } from 'react'

// Module-level cache of resolved stories, keyed by league/gameId. The page renders
// <GameStory> in two layout branches and moves through loading/hydration states, so the
// component remounts a few times per view. Without this, every remount refetched and
// replayed the shimmer→content (the "flicker"). We cache only NON-null results: a null
// (story still generating) stays uncached so a later mount retries.
const storyCache = new Map<string, string>()

export default function GameStory({ league, gameId }: { league: string; gameId: string }) {
  const key = `${league}/${gameId}`
  // undefined = not loaded yet (show shimmer); string = story; null = fetched, no story.
  const [story, setStory] = useState<string | null | undefined>(() => storyCache.get(key))

  useEffect(() => {
    const hit = storyCache.get(key)
    if (hit !== undefined) { setStory(hit); return }   // cached → no refetch, no flicker
    let alive = true
    fetch(`/api/game/${league}/${gameId}/story`)
      .then(r => r.json())
      .then(d => {
        const s: string | null = d.story || null
        if (s) storyCache.set(key, s)
        if (alive) setStory(s)
      })
      .catch(() => { if (alive) setStory(null) })
    return () => { alive = false }
  }, [key, league, gameId])

  // Loading: a subdued shimmer bar that mirrors the story's own border-left accent —
  // not a generic spinner. The emerald line is already the story's signature, so we
  // keep it during loading to signal "content coming here."
  if (story === undefined) return (
    <div className="border-l-2 border-emerald-600/40 pl-3 space-y-2 animate-pulse">
      <div className="h-3 bg-zinc-800 rounded w-full" />
      <div className="h-3 bg-zinc-800 rounded w-3/4" />
    </div>
  )

  if (!story) return null
  return (
    <p className="text-sm text-zinc-300 leading-relaxed border-l-2 border-emerald-600/60 pl-3">{story}</p>
  )
}
