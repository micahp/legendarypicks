import "TopShot"

transaction(momentMetaData: {String: String}) {
  // Private reference to this account's Admin resource
  let AdminRef: &TopShot.Admin
  let CollectionRef: &TopShot.Collection
       
  prepare(account: AuthAccount) {
    // Borrow a reference for the Admin in storage
    self.AdminRef = account.borrow<&TopShot.Admin>(from: /storage/TopShotAdmin)
        ?? panic("Could not borrow Admin reference")
    log("got AdminRef successfully")

    // Borrow a reference for the Collection in storage
    self.CollectionRef = account.borrow<&TopShot.Collection>(from: /storage/MomentCollection)
        ?? panic("Could not borrow Admin reference")
    log("got Admin Collection Ref successfully")
  }
  
  execute {

    // Get the recipient's public account object
    let recipient = getAccount(0x11a1b8a51a86f2a1)
    log(recipient.address)

    // Get the Collection reference for the receiver
    // getting the public capability and borrowing a reference from it
    let receiverRef = recipient.getCapability(/public/MomentCollection)
      .borrow<&{TopShot.MomentCollectionPublic}>() 
      ?? panic("Could not borrow nft receiver reference")
    log("obtained receiverRef successfully")
    
    // Add new Play with moment meta data
    let newPlayId = self.AdminRef.createPlay(metadata: momentMetaData)
    log(newPlayId);

    // Add new Set with set name and borrow its resource
    let newSetId = self.AdminRef.createSet(name: "NewSet")
    let newSet = self.AdminRef.borrowSet(setID: newSetId)
    log(newSet.setID)

    // Add new play to the net set
    newSet.addPlay(playID: newPlayId);
    log(newSet.getPlays())

    // Mint an NFT and deposit it into admin account's collection
    receiverRef.deposit(token: <-newSet.mintMoment(playID: newPlayId))
    log("Owned Moments")
    log(receiverRef.getIDs())
  }
}
