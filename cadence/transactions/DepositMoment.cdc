import "TopShot"
import NonFungibleToken from 0xf8d6e0586b0a20c7

transaction(escrowAddress:Address, momentID: UInt64) {

  // The field that will hold the NFT as it is being transferred to the other account
  let transferToken: @NonFungibleToken.NFT
       
  prepare(account: AuthAccount) {

    // Borrow a reference from the stored collection
    let collectionRef = account.borrow<&TopShot.Collection>(from: /storage/MomentCollection) ?? panic("Could not borrow nft collection reference")
    log("obtained collectionRef successfully")
    
    log("Sender Owned Moments")
    log(collectionRef.getIDs())
    // Call the withdraw function on the sender's Collection to move the NFT out of the collection
    self.transferToken <- collectionRef.withdraw(withdrawID: momentID)

  }
  
  execute {
    // Get the recipient's public account object
    let recipient = getAccount(escrowAddress)

    // Get the Collection reference for the receiver
    // getting the public capability and borrowing a reference from it
    let receiverRef = recipient.getCapability(/public/MomentCollection)
      .borrow<&{TopShot.MomentCollectionPublic}>() 
      ?? panic("Could not borrow nft receiver reference")
    log("obtained receiverRef successfully")


    // deposit moment into escrow account's collection
    receiverRef.deposit(token: <-self.transferToken)
    log("Escrow Owned Moments")
    log(receiverRef.getIDs())

  }
}