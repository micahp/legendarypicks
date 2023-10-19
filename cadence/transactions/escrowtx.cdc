import "Escrow"

transaction() {
  // Private reference to this account's Admin resource
  let AdminRef: &Escrow.Admin

  prepare(account: AuthAccount) {
    // Borrow a reference for the Admin in storage
    self.AdminRef = account.borrow<&Escrow.Admin>(from: /storage/EscrowAdmin)
        ?? panic("Could not borrow Admin reference")
    log("got AdminRef successfully")
  }
  execute{
    self.AdminRef.depositMoment(address: 0x01, momentID: 10)
    log(Escrow.getDepositedMoments())
  }
}