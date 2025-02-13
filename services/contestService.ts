import * as fcl from "@onflow/fcl"

const createContestTx = `
  import LegendaryPicksContest from 0xLEGENDARYPICKS

  transaction(
    gameIds: [String],
    startTime: UFix64,
    endTime: UFix64,
    entryFee: UFix64,
    maxEntries: UInt64
  ) {
    prepare(signer: AuthAccount) {
      let contestManager = signer.borrow<&LegendaryPicksContest.ContestManager>(
        from: /storage/LegendaryPicksContestManager
      ) ?? panic("Could not borrow contest manager")

      contestManager.createContest(
        gameIds: gameIds,
        startTime: startTime,
        endTime: endTime,
        entryFee: entryFee,
        maxEntries: maxEntries
      )
    }
  }
`

const getContestsTx = `
  import LegendaryPicksContest from 0xLEGENDARYPICKS

  pub fun main(): {UInt64: LegendaryPicksContest.Contest} {
    let contests: {UInt64: LegendaryPicksContest.Contest} = {}
    let contestManager = getAccount(0xLEGENDARYPICKS)
      .getCapability(/public/LegendaryPicksContestManager)
      .borrow<&LegendaryPicksContest.ContestManager>()
      ?? panic("Could not borrow contest manager")

    return contestManager.getContests()
  }
`

const submitEntryTx = `
  import LegendaryPicksContest from 0xLEGENDARYPICKS

  transaction(contestId: UInt64, momentIds: [UInt64]) {
    prepare(signer: AuthAccount) {
      let contestManager = getAccount(0xLEGENDARYPICKS)
        .getCapability(/public/LegendaryPicksContestManager)
        .borrow<&LegendaryPicksContest.ContestManager>()
        ?? panic("Could not borrow contest manager")

      contestManager.submitEntry(
        contestId: contestId,
        momentIds: momentIds,
        participant: signer.address
      )
    }
  }
`

export const ContestService = {
  createContest: async (
    gameIds: string[],
    startTime: number,
    endTime: number,
    entryFee: number,
    maxEntries: number
  ) => {
    try {
      const txId = await fcl.mutate({
        cadence: createContestTx,
        args: (arg: any, t: any) => [
          arg(gameIds, t.Array(t.String)),
          arg(startTime.toFixed(8), t.UFix64),
          arg(endTime.toFixed(8), t.UFix64),
          arg(entryFee.toFixed(8), t.UFix64),
          arg(maxEntries, t.UInt64)
        ],
        limit: 1000
      })

      return await fcl.tx(txId).onceSealed()
    } catch (error) {
      console.error("Error creating contest:", error)
      throw error
    }
  },

  getContests: async () => {
    try {
      return await fcl.query({
        cadence: getContestsTx
      })
    } catch (error) {
      console.error("Error getting contests:", error)
      return {}
    }
  },

  submitEntry: async (contestId: number, momentIds: number[]) => {
    try {
      const txId = await fcl.mutate({
        cadence: submitEntryTx,
        args: (arg: any, t: any) => [
          arg(contestId, t.UInt64),
          arg(momentIds, t.Array(t.UInt64))
        ],
        limit: 1000
      })

      return await fcl.tx(txId).onceSealed()
    } catch (error) {
      console.error("Error submitting entry:", error)
      throw error
    }
  }
} 