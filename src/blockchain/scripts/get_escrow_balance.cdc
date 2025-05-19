// src/blockchain/scripts/get_escrow_balance.cdc
import FantasyEscrow from 0xFantasyEscrowPlaceholder // Will be replaced by config

// Script to get the balance of a specific contest pool in the FantasyEscrow contract.
// Takes contestId as an argument.
pub fun main(contestId: String): UFix64? {
    // Call the public function on the FantasyEscrow contract
    let balance = FantasyEscrow.getContestPoolBalance(contestId: contestId)
    
    if balance == nil {
        log("No contest pool found for ID: ".concat(contestId))
    } else {
        log("Balance for contest pool ".concat(contestId).concat(": ").concat(balance!.toString()))
    }
    
    return balance
}
