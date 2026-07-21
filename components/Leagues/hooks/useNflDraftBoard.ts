import { useCallback, useEffect, useMemo, useState } from 'react'
import type { NflDraftBoard, NflDraftNotes, NflDraftPlayer, NflDraftSort } from '../types'

const POSITIONS = ['all', 'QB', 'RB', 'WR', 'TE', 'FB', 'FLEX'] as const
export type DraftPosition = typeof POSITIONS[number]

const SORT_LABELS: Record<NflDraftSort, string> = {
  fantasy_ppr_g: 'PPR/G',
  fantasy_pts_g: 'Pts/G',
  pass_yds_g: 'Pass Yds/G',
  rush_yds_g: 'Rush Yds/G',
  rec_yds_g: 'Rec Yds/G',
  targets: 'Targets',
}

const STORAGE_KEY = 'lp_nfl_draft_notes'

function loadNotes(): NflDraftNotes {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw)
  } catch { /* ignore corrupt data */ }
  return { rank: {}, watch: {}, fade: {} }
}

function saveNotes(notes: NflDraftNotes) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(notes))
  } catch { /* storage full — silently degrade */ }
}

export function useNflDraftBoard() {
  const [data, setData] = useState<NflDraftBoard | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [position, setPosition] = useState<DraftPosition>('all')
  const [sort, setSort] = useState<NflDraftSort>('fantasy_ppr_g')
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
  }, [buildUrl])

  // reset offset when position or sort changes
  const selectPosition = useCallback((next: DraftPosition) => {
    setPosition(next)
    setOffset(0)
  }, [])

  const selectSort = useCallback((next: NflDraftSort) => {
    setSort(next)
    setOffset(0)
  }, [])

  const persist = useCallback((next: NflDraftNotes) => {
    setNotes(next)
    saveNotes(next)
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
