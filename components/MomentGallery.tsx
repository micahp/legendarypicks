import { useEffect, useState } from 'react'
import * as fcl from "@onflow/fcl"
import { NBATopShotService } from '../services/nbaTopShot'
import { AccountLinkingService } from '../services/accountLinking'

interface Moment {
  id: number
  metadata: {
    fullName: string
    playType: string
    teamAtMoment: string
    serialNumber: number
    setName: string
    seriesNumber: number
    jerseyNumber?: string
    primaryPosition?: string
    dateOfMoment?: string
    playCategory?: string
    homeTeamName?: string
    awayTeamName?: string
    homeTeamScore?: string
    awayTeamScore?: string
  }
  selected?: boolean
}

export default function MomentGallery() {
  const [moments, setMoments] = useState<Moment[]>([])
  const [user, setUser] = useState<{ addr: string | null }>({ addr: null })
  const [selectedMoments, setSelectedMoments] = useState<number[]>([])
  const [filter, setFilter] = useState<string>('all')
  const [linkedAccounts, setLinkedAccounts] = useState<string[]>([])
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null)
  const [manualAddress, setManualAddress] = useState<string>('')
  const [usingManual, setUsingManual] = useState<boolean>(false)
  const [momentIdsCount, setMomentIdsCount] = useState<number>(0)

  useEffect(() => {
    fcl.currentUser.subscribe(setUser)
  }, [])

  useEffect(() => {
    const fetchLinkedAccounts = async () => {
      if (!user.addr) return
      const accounts = await AccountLinkingService.getLinkedAccounts(user.addr)
      setLinkedAccounts(accounts)
      setSelectedAccount(user.addr)
      setUsingManual(false)
    }

    fetchLinkedAccounts()
  }, [user.addr])

  useEffect(() => {
    const fetchMoments = async () => {
      if (!selectedAccount) return

      const momentIds = await NBATopShotService.getMomentIDs(selectedAccount)
      setMomentIdsCount(Array.isArray(momentIds) ? momentIds.length : 0)
      const momentData = await Promise.all(
        momentIds.map(async (id: number) => {
          const metadata = await NBATopShotService.getMomentMetadata(selectedAccount, id)
          return { id, metadata, selected: false }
        })
      )
      setMoments(momentData.filter(m => m && m.metadata))
    }

    fetchMoments()
  }, [selectedAccount])

  const handleManualSubmit = async () => {
    const addr = manualAddress.trim()
    if (!addr) return
    setUsingManual(true)
    setSelectedAccount(addr)
  }

  const toggleMomentSelection = (momentId: number) => {
    if (selectedMoments.includes(momentId)) {
      setSelectedMoments(selectedMoments.filter(id => id !== momentId))
    } else {
      setSelectedMoments([...selectedMoments, momentId])
    }
  }

  const filterMoments = (moments: Moment[]) => {
    switch (filter) {
      case 'guards':
        return moments.filter(m => m.metadata.primaryPosition?.includes('Guard'))
      case 'forwards':
        return moments.filter(m => m.metadata.primaryPosition?.includes('Forward'))
      case 'centers':
        return moments.filter(m => m.metadata.primaryPosition?.includes('Center'))
      default:
        return moments
    }
  }

  const filteredMoments = filterMoments(moments)

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold">Your NBA Top Shot Collection</h2>
        <div className="text-sm text-zinc-400">
          {user.addr ? (
            <>Connected Address: {user.addr}</>
          ) : (
            <span className="text-amber-500">No wallet connected</span>
          )}
        </div>
        <div className="flex gap-2">
          {!user.addr && (
            <div className="flex items-center gap-2">
              <input
                value={manualAddress}
                onChange={(e) => setManualAddress(e.target.value)}
                placeholder="Paste Flow address (0x...)"
                className="px-3 py-2 w-64 rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-200 placeholder-zinc-500"
              />
              <button
                className="btn-primary"
                onClick={handleManualSubmit}
              >
                Load Moments
              </button>
            </div>
          )}
          {linkedAccounts.length > 0 && (
            <select
              className="px-4 py-2 rounded-lg border border-zinc-800 bg-zinc-900"
              value={selectedAccount || ''}
              onChange={(e) => setSelectedAccount(e.target.value)}
            >
              <option value={user.addr}>Main Account</option>
              {linkedAccounts.map(account => (
                <option key={account} value={account}>
                  Linked Account ({account})
                </option>
              ))}
            </select>
          )}
          <select 
            className="px-4 py-2 rounded-lg border border-zinc-800 bg-zinc-900"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">All Positions</option>
            <option value="guards">Guards</option>
            <option value="forwards">Forwards</option>
            <option value="centers">Centers</option>
          </select>
          {selectedMoments.length > 0 && (
            <button 
              className="btn-primary"
              onClick={() => console.log('Selected moments:', selectedMoments)}
            >
              Create Lineup ({selectedMoments.length})
            </button>
          )}
        </div>
      </div>

      <div className="panel p-4 text-sm">
        <p>Network: {process.env.NEXT_PUBLIC_FLOW_NETWORK}</p>
        <p>Total Moments Found: {momentIdsCount}</p>
        <p>Metadata Resolved: {moments.length}</p>
        <p>Selected Account: {selectedAccount}</p>
        {!user.addr && usingManual && <p>Mode: manual address</p>}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filteredMoments.map((moment) => (
          <div 
            key={moment.id} 
            className={`panel p-4 cursor-pointer transition-all ${
              selectedMoments.includes(moment.id) ? 'ring-2 ring-emerald-400' : 'hover:border-zinc-700'
            }`}
            onClick={() => toggleMomentSelection(moment.id)}
          >
            <div className="flex justify-between items-start">
              <h3 className="text-xl font-bold">{moment.metadata?.fullName ?? `Moment #${moment.id}`}</h3>
              <span className="text-sm px-2 py-1 rounded bg-zinc-800">#{moment.metadata?.jerseyNumber ?? '-'}</span>
            </div>

            <p className="text-zinc-400">{moment.metadata?.primaryPosition ?? ''}</p>

            <div className="mt-2 rounded border border-zinc-800 bg-zinc-900 p-2">
              <p>{moment.metadata?.playType ?? ''} {moment.metadata?.playCategory ? `— ${moment.metadata?.playCategory}` : ''}</p>
              <p className="text-sm text-zinc-400">
                {moment.metadata?.homeTeamName ?? ''} vs {moment.metadata?.awayTeamName ?? ''}
              </p>
              <p className="text-sm text-zinc-400">
                {moment.metadata?.homeTeamScore ?? ''} - {moment.metadata?.awayTeamScore ?? ''}
              </p>
            </div>

            <div className="mt-2 flex justify-between text-sm text-zinc-400">
              <p>Serial: #{moment.metadata?.serialNumber ?? '-'}</p>
              <p>Series {moment.metadata?.seriesNumber ?? '-'}</p>
            </div>

            <p className="text-sm text-zinc-400">{moment.metadata?.setName ?? ''}</p>
          </div>
        ))}
      </div>
    </div>
  )
} 