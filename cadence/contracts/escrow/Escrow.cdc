pub contract Escrow {
  // variable dictory of deposited moments
  access(self) var depositedMoments: {Address : UInt64}

  // Admin is a special authorization resource that allows the owner to perform important functions 
  pub resource Admin{
    // Function to deposit a moment
    pub fun depositMoment(address: Address, momentID: UInt64) {
        if Escrow.depositedMoments[address] == nil {
            Escrow.depositedMoments[address] = momentID
        }
    }

    // Function to withdraw a moment
    pub fun withdrawMoment(address: Address, momentID: UInt64) {
        if Escrow.depositedMoments[address] == momentID {
            Escrow.depositedMoments.remove(key: address)
        }
    }
  }

  // Function to check if a given address has deposited moment and return them
  pub fun getDepositedMoment(address: Address): UInt64? {
      return self.depositedMoments[address]
  }

  // Function to check if a specific momentId is deposited by the given address
  pub fun hasDepositedMoment(address: Address): Bool {
      return self.depositedMoments[address] != nil
  }

  // Function to get the whole list of deposited moments
  pub fun getDepositedMoments(): {Address : UInt64} {
      return self.depositedMoments
  } 
  
  init() {
    // Initialize the deposited moments field to an empty
    self.depositedMoments = {};

    // Put the Admin in storage
    self.account.save<@Admin>(<- create Admin(), to: /storage/EscrowAdmin)
  }
}   