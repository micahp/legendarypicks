import "Escrow"

transaction (sender:Address, momentID: UInt64) {
  // Private reference to this account's Admin resource
  let AdminRef: &Escrow.Admin

  prepare(account: AuthAccount) {
    // Borrow a reference for the Admin in storage
    self.AdminRef = account.borrow<&Escrow.Admin>(from: /storage/EscrowAdmin)
        ?? panic("Could not borrow Admin reference")
    log("got AdminRef successfully")
  }

  execute{
    // Deposit moment
    self.AdminRef.depositMoment(address: sender, momentID: momentID)
    log("Deposited Moments")
    log(Escrow.getDepositedMoments())
  }
}