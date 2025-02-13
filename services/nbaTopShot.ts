import * as fcl from "@onflow/fcl"

// Script to get all NFTs in a user's collection
const getMomentIDs = `
  import TopShot from 0x877931736ee77cff

  pub fun main(account: Address): [UInt64] {
    let collectionRef = getAccount(account)
      .getCapability(/public/MomentCollection)
      .borrow<&{TopShot.MomentCollectionPublic}>()
      ?? panic("Could not get public moment collection reference")
    
    return collectionRef.getIDs()
  }
`

// Script to get metadata for a specific moment
const getMomentMetadata = `
  import TopShot from 0x877931736ee77cff
  import MetadataViews from 0x631e88ae7f1d7c20

  pub fun main(account: Address, id: UInt64): {String: AnyStruct} {
    let collectionRef = getAccount(account)
      .getCapability(/public/MomentCollection)
      .borrow<&{TopShot.MomentCollectionPublic}>()
      ?? panic("Could not get public moment collection reference")

    let moment = collectionRef.borrowMoment(id: id)
      ?? panic("Could not borrow moment reference")

    let view = moment.resolveView(Type<TopShot.TopShotMomentMetadataView>())
      ?? panic("Could not resolve view")

    let metadata = view as! TopShot.TopShotMomentMetadataView

    return {
      "fullName": metadata.fullName,
      "playCategory": metadata.playCategory,
      "playType": metadata.playType,
      "teamAtMoment": metadata.teamAtMoment,
      "serialNumber": metadata.serialNumber,
      "setName": metadata.setName,
      "seriesNumber": metadata.seriesNumber,
      "jerseyNumber": metadata.jerseyNumber,
      "primaryPosition": metadata.primaryPosition,
      "dateOfMoment": metadata.dateOfMoment,
      "homeTeamName": metadata.homeTeamName,
      "awayTeamName": metadata.awayTeamName,
      "homeTeamScore": metadata.homeTeamScore,
      "awayTeamScore": metadata.awayTeamScore
    }
  }
`

export const NBATopShotService = {
  // Get all moment IDs for an account
  getMomentIDs: async (address: string) => {
    try {
      return await fcl.query({
        cadence: getMomentIDs,
        args: (arg: any, t: any) => [arg(address, t.Address)]
      })
    } catch (error) {
      console.error("Error getting moment IDs:", error)
      return []
    }
  },

  // Get metadata for a specific moment
  getMomentMetadata: async (address: string, id: number) => {
    try {
      return await fcl.query({
        cadence: getMomentMetadata,
        args: (arg: any, t: any) => [
          arg(address, t.Address),
          arg(id, t.UInt64)
        ]
      })
    } catch (error) {
      console.error("Error getting moment metadata:", error)
      return null
    }
  }
} 