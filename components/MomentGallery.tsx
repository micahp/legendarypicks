import { useEffect, useState } from 'react'
import * as fcl from "@onflow/fcl"
import { NBATopShotService } from '../services/nbaTopShot'
import { AccountLinkingService } from '../services/accountLinking'

interface Moment {
  id: number
  metadata: {
    fullName: string
    playCategory: string
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

  useEffect(() => {
    fcl.currentUser.subscribe(setUser)
  }, [])

  useEffect(() => {
    const fetchLinkedAccounts = async () => {
      if (!user.addr) return
      const accounts = await AccountLinkingService.getLinkedAccounts(user.addr)
      setLinkedAccounts(accounts)
      setSelectedAccount(user.addr)
    }

    fetchLinkedAccounts()
  }, [user.addr])

  useEffect(() => {
    const fetchMoments = async () => {
      if (!selectedAccount) return

      const momentIds = await NBATopShotService.getMomentIDs(selectedAccount)
      
      const momentData = await Promise.all(
        momentIds.map(async (id: number) => {
          const metadata = await NBATopShotService.getMomentMetadata(selectedAccount, id)
          return { id, metadata, selected: false }
        })
      )

      setMoments(momentData)
    }

    fetchMoments()
  }, [selectedAccount])

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

  if (!user.addr) {
    return (
      <div className="flex flex-col items-center justify-center h-64">
        <h2 className="text-2xl font-bold mb-4">Welcome to Legendary Picks</h2>
        <p className="text-gray-600 mb-4">Connect your wallet to view your NBA Top Shot moments</p>
      </div>
    )
  }

  const filteredMoments = filterMoments(moments)

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold">Your NBA Top Shot Collection</h2>
        <div className="flex gap-2">
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

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filteredMoments.map((moment) => (
          <div 
            key={moment.id} 
            className={`border rounded-lg p-4 shadow-lg cursor-pointer transition-all
              ${selectedMoments.includes(moment.id) ? 'border-green-500 bg-green-50' : 'hover:border-gray-400'}`}
            onClick={() => toggleMomentSelection(moment.id)}
          >
            <div className="flex justify-between items-start">
              <h3 className="text-xl font-bold">{moment.metadata.fullName}</h3>
              <span className="text-sm bg-gray-100 px-2 py-1 rounded">
                #{moment.metadata.jerseyNumber}
              </span>
            </div>
            
            <p className="text-gray-600">{moment.metadata.primaryPosition}</p>
            
            <div className="mt-2 p-2 bg-gray-50 rounded">
              <p>{moment.metadata.playType} - {moment.metadata.playCategory}</p>
              <p className="text-sm text-gray-500">
                {moment.metadata.homeTeamName} vs {moment.metadata.awayTeamName}
              </p>
              <p className="text-sm text-gray-500">
                {moment.metadata.homeTeamScore} - {moment.metadata.awayTeamScore}
              </p>
            </div>

            <div className="mt-2 flex justify-between text-sm text-gray-500">
              <p>Serial: #{moment.metadata.serialNumber}</p>
              <p>Series {moment.metadata.seriesNumber}</p>
            </div>
            
            <p className="text-sm text-gray-500">{moment.metadata.setName}</p>
          </div>
        ))}
      </div>
    </div>
  )
} 