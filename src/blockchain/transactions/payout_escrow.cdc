// src/blockchain/transactions/payout_escrow.cdc
import FantasyEscrow from 0xFantasyEscrowPlaceholder // Will be replaced by config
// FungibleToken and FlowToken imports are not directly needed here if FantasyEscrow handles vault interactions.

transaction(contestId: String, winnerAddresses: [Address], winnerAmounts: [UFix64]) {
    
    prepare(signer: AuthAccount) {
        // The FantasyEscrow.payout() function has a `pre` condition checking:
        // `self.account.address == self.adminAddress`.
        // This means this transaction MUST be signed by the adminAddress defined in the FantasyEscrow contract.
        // No specific resources need to be borrowed by the signer here related to the FantasyEscrow contract itself,
        // as the contract's methods will handle its own resources based on the signer's authority.
        log("Payout transaction prepare phase by signer: ".concat(signer.address.toString()))
    }

    execute {
        // Construct the array of WinnerPayout structs for the payout function
        var winnerPayouts: [FantasyEscrow.WinnerPayout] = []
        var i = 0
        while i < winnerAddresses.length {
            if winnerAmounts[i] <= 0.0 {
                panic("Winner amount must be positive.") // Adding basic validation
            }
            winnerPayouts.append(
                FantasyEscrow.WinnerPayout( // This struct is defined in FantasyEscrow contract
                    address: winnerAddresses[i], 
                    amount: winnerAmounts[i]
                )
            )
            i = i + 1
        }

        // Call the payout function on the imported FantasyEscrow contract
        FantasyEscrow.payout(contestId: contestId, winners: winnerPayouts)
        
        log("Payout transaction executed for contest: ".concat(contestId))
    }
}
