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

      console.log("Fetching moments for address:", selectedAccount)
      const momentIds = await NBATopShotService.getMomentIDs(selectedAccount)
      console.log("Found moment IDs:", momentIds)
      setMomentIdsCount(Array.isArray(momentIds) ? momentIds.length : 0)
      
      const momentData = await Promise.all(
        momentIds.map(async (id: number) => {
          const metadata = await NBATopShotService.getMomentMetadata(selectedAccount, id)
          console.log("Moment metadata for ID", id, ":", metadata)
          return { id, metadata, selected: false }
        })
      )

      console.log("Final moment data:", momentData)
      // Filter out items with null/invalid metadata to avoid UI crashes
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
        return moments.filter(m => 
          m.metadata.primaryPosition?.includes('Guard'))
      case 'forwards':
        return moments.filter(m => 
          m.metadata.primaryPosition?.includes('Forward'))
      case 'centers':
        return moments.filter(m => 
          m.metadata.primaryPosition?.includes('Center'))
      default:
        return moments
    }
  }

  // Always render; if not connected, show address input to test retrieval

  const filteredMoments = filterMoments(moments)

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold">Your NBA Top Shot Collection</h2>
        <div className="text-sm text-gray-500">
          {user.addr ? (
            <>Connected Address: {user.addr}</>
          ) : (
            <span className="text-amber-600">No wallet connected</span>
          )}
        </div>
        <div className="flex gap-2">
          {!user.addr && (
            <div className="flex items-center gap-2">
              <input
                value={manualAddress}
                onChange={(e) => setManualAddress(e.target.value)}
                placeholder="Paste Flow address (0x...)"
                className="border rounded-lg px-3 py-2 w-64"
              />
              <button
                className="bg-blue-600 text-white px-3 py-2 rounded-lg"
                onClick={handleManualSubmit}
              >
                Load Moments
              </button>
            </div>
          )}
          {linkedAccounts.length > 0 && (
            <select
              className="border rounded-lg px-4 py-2"
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
            className="border rounded-lg px-4 py-2"
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
              className="bg-green-500 text-white px-4 py-2 rounded-lg"
              onClick={() => console.log('Selected moments:', selectedMoments)}
            >
              Create Lineup ({selectedMoments.length})
            </button>
          )}
        </div>
      </div>

      <div className="bg-gray-100 p-4 rounded-lg text-sm font-mono">
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
            className={`border rounded-lg p-4 shadow-lg cursor-pointer transition-all
              ${selectedMoments.includes(moment.id) ? 'border-green-500 bg-green-50' : 'hover:border-gray-400'}`}
            onClick={() => toggleMomentSelection(moment.id)}
          >
            <div className="flex justify-between items-start">
              <h3 className="text-xl font-bold">{moment.metadata?.fullName ?? `Moment #${moment.id}`}</h3>
              <span className="text-sm bg-gray-100 px-2 py-1 rounded">
                #{moment.metadata?.jerseyNumber ?? '-'}
              </span>
            </div>
            
            <p className="text-gray-600">{moment.metadata?.primaryPosition ?? ''}</p>
            
            <div className="mt-2 p-2 bg-gray-50 rounded">
              <p>{moment.metadata?.playType ?? ''} - {moment.metadata?.playCategory ?? ''}</p>
              <p className="text-sm text-gray-500">
                {moment.metadata?.homeTeamName ?? ''} vs {moment.metadata?.awayTeamName ?? ''}
              </p>
              <p className="text-sm text-gray-500">
                {moment.metadata?.homeTeamScore ?? ''} - {moment.metadata?.awayTeamScore ?? ''}
              </p>
            </div>

            <div className="mt-2 flex justify-between text-sm text-gray-500">
              <p>Serial: #{moment.metadata?.serialNumber ?? '-'}</p>
              <p>Series {moment.metadata?.seriesNumber ?? '-'}</p>
            </div>
            
            <p className="text-sm text-gray-500">{moment.metadata?.setName ?? ''}</p>
          </div>
        ))}
      </div>
    </div>
  )
} 