import { useEffect, useState } from 'react'
import * as fcl from "@onflow/fcl"
import { NBAGameService } from '../services/nbaGames'
import { ContestService } from '../services/contestService'
import { NBATopShotService } from '../services/nbaTopShot'
import ContestLeaderboard from './ContestLeaderboard'

interface Contest {
  contestId: number
  gameIds: string[]
  startTime: number
  endTime: number
  entryFee: number
  maxEntries: number
  requirements: {
    requiredPositions: { [key: string]: number }
    maxPlayersPerTeam: number
    totalPlayers: number
  }
}

interface Moment {
  id: number
  metadata: {
    fullName: string
    playCategory: string
    playType: string
    teamAtMoment: string
    position: string
    jerseyNumber: string
  }
  selected?: boolean
}

export default function ContestEntry({ contest }: { contest: Contest }) {
  const [moments, setMoments] = useState<Moment[]>([])
  const [selectedMoments, setSelectedMoments] = useState<number[]>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchMoments = async () => {
      const user = await fcl.currentUser.snapshot()
      if (!user?.addr) return

      const momentIds = await NBATopShotService.getMomentIDs(user.addr)
      const momentData = await Promise.all(
        momentIds.map(async (id: number) => {
          const metadata = await NBATopShotService.getMomentMetadata(user.addr!, id)
          return { id, metadata }
        })
      )

      setMoments(momentData)
      setLoading(false)
    }

    fetchMoments()
  }, [])

  const validateLineup = () => {
    // Implement lineup validation logic based on contest requirements
    const selectedMomentData = moments.filter(m => selectedMoments.includes(m.id))
    
    // Check total players
    if (selectedMomentData.length !== contest.requirements.totalPlayers) {
      return `Must select exactly ${contest.requirements.totalPlayers} players`
    }

    // Check position requirements
    const positionCounts: { [key: string]: number } = {}
    selectedMomentData.forEach(moment => {
      const position = moment.metadata.position
      positionCounts[position] = (positionCounts[position] || 0) + 1
    })

    for (const [position, required] of Object.entries(contest.requirements.requiredPositions)) {
      if ((positionCounts[position] || 0) < required) {
        return `Need ${required} ${position} players`
      }
    }

    // Check team limits
    const teamCounts: { [key: string]: number } = {}
    selectedMomentData.forEach(moment => {
      const team = moment.metadata.teamAtMoment
      teamCounts[team] = (teamCounts[team] || 0) + 1
      if (teamCounts[team] > contest.requirements.maxPlayersPerTeam) {
        return `Maximum ${contest.requirements.maxPlayersPerTeam} players per team allowed`
      }
    })

    return null
  }

  const handleSubmitEntry = async () => {
    const validationError = validateLineup()
    if (validationError) {
      setError(validationError)
      return
    }

    try {
      setSubmitting(true)
      setError(null)
      
      await ContestService.submitEntry(contest.contestId, selectedMoments)
      
      // Reset selection
      setSelectedMoments([])
    } catch (error) {
      console.error("Error submitting entry:", error)
      setError('Failed to submit entry. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return <div className="text-sm text-zinc-400">Loading your moments...</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-bold">Create Lineup</h2>
        <div className="text-sm text-zinc-500">
          Selected: {selectedMoments.length} / {contest.requirements.totalPlayers}
        </div>
      </div>

      {error && (
        <div className="border border-red-900/40 bg-red-900/20 text-red-300 p-3 rounded-lg">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {moments.map((moment) => (
          <div 
            key={moment.id}
            className={`p-4 border border-zinc-800 rounded-lg cursor-pointer transition ${
              selectedMoments.includes(moment.id) ? 'border-emerald-500/70 bg-emerald-500/10' : 'hover:bg-zinc-900'
            }`}
            onClick={() => {
              if (selectedMoments.includes(moment.id)) {
                setSelectedMoments(selectedMoments.filter(id => id !== moment.id))
              } else if (selectedMoments.length < contest.requirements.totalPlayers) {
                setSelectedMoments([...selectedMoments, moment.id])
              }
            }}
          >
            <div className="flex justify-between">
              <div>
                <p className="font-semibold">{moment.metadata.fullName}</p>
                <p className="text-sm text-zinc-500">
                  {moment.metadata.position} - {moment.metadata.teamAtMoment}
                </p>
              </div>
              <div className="text-sm bg-zinc-800 px-2 py-1 rounded">
                #{moment.metadata.jerseyNumber}
              </div>
            </div>
          </div>
        ))}
      </div>

      <button
        className="w-full bg-emerald-500 text-black font-semibold px-4 py-2 rounded-lg disabled:opacity-50 hover:bg-emerald-400"
        onClick={handleSubmitEntry}
        disabled={submitting || selectedMoments.length !== contest.requirements.totalPlayers}
      >
        {submitting ? 'Submitting...' : 'Submit Lineup'}
      </button>

      <ContestLeaderboard contest={contest} />
    </div>
  )
} 