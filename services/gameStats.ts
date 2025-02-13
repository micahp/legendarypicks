import * as fcl from "@onflow/fcl"

const updateGameStatsTx = `
  import LegendaryPicksContest from 0xLEGENDARYPICKS

  transaction(gameId: String, playerStats: {String: UFix64}) {
    prepare(signer: AuthAccount) {
      let contestManager = signer.borrow<&LegendaryPicksContest.ContestManager>(
        from: /storage/LegendaryPicksContestManager
      ) ?? panic("Could not borrow contest manager")

      contestManager.updateGameStats(gameId: gameId, playerStats: playerStats)
    }
  }
`

export const GameStatsService = {
  updateGameStats: async (gameId: string, playerStats: { [playerId: string]: number }) => {
    try {
      // Convert player stats to UFix64 format
      const formattedStats: { [key: string]: string } = {}
      for (const [playerId, score] of Object.entries(playerStats)) {
        formattedStats[playerId] = score.toFixed(8)
      }

      const txId = await fcl.mutate({
        cadence: updateGameStatsTx,
        args: (arg: any, t: any) => [
          arg(gameId, t.String),
          arg(formattedStats, t.Dictionary({ key: t.String, value: t.UFix64 }))
        ],
        limit: 1000
      })

      return await fcl.tx(txId).onceSealed()
    } catch (error) {
      console.error("Error updating game stats:", error)
      throw error
    }
  },

  // Calculate player score based on game performance
  calculatePlayerScore: (stats: any): number => {
    // Example scoring system
    return (
      (stats.points || 0) * 1.0 +
      (stats.rebounds || 0) * 1.2 +
      (stats.assists || 0) * 1.5 +
      (stats.steals || 0) * 2.0 +
      (stats.blocks || 0) * 2.0 -
      (stats.turnovers || 0) * 1.0
    )
  }
} 