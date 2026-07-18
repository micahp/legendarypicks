import { useCallback, useEffect, useRef, useState } from 'react'
import { getDeviceId } from '../../../lib/deviceId'
import type { HubTab } from '../types'

export type UfcPickSide = 'home' | 'away'
export type UfcPickMethod = 'KO/TKO' | 'SUB' | 'DEC'

export interface UfcFight {
  fightKey: string
  date: string | null
  event: string
  cardSegment: string
  state: 'pre' | 'in' | 'post'
  home: UfcFighter
  away: UfcFighter
  lockAt: number | null
}

export interface UfcFighter {
  id: string
  name: string
  record: string
}

export interface UfcPick {
  fightKey: string
  side: UfcPickSide
  method: UfcPickMethod | null
  fighterName: string
  opponentName: string
  createdAt: number
  lockAt: number | null
  settledAt: number | null
  result: 'win' | 'loss' | 'void' | null
  methodResult: 'win' | 'loss' | null
  points: number | null
}

export interface UfcPickRecord {
  wins: number
  losses: number
  voids: number
  streak: number
}

export interface UfcCrowd {
  countHome: number
  countAway: number
  total: number
  shareHome: number | null
}

const EMPTY_RECORD: UfcPickRecord = { wins: 0, losses: 0, voids: 0, streak: 0 }

export function useUfcPredictData(isUFC: boolean, activeTab: HubTab) {
  const [fights, setFights] = useState<UfcFight[]>([])
  const [myPicks, setMyPicks] = useState<UfcPick[]>([])
  const [record, setRecord] = useState<UfcPickRecord>(EMPTY_RECORD)
  const [crowd, setCrowd] = useState<Record<string, UfcCrowd>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [submittingKey, setSubmittingKey] = useState<string | null>(null)
  const crowdInFlight = useRef<Set<string>>(new Set())

  const loadPicks = useCallback(async () => {
    const response = await fetch('/api/ufc/picks/me', {
      headers: { 'X-Device-Id': getDeviceId() },
    })
    if (!response.ok) throw new Error('Unable to load your UFC picks.')
    const data = await response.json()
    setMyPicks(Array.isArray(data.picks) ? data.picks : [])
    setRecord(data.record || EMPTY_RECORD)
  }, [])

  const fetchCrowd = useCallback(async (fightKey: string) => {
    if (crowdInFlight.current.has(fightKey)) return null
    crowdInFlight.current.add(fightKey)
    try {
      const response = await fetch(`/api/ufc/crowd?fightKey=${encodeURIComponent(fightKey)}`)
      if (!response.ok) return null
      const data: UfcCrowd = await response.json()
      setCrowd(current => ({ ...current, [fightKey]: data }))
      return data
    } catch {
      return null
    } finally {
      crowdInFlight.current.delete(fightKey)
    }
  }, [])

  useEffect(() => {
    if (!isUFC || activeTab !== 'predict') return
    let ignore = false
    const load = async () => {
      setFights([])
      setLoading(true)
      setError(null)
      setActionError(null)
      try {
        const [upcomingResponse, picksResponse] = await Promise.all([
          fetch('/api/ufc/upcoming'),
          fetch('/api/ufc/picks/me', {
            headers: { 'X-Device-Id': getDeviceId() },
          }),
        ])
        if (!upcomingResponse.ok) throw new Error('Unable to load the upcoming UFC card.')
        const upcomingData = await upcomingResponse.json()
        const picksData = picksResponse.ok
          ? await picksResponse.json()
          : { picks: [], record: EMPTY_RECORD }
        if (ignore) return
        setFights(Array.isArray(upcomingData.fights) ? upcomingData.fights : [])
        setMyPicks(Array.isArray(picksData.picks) ? picksData.picks : [])
        setRecord(picksData.record || EMPTY_RECORD)
        if (!picksResponse.ok) setActionError('Unable to load your UFC picks.')
      } catch (loadError: any) {
        if (!ignore) setError(loadError.message || 'Unable to load UFC picks.')
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [isUFC, activeTab])

  useEffect(() => {
    if (!isUFC || activeTab !== 'predict' || fights.length === 0) return
    const currentFightKeys = new Set(fights.map(fight => fight.fightKey))
    const missing = myPicks
      .map(pick => pick.fightKey)
      .filter(fightKey => currentFightKeys.has(fightKey) && !(fightKey in crowd))
    missing.forEach(fightKey => { void fetchCrowd(fightKey) })
  }, [isUFC, activeTab, fights, myPicks, crowd, fetchCrowd])

  const submitPick = useCallback(async (
    fightKey: string,
    side: UfcPickSide,
    method: UfcPickMethod | null,
  ) => {
    setSubmittingKey(fightKey)
    setActionError(null)
    try {
      const response = await fetch('/api/ufc/picks', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Device-Id': getDeviceId(),
        },
        body: JSON.stringify({ fightKey, side, method }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.error || 'Unable to save this pick.')
      }
      setCrowd(current => {
        const next = { ...current }
        delete next[fightKey]
        return next
      })
      await loadPicks()
      return true
    } catch (submitError: any) {
      setActionError(submitError.message || 'Unable to save this pick.')
      return false
    } finally {
      setSubmittingKey(null)
    }
  }, [loadPicks])

  return {
    fights,
    myPicks,
    record,
    crowd,
    loading,
    error,
    actionError,
    submittingKey,
    submitPick,
    fetchCrowd,
  }
}
