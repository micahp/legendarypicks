import { useState, useEffect, useRef, useCallback } from 'react'
import type { AllDayCollectionResponse } from '../types'

const FLOW_ADDRESS_RE = /^0x[0-9a-fA-F]{16}$/
const LS_KEY = 'nfl-allday-address'
const DEFAULT_LIMIT = 200
const MAX_LIMIT = 1000

function loadSavedAddress(): string {
  if (typeof window === 'undefined') return ''
  return localStorage.getItem(LS_KEY) || ''
}

function saveAddress(address: string) {
  if (typeof window === 'undefined') return
  localStorage.setItem(LS_KEY, address)
}

export function useAllDayCollection() {
  const [address, setAddress] = useState(loadSavedAddress)
  const [inputValue, setInputValue] = useState('')
  const [data, setData] = useState<AllDayCollectionResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [pageLoading, setPageLoading] = useState(false) // subtle — only on page change
  const [error, setError] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const [limit] = useState(DEFAULT_LIMIT)
  const abortRef = useRef<AbortController | null>(null)

  // Fetch when address or offset changes
  useEffect(() => {
    if (!address || !FLOW_ADDRESS_RE.test(address)) return

    // Abort previous request
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError(null)

    const backend = process.env.NEXT_PUBLIC_API_BASE || ''
    fetch(`${backend}/api/nfl/allday/collection?address=${encodeURIComponent(address)}&limit=${limit}&offset=${offset}`, {
      signal: controller.signal,
    })
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(json => {
        setData(json)
        setLoading(false)
        setPageLoading(false)
      })
      .catch(err => {
        if (err.name === 'AbortError') return
        setError(err.message || 'Failed to load collection')
        setLoading(false)
        setPageLoading(false)
      })

    return () => controller.abort()
  }, [address, offset, limit])

  const submit = useCallback((addr: string) => {
    const trimmed = addr.trim()
    if (!FLOW_ADDRESS_RE.test(trimmed)) {
      setError('Enter a valid Flow address (0x + 16 hex chars)')
      return
    }
    setError(null)
    setOffset(0)  // reset to first page
    saveAddress(trimmed)
    setAddress(trimmed)
  }, [])

  const clear = useCallback(() => {
    setAddress('')
    setInputValue('')
    setData(null)
    setError(null)
    setOffset(0)
    saveAddress('')
  }, [])

  const goToPage = useCallback((newOffset: number) => {
    setOffset(newOffset)
    setPageLoading(true)
  }, [])

  const totalPages = data && data.limit > 0 ? Math.ceil(data.total / data.limit) : 0
  const currentPage = data && data.limit > 0 ? Math.floor(data.offset / data.limit) + 1 : 0

  return {
    address,
    inputValue,
    setInputValue,
    data,
    loading,
    pageLoading,
    error,
    offset,
    limit,
    totalPages,
    currentPage,
    submit,
    clear,
    goToPage,
  }
}
