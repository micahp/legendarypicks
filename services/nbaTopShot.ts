import * as fcl from "@onflow/fcl"

// Script to get all NFTs in a user's collection
const getMomentIDs = `
  import TopShot from 0x877931736ee77cff
  import HybridCustody from 0xd8a7e05a7ac670c0

  pub fun main(account: Address): [UInt64] {
    // Get the manager to access linked accounts
    let manager = getAuthAccount(account).storage
      .borrow<&HybridCustody.Manager>(from: HybridCustody.ManagerStoragePath)
    
    var allMomentIds: [UInt64] = []
    
    // First get moments from main account
    let mainCollection = getAccount(account)
      .getCapability(/public/MomentCollection)
      .borrow<&{TopShot.MomentCollectionPublic}>()
    
    if let collection = mainCollection {
      allMomentIds.append(contentsOf: collection.getIDs())
    }
    
    // Then get moments from linked accounts
    if let manager = manager {
      for childAddress in manager.getChildAddresses() {
        let childCollection = getAccount(childAddress)
          .getCapability(/public/MomentCollection)
          .borrow<&{TopShot.MomentCollectionPublic}>()
        
        if let collection = childCollection {
          allMomentIds.append(contentsOf: collection.getIDs())
        }
      }
    }
    
    return allMomentIds
  }
`

// Script to get metadata for a specific moment
const getMomentMetadata = `
  import TopShot from 0x877931736ee77cff
  import MetadataViews from 0x631e88ae7f1d7c20
  import HybridCustody from 0xd8a7e05a7ac670c0

  pub fun main(account: Address, id: UInt64): {String: AnyStruct} {
    // Try main account first
    let mainCollection = getAccount(account)
      .getCapability(/public/MomentCollection)
      .borrow<&{TopShot.MomentCollectionPublic}>()
    
    if let collection = mainCollection {
      if let moment = collection.borrowMoment(id: id) {
        return resolveMomentMetadata(moment)
      }
    }
    
    // Try linked accounts
    let manager = getAuthAccount(account).storage
      .borrow<&HybridCustody.Manager>(from: HybridCustody.ManagerStoragePath)
    
    if let manager = manager {
      for childAddress in manager.getChildAddresses() {
        let childCollection = getAccount(childAddress)
          .getCapability(/public/MomentCollection)
          .borrow<&{TopShot.MomentCollectionPublic}>()
        
        if let collection = childCollection {
          if let moment = collection.borrowMoment(id: id) {
            return resolveMomentMetadata(moment)
          }
        }
      }
    }
    
    panic("Could not find moment with ID: ".concat(id.toString()))
  }

  pub fun resolveMomentMetadata(moment: &{TopShot.MomentNFT}): {String: AnyStruct} {
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