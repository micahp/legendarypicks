import "TopShot"
import "NonFungibleToken"

transaction() {
       
  prepare(account: AuthAccount) {
    // store an empty Moment Collection in account storage
    account.save<@NonFungibleToken.Collection>(<-TopShot.createEmptyCollection(), to: /storage/MomentCollection)

    // publish a capability to the Collection in storage
    account.link<&{TopShot.MomentCollectionPublic}>(/public/MomentCollection, target: /storage/MomentCollection)

    log("Created a new empty collection and published a reference")
  }
}
