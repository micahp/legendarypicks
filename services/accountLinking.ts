import * as fcl from "@onflow/fcl"

const createChildAccount = `
  import HybridCustody from 0xHYBRIDCUSTODY

  transaction(publicKey: String) {
    prepare(signer: AuthAccount) {
      // Create the child account with the provided public key
      let newAccount = AuthAccount(payer: signer)

      // Setup hybrid custody for the new account
      HybridCustody.createChildAccount(
        parent: signer,
        child: newAccount,
        publicKey: publicKey
      )
    }
  }
`

const linkAccounts = `
  import HybridCustody from 0xHYBRIDCUSTODY

  transaction(childAddress: Address) {
    prepare(signer: AuthAccount) {
      // Setup the parent account to manage the child account
      HybridCustody.linkAccounts(
        parent: signer,
        childAddress: childAddress
      )
    }
  }
`

const getLinkedAccounts = `
  import HybridCustody from 0xHYBRIDCUSTODY

  pub fun main(address: Address): [Address] {
    return HybridCustody.getChildAccounts(parent: address)
  }
`

export const AccountLinkingService = {
  createChildAccount: async (publicKey: string) => {
    try {
      const txId = await fcl.mutate({
        cadence: createChildAccount,
        args: (arg: any, t: any) => [arg(publicKey, t.String)],
        limit: 1000
      })

      return await fcl.tx(txId).onceSealed()
    } catch (error) {
      console.error("Error creating child account:", error)
      throw error
    }
  },

  linkAccounts: async (childAddress: string) => {
    try {
      const txId = await fcl.mutate({
        cadence: linkAccounts,
        args: (arg: any, t: any) => [arg(childAddress, t.Address)],
        limit: 1000
      })

      return await fcl.tx(txId).onceSealed()
    } catch (error) {
      console.error("Error linking accounts:", error)
      throw error
    }
  },

  getLinkedAccounts: async (address: string) => {
    try {
      return await fcl.query({
        cadence: getLinkedAccounts,
        args: (arg: any, t: any) => [arg(address, t.Address)]
      })
    } catch (error) {
      console.error("Error getting linked accounts:", error)
      return []
    }
  }
} 