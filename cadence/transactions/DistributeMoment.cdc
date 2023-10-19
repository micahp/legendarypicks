import "TopShot"
import "Escrow"
import NonFungibleToken from 0xf8d6e0586b0a20c7

transaction(address: Address, distributeID: UInt64) {

  // The field that will hold the NFT as it is being transferred to the other account
  let transferToken: @NonFungibleToken.NFT
  
  // Private reference to this account's Admin resource
  let AdminRef: &Escrow.Admin
       
  prepare(account: AuthAccount) {

    // Borrow a reference from the stored collection
    let collectionRef = account.borrow<&TopShot.Collection>(from: /storage/MomentCollection) ?? panic("Could not borrow moment collection reference")
    log("obtained collectionRef successfully")
    
    log("Escrow Owned Moments")
    log(collectionRef.getIDs())
    // Call the withdraw function on the sender's Collection to move the NFT out of the collection
    self.transferToken <- collectionRef.withdraw(withdrawID: distributeID)


    // Borrow a reference for the Escrow Admin in storage
    self.AdminRef = account.borrow<&Escrow.Admin>(from: /storage/EscrowAdmin)
        ?? panic("Could not borrow Admin reference")
    log("got Escrow AdminRef successfully")
  }
  
  execute {
    // Get the recipient's public account object
    let recipient = getAccount(address)

    // Get the Collection reference for the receiver
    // getting the public capability and borrowing a reference from it
    let receiverRef = recipient.getCapability(/public/MomentCollection)
      .borrow<&{TopShot.MomentCollectionPublic}>() 
      ?? panic("Could not borrow nft receiver reference")
    log("obtained receiverRef successfully")


    // Mint an NFT and deposit it into receiver account's collection
    receiverRef.deposit(token: <-self.transferToken)
    log("Receiver Owned Moments")
    log(receiverRef.getIDs())

    // Withdraw Moment from Escrow
    self.AdminRef.withdrawMoment(address:address, momentID:distributeID)
    log("Escrow owned Moments")
    log(Escrow.getDepositedMoments())
    
  }
}