import * as fcl from "@onflow/fcl"

const TOPSHOT_ADDRESS = process.env.NEXT_PUBLIC_TOPSHOT_ADDRESS || "0x0b2a3299cc857e29"
const METADATAVIEWS_ADDRESS = process.env.NEXT_PUBLIC_METADATAVIEWS_ADDRESS || "0x1d7e57aa55817448"
const VIEWRESOLVER_ADDRESS = process.env.NEXT_PUBLIC_VIEWRESOLVER_ADDRESS || METADATAVIEWS_ADDRESS

// Cadence 1.0 script to get all Moment IDs via public capability
const getMomentIDs = `
  import TopShot from ${TOPSHOT_ADDRESS}

  access(all) fun main(account: Address): [UInt64] {
    let ids: [UInt64] = []
    if let collection = getAccount(account)
      .capabilities
      .borrow<&{TopShot.MomentCollectionPublic}>(/public/MomentCollection) {
      ids.appendAll(collection.getIDs())
    }
    return ids
  }
`

// Cadence 1.0 script to get metadata for a specific moment via view resolver
const getMomentMetadata = `
  import TopShot from ${TOPSHOT_ADDRESS}
  import MetadataViews from ${METADATAVIEWS_ADDRESS}
  import ViewResolver from ${VIEWRESOLVER_ADDRESS}

  access(all) fun main(account: Address, id: UInt64): {String: AnyStruct} {
    if let collection = getAccount(account)
      .capabilities
      .borrow<&{TopShot.MomentCollectionPublic}>(/public/MomentCollection) {
      if let nft = collection.borrowNFT(id) {
        let resolver = nft as &{ViewResolver.Resolver}
        if let anyView = resolver.resolveView(Type<TopShot.TopShotMomentMetadataView>()) {
          if let v = anyView as? TopShot.TopShotMomentMetadataView {
            return {
              "fullName": v.fullName,
              "playCategory": v.playCategory,
              "playType": v.playType,
              "teamAtMoment": v.teamAtMoment,
              "serialNumber": v.serialNumber,
              "setName": v.setName,
              "seriesNumber": v.seriesNumber,
              "jerseyNumber": v.jerseyNumber,
              "primaryPosition": v.primaryPosition,
              "dateOfMoment": v.dateOfMoment,
              "homeTeamName": v.homeTeamName,
              "awayTeamName": v.awayTeamName,
              "homeTeamScore": v.homeTeamScore,
              "awayTeamScore": v.awayTeamScore
            }
          }
        }
      }
    }
    panic("Could not find moment with ID: ".concat(id.toString()))
  }
`

export const NBATopShotService = {
  // Get all moment IDs for an account
  getMomentIDs: async (address: string) => {
    try {
      console.log("Executing getMomentIDs script for address:", address)
      return await fcl.query({
        cadence: getMomentIDs,
        args: (arg: any, t: any) => [arg(address, t.Address)]
      })
    } catch (error) {
      console.error("Error getting moment IDs for address", address, ":", error)
      console.error("Script:", getMomentIDs)
      return []
    }
  },

  // Get metadata for a specific moment
  getMomentMetadata: async (address: string, id: number) => {
    try {
      console.log("Fetching metadata for moment", id, "from address:", address)
      return await fcl.query({
        cadence: getMomentMetadata,
        args: (arg: any, t: any) => [
          arg(address, t.Address),
          arg(id, t.UInt64)
        ]
      })
    } catch (error) {
      console.error("Error getting metadata for moment", id, "from address", address, ":", error)
      console.error("Script:", getMomentMetadata)
      return null
    }
  }
} 