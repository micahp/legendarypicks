import { useCallback, useEffect, useMemo, useState } from 'react'
import type { NflDraftBoard, NflDraftNotes, NflDraftPlayer, NflDraftSort } from '../types'

const POSITIONS = ['all', 'QB', 'RB', 'WR', 'TE', 'FB', 'FLEX'] as const
export type DraftPosition = typeof POSITIONS[number]

// Named for what the reader controls, not for how we compute it.
const SORT_LABELS: Record<NflDraftSort, string> = {
  adp: 'ADP',
  ppr_per_team_game: 'PPR / team game',
  ppr_per_game_played: 'PPR / game played',
  xfp_per_game: 'Expected PPR',
  games_played: 'Availability',
  snap_pct: 'Snap share',
  target_share: 'Target share',
}

const STORAGE_KEY = 'lp_nfl_draft_notes'

function sanitizeNotes(raw: unknown): NflDraftNotes {
  const empty: NflDraftNotes = { rank: {}, watch: {}, fade: {} }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return empty

  const obj = raw as Record<string, unknown>
  const result: NflDraftNotes = { rank: {}, watch: {}, fade: {} }

  for (const bucket of ['rank', 'watch', 'fade'] as const) {
    const bucketVal = obj[bucket]
    if (!bucketVal || typeof bucketVal !== 'object' || Array.isArray(bucketVal)) continue
    const src = bucketVal as Record<string, unknown>
    for (const [key, val] of Object.entries(src)) {
      const pid = Number(key)
      if (!Number.isFinite(pid) || pid <= 0 || pid !== Math.floor(pid)) continue
      // Canonical positive decimal integer only — reject whitespace, 1e2, etc.
      if (!/^[1-9][0-9]*$/.test(key)) continue
      if (!Number.isSafeInteger(pid)) continue
      if (bucket === 'rank') {
        if (typeof val !== 'number' || val < 1 || val > 999 || val !== Math.floor(val)) continue
        result.rank[pid] = val
      } else {
        if (val !== true) continue
        result[bucket][pid] = true
      }
    }
  }
  return result
}

function loadNotes(): NflDraftNotes {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { rank: {}, watch: {}, fade: {} }
    return sanitizeNotes(JSON.parse(raw))
  } catch {
    return { rank: {}, watch: {}, fade: {} }
  }
}

function saveNotes(notes: NflDraftNotes) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(notes))
  } catch { /* storage full — silently degrade */ }
}

export function useNflDraftBoard(enabled: boolean) {
  const [data, setData] = useState<NflDraftBoard | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [position, setPosition] = useState<DraftPosition>('all')
  const [sort, setSort] = useState<NflDraftSort>('adp')
  const [offset, setOffset] = useState(0)
  const [notes, setNotes] = useState<NflDraftNotes>(() => {
    if (typeof window === 'undefined') return { rank: {}, watch: {}, fade: {} }
    return loadNotes()
  })

  const buildUrl = useCallback(() => {
    const params = new URLSearchParams({ sort, limit: '50', offset: String(offset) })
    if (position !== 'all') params.set('position', position)
    return `/api/nfl/draft-board?${params.toString()}`
  }, [position, sort, offset])

  useEffect(() => {
    if (!enabled) {
      setData(null)
      setError(null)
      setLoading(true) // ready for re-entry
      return
    }
    let ignore = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const response = await fetch(buildUrl())
        if (!response.ok) {
          if (!ignore) setError(`Draft board unavailable (${response.status})`)
          return
        }
        const json = await response.json()
        if (!ignore) setData(json)
      } catch {
        if (!ignore) setError('Unable to load draft board.')
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [enabled, buildUrl])

  const selectPosition = useCallback((next: DraftPosition) => {
    setPosition(next)
    setOffset(0)
  }, [])

  const selectSort = useCallback((next: NflDraftSort) => {
    setSort(next)
    setOffset(0)
  }, [])

  const setRank = useCallback((playerId: number, rank: number | null) => {
    setNotes(current => {
      const next = { ...current, rank: { ...current.rank } }
      if (rank === null) {
        delete next.rank[playerId]
      } else {
        next.rank[playerId] = rank
      }
      saveNotes(next)
      return next
    })
  }, [])

  const toggleWatch = useCallback((playerId: number) => {
    setNotes(current => {
      const next = { ...current, watch: { ...current.watch } }
      if (next.watch[playerId]) {
        delete next.watch[playerId]
      } else {
        next.watch[playerId] = true
      }
      saveNotes(next)
      return next
    })
  }, [])

  const toggleFade = useCallback((playerId: number) => {
    setNotes(current => {
      const next = { ...current, fade: { ...current.fade } }
      if (next.fade[playerId]) {
        delete next.fade[playerId]
      } else {
        next.fade[playerId] = true
      }
      saveNotes(next)
      return next
    })
  }, [])

  return {
    data,
    loading,
    error,
    position,
    sort,
    offset,
    notes,
    selectPosition,
    selectSort,
    setOffset,
    setRank,
    toggleWatch,
    toggleFade,
  }
}

export { POSITIONS, SORT_LABELS }
